"""PAYE / NI and pension: the year-end PAYE creditor is agreed to the HMRC PAYE account statement and the pension
creditor to the provider's statement (sheet H1.1 HMRC details). The
payroll report and the ledger cannot give the figure on their own (arrears, payments to another account, penalties),
so the app does not guess it: the accountant types the statement's balance on the Balance sheet tab, and the app
- shows beside it what the payroll report says: last month's amount due (normally all that is unpaid at the year
  end), and the year's amounts due less the payments to HMRC in the ledger;
- compares the books with the statement and raises the difference with those figures (U-PAY-020 / U-PAY-021);
- asks the client for the statement while it is not in (the same points, as a client question)."""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, PAYE_NIC

PENSION_PAYABLE = 5352
TOLERANCE = 1.0
NAME = "M5 PAYE / NI and pension (G7, G8)"


@dataclass
class PayrollFigures:
    last_month: str = ""           # 'Mar 2025'
    last_due: float = 0.0          # owed for the last payroll month of the year (to HMRC, or to the pension)
    year_due: float = 0.0          # the year's months together
    paid: float = 0.0              # payments in the ledger (debits on the account)
    opening: float = 0.0           # owed at the start of the year
    months: int = 0

    @property
    def expected(self) -> float:
        return round(self.opening + self.year_due - self.paid, 2)


def _year(engagement: ClientEngagement) -> Tuple[date, date]:
    end = engagement.period_end_date
    try:
        start = date(end.year - 1, end.month, end.day) + timedelta(days=1)
    except ValueError:
        start = date(end.year - 1, 3, 1)
    return start, end


def payroll_figures(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session,
                    kind: str = "paye") -> Optional[PayrollFigures]:
    """What the payroll report and the ledger say about PAYE ('paye') or the pension ('pension'); None without a
    payroll report for the year."""
    from backend.app.services.sop.common import code_matcher, ledger_rows
    start, end = _year(engagement)
    from backend.app.services.review.payroll_period import usable
    report = [p for p in usable(engagement, db)[0] if p.period_end and start <= p.period_end <= end]
    if not report:
        return None
    # What HMRC is owed for a month is the PAYE, NI and student loan less the employment allowance and statutory pay
    # recovered (NIM06575: the allowance comes off each month's employer NI)
    due_of = (lambda p: float(p.total_hmrc_due or 0) - float(p.statutory_pay_recovered or 0)) if kind == "paye" else \
        (lambda p: float(p.pension_employee or 0) + float(p.pension_employer or 0))
    by_month: Dict[date, float] = {}
    for p in report:
        key = date(p.period_end.year, p.period_end.month, 1)
        by_month[key] = by_month.get(key, 0.0) + due_of(p)
    if kind == "paye":
        from backend.app.models.payroll_allowance import PayrollAllowance
        for a in db.query(PayrollAllowance).filter(PayrollAllowance.engagement_id == engagement.id).all():
            key = date(a.period_end.year, a.period_end.month, 1) if a.period_end else None
            if key in by_month:
                by_month[key] = max(0.0, by_month[key] - float(a.amount or 0))
    last = max(by_month)
    out = PayrollFigures(last_month=f"{last:%b %Y}", last_due=round(by_month[last], 2),
                         year_due=round(sum(by_month.values()), 2), months=len(by_month))
    codes = {PAYE_NIC} if kind == "paye" else {PENSION_PAYABLE}
    code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))
    for tx in ledger_rows(str(engagement.id), db):
        if code_of(tx.raw_account_name) in codes and tx.transaction_date and start <= tx.transaction_date <= end:
            out.paid += float(tx.debit_amount or 0)
    out.paid = round(out.paid, 2)
    out.opening = round(-sum(float(t.opening_amount or 0) for t in tb_records if t.std_code in codes), 2)
    return out


def help_note(f: Optional[PayrollFigures], kind: str = "paye") -> str:
    """The payroll's figures beside the statement box on the Balance sheet tab."""
    if f is None:
        return ""
    who = "HMRC" if kind == "paye" else "the pension provider"
    return (f"Payroll report: {f.last_month} owed £{f.last_due:,.2f} (normally all that is unpaid at the year end); "
            f"the year's {f.months} months owed £{f.year_due:,.2f}, the ledger shows £{f.paid:,.2f} paid to {who}"
            + (f" with £{f.opening:,.2f} owed at the start" if abs(f.opening) >= TOLERANCE else "") + ".")


def _owed_figures(f: Optional[PayrollFigures], books: float, statement: Optional[float] = None) -> Optional[str]:
    """PAYE or pension owed: the payroll's year (owed at the start, owed for the year, paid), the last month, the books
    and the statement."""
    from backend.app.services.review.point_figures import amounts
    rows = []
    if f is not None:
        if abs(f.opening) >= TOLERANCE:
            rows.append(("Owed at the start", f.opening))
        rows += [(f"Owed for the year per the payroll ({f.months} months)", f.year_due), ("Paid per the ledger", f.paid),
                 (f"Owed for {f.last_month} (usually all that is unpaid)", f.last_due)]
    rows.append(("Owed per the books at the year end", books, statement is None))
    if statement is not None:
        rows += [("Per the statement", statement), ("Difference", books - statement, True)]
    return amounts(rows) if len(rows) > 1 else None


def statement_points(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                     materiality: float = 1000.0) -> List[AuditFinding]:
    """U-PAY-020 (PAYE) and U-PAY-021 (pension): the books against the statement typed on the Balance sheet tab, or
    the statement asked for while it is not in."""
    from backend.app.services.reconciliation.control_accounts import entered_inputs, statement_balance
    from backend.app.services.tax.ct_computation import final_balances
    inputs = entered_inputs(db, engagement.id)
    after = final_balances(str(engagement.id), tb_records, db)
    out = []
    from backend.app.services.mapping.chart_lookup import foreign_tax_on_paye_code
    foreign = foreign_tax_on_paye_code(tb_records)
    if foreign:
        owed = round(-after.get(PAYE_NIC, 0.0), 2)
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-024",
            procedure_name="Foreign tax on the PAYE code", severity="MEDIUM", source_row_ref=foreign[:100],
            finding_title=f"{foreign[:60]} £{owed:,.2f} on {PAYE_NIC}: tax owed abroad, not PAYE"[:255],
            finding_details=(f"The account on {PAYE_NIC} is '{foreign}': tax owed to an overseas tax authority, not "
                             f"PAYE and NI, so it is not agreed to the HMRC PAYE statement. Agree it to the overseas "
                             f"tax assessments, and decide on the tax computation (H1) how much of the foreign tax is "
                             f"relieved against UK corporation tax (double tax relief, TIOPA 2010 Part 2)."),
            quantified_amount=abs(owed), status="OPEN"))
    for kind, code, ref, what, doc in (("paye", PAYE_NIC, "U-PAY-020", "PAYE and NI", "HMRC PAYE account statement"),
                                       ("pension", PENSION_PAYABLE, "U-PAY-021", "pension", "pension provider's statement")):
        if kind == "paye" and foreign:
            continue
        figures = payroll_figures(engagement, tb_records, db, kind)
        books = round(-after.get(code, 0.0), 2) or 0.0     # owed + (no '-0.00')
        entered = inputs.get(f"code:{code}")
        if entered and entered.get("agreed"):
            continue
        statement = statement_balance(entered)
        if figures is None and abs(books) < TOLERANCE and statement is None:
            continue            # no payroll report and nothing owed: nothing to agree
        if kind == "pension" and figures is not None and figures.year_due < TOLERANCE and abs(books) < TOLERANCE:
            continue            # a payroll with no pension
        payroll = help_note(figures, kind)
        if statement is None:
            if figures is not None and abs(books - figures.last_due) <= TOLERANCE:
                continue        # the books hold last month's amount: the usual year end, nothing to ask
            out.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=ref, procedure_name=NAME,
                severity="MEDIUM" if abs(books) >= materiality or (figures and abs(books - figures.last_due) >= materiality) else "LOW",
                source_row_ref=f"{chart.name(code, what)} ({code})",
                finding_title=f"{what[0].upper() + what[1:]} owed £{books:,.2f} in the books: agree it to the {doc}"[:255],
                finding_details=(
                    f"The books show £{books:,.2f} of {what} owed at the year end. {payroll} "
                    f"Type the {doc}'s balance at the year end on the Balance sheet tab ({code}) to agree it.\n\n"
                    f"Query to the client: Please send the {doc} showing the balance at "
                    f"{engagement.period_end_date:%d/%m/%Y} (what was owed and what was paid)."),
                quantified_amount=abs(books), status="OPEN", figures=_owed_figures(figures, books)))
            continue
        diff = round(books - statement, 2)
        if abs(diff) < TOLERANCE:
            continue
        hint = ""
        if figures is not None and abs(statement - figures.last_due) <= TOLERANCE and diff > 0:
            hint = "The statement shows only last month's amount, so the year's earlier months are paid: the books' " \
                   "extra is payments posted to another account, or months posted twice. "
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=ref, procedure_name=NAME,
            severity="HIGH" if abs(diff) >= materiality else "MEDIUM", source_row_ref=f"{chart.name(code, what)} ({code})",
            finding_title=(f"{what[0].upper() + what[1:]}: books £{books:,.2f} v {doc} £{statement:,.2f}, "
                           f"a difference of £{abs(diff):,.2f}")[:255],
            finding_details=(
                f"The books show £{books:,.2f} of {what} owed at the year end; the {doc} shows £{statement:,.2f} "
                f"({'the books owe more' if diff > 0 else 'the books owe less'}). {payroll} {hint}"
                "Usual causes: payments to HMRC posted to another account, payroll months not posted, employer NI or "
                "the employment allowance not posted, interest or penalties not posted. Find the cause and put it right "
                "with a journal on the Journals tab."),
            quantified_amount=abs(diff), status="OPEN", figures=_owed_figures(figures, books, statement)))
    return out


# The 13-character accounts office reference, and the HMRC offices PAYE is paid to (as a contact or in the narrative)
PAYE_REF = re.compile(r"\b\d{3}P[A-Z]\d{7,8}\b|cumbernauld|shipley", re.I)


def paye_line_kind(desc: str, source: str = "") -> str:
    """'VAT' or 'CT' when a line on the PAYE account is that tax by its bank narrative (after the contact), else ""."""
    from backend.app.services.reconciliation.control_accounts import CT_TEXT, JOURNAL_SOURCE, OTHER_TAX_TEXT, VAT_WORDS
    narrative = desc.split(" - ", 1)[1] if " - " in desc else ""
    if not narrative or JOURNAL_SOURCE.search(source) or PAYE_REF.search(desc):
        return ""
    if CT_TEXT.search(narrative):
        return "CT"
    return "VAT" if VAT_WORDS.search(narrative) and not OTHER_TAX_TEXT.search(narrative) else ""


def other_tax_on_paye(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                      db: Session) -> List[AuditFinding]:
    """U-PAY-022: VAT or corporation tax paid to HMRC but posted to the PAYE account (5320; it moves to 5300 or 5310),
    the mirror of V-M08 on the VAT account. Read as there: only the
    bank narrative counts (after the contact: one HMRC contact is often used for every tax), NDDS is how VAT is
    collected, and a line naming PAYE, NI or the PAYE accounts office reference stays PAYE. A question with the journal
    written out, not proposed: an HMRC direct debit can be for PAYE too."""
    from backend.app.services.sop.common import gl_lines
    from backend.app.services.mapping.chart_lookup import CT_CREDITOR, VAT_CONTROL
    found: Dict[str, List[Tuple[date, str, float]]] = {"VAT": [], "CT": []}
    for l in gl_lines(str(engagement.id), tb_records, db):
        kind = paye_line_kind(l.description or "", l.source or "") if l.code == PAYE_NIC else ""
        if kind:
            found[kind].append((l.when, l.description or "", round(l.debit - l.credit, 2)))
    out = []
    for kind, (code, what) in (("VAT", (VAT_CONTROL, "VAT")), ("CT", (CT_CREDITOR, "corporation tax"))):
        lines = sorted(found[kind])
        net = round(sum(x[2] for x in lines), 2)
        if abs(net) < TOLERANCE:
            continue
        dr, cr = (code, PAYE_NIC) if net > 0 else (PAYE_NIC, code)
        entry = f"Dr {dr} {chart.name(dr)} (£{abs(net):,.2f}) / Cr {cr} {chart.name(cr)} (£{abs(net):,.2f})"
        listed = "; ".join(f"{w:%d/%m/%Y} {d[:60]} £{a:,.2f}" for w, d, a in lines[:6])
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-022", procedure_name=NAME,
            severity="MEDIUM" if abs(net) >= 500 else "LOW", source_row_ref=f"{chart.name(PAYE_NIC, 'PAYE')} ({PAYE_NIC})",
            finding_title=f"{what[0].upper() + what[1:]} {'paid to' if net > 0 else 'refunded by'} HMRC posted to the "
                          f"PAYE account? £{abs(net):,.2f}"[:255],
            finding_details=(
                f"These HMRC lines on the PAYE account say {what} in the bank narrative ({'NDDS is the direct debit HMRC '
                'collects VAT by' if kind == 'VAT' else 'corporation tax'}), with no PAYE reference: {listed}"
                f"{' and others' if len(lines) > 6 else ''}. If they paid {what}, the PAYE account looks paid when it is "
                f"not and the {what} account looks unpaid: post {entry}. If they were PAYE (HMRC also collects PAYE by "
                f"direct debit), nothing to change. Check against the HMRC PAYE statement or the {what} account."),
            quantified_amount=abs(net), status="OPEN")
        f.suggested_journal = entry
        out.append(f)
    return out


# Interest, penalties or surcharges on late PAYE / NIC, as the line names them
PAYE_INTEREST = re.compile(r"\b(interest|penalt(y|ies)|surcharge|late (filing|payment))\b", re.I)


def interest_on_paye(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                     db: Session) -> List[AuditFinding]:
    """U-PAY-023: interest or a penalty on late PAYE / NIC posted to the PAYE account (5320; it moves to the P&L,
    disallowable). Left there, the PAYE account looks paid
    when it is not and the cost is missing from the P&L; in the P&L it is not deductible (CTA 2009 s1303, BIM45740),
    which the tax computation adds back from the late payment tax charges code."""
    from backend.app.services.sop.common import gl_lines
    from backend.app.services.tax.ct_computation import LATE_TAX_CHARGES
    lines = sorted((l.when, l.description or "", round(l.debit - l.credit, 2))
                   for l in gl_lines(str(engagement.id), tb_records, db)
                   if l.code == PAYE_NIC and PAYE_INTEREST.search(l.description or "") and l.debit > l.credit)
    net = round(sum(x[2] for x in lines), 2)
    if net < TOLERANCE:
        return []
    entry = (f"Dr {LATE_TAX_CHARGES} {chart.name(LATE_TAX_CHARGES)} (£{net:,.2f}) / "
             f"Cr {PAYE_NIC} {chart.name(PAYE_NIC)} (£{net:,.2f})")
    listed = "; ".join(f"{w:%d/%m/%Y} {d[:60]} £{a:,.2f}" for w, d, a in lines[:6])
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-023", procedure_name=NAME,
        severity="MEDIUM" if net >= 500 else "LOW", source_row_ref=f"{chart.name(PAYE_NIC, 'PAYE')} ({PAYE_NIC})",
        finding_title=f"Interest or penalties on late PAYE posted to the PAYE account £{net:,.2f}"[:255],
        finding_details=(
            f"These lines on the PAYE account name interest or a penalty: {listed}"
            f"{' and others' if len(lines) > 6 else ''}. They are a cost of the year, not a payment of the PAYE owed: "
            f"post {entry}. In the tax computation they are added back (interest and penalties on late PAYE are not "
            f"deductible, CTA 2009 s1303, BIM45740)."),
        quantified_amount=net, status="OPEN")
    f.suggested_journal = entry
    return [f]
