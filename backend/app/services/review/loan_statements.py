"""
Loans without a loans register (no loan schedule to split interest from capital):

  U-LOAN-004  The lender's year-end statement, its balance typed on the Balance sheet tab against the loan, against
              the books after the year's repayments. Owed more per the statement: the year's interest, charged to the
              loan (journal Dr interest / Cr the loan); owed less: a repayment or drawdown to find.
  U-LOAN-005  A loan account paid into debit (more repaid than was ever owed): the loan is missing from the books (a
              mortgage is paid by the lender straight to the solicitor, so it never shows on the bank statement), the
              payments belong to another loan, or part of them is interest. The lender's statement is asked for.
  U-LOAN-006  A loan owed at the year end with no lender statement typed and no loans register: the client is asked
              for the statement (balance and interest charged, so interest owed at the year end is found), whether the
              loan is secured and how much falls due after five years (small company disclosures, FRS 102 1AC); each
              loan is matched to its lender's statement.
With a loans register the agreement's schedule decides instead (loans_review.loan_schedule_points).
"""

from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.review.loans_review import INTEREST_CODE, MIN_AMOUNT, OTHER_INTEREST, _journal


def loan_codes(tb_records: List[TBRecord]) -> Dict[int, str]:
    """The loan accounts in the books: code -> name (the loan codes, and loan-named accounts on the other creditors)."""
    from backend.app.services.workbook.balance_tabs import (
        CREDITOR_LOAN_CODES, LOAN_NAME, LOANS_AFTER_1_YEAR, LOANS_WITHIN_1_YEAR, NOT_A_LOAN)
    out: Dict[int, str] = {}
    for t in tb_records:
        if t.std_code in LOANS_WITHIN_1_YEAR + LOANS_AFTER_1_YEAR or (
                t.std_code in CREDITOR_LOAN_CODES and LOAN_NAME.search(t.raw_account_name or "")
                and not NOT_A_LOAN.search(t.raw_account_name or "")):
            out.setdefault(int(t.std_code), t.raw_account_name or "")
    return out


def _interest(engagement: ClientEngagement, code: int, name: str, owed: float, books: float, chart,
              counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    where = f"{name} ({code})"
    diff = round(owed - books, 2)
    if diff >= MIN_AMOUNT:
        interest_code = INTEREST_CODE.get(code, OTHER_INTEREST)
        entry = (f"Dr {interest_code} {chart.name(interest_code)} (£{diff:,.2f}) / "
                 f"Cr {code} {chart.name(code)} (£{diff:,.2f})")
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-004",
            procedure_name="Loans: interest from the lender's statement", severity="HIGH" if diff >= 1000 else "MEDIUM",
            source_row_ref=where[:100], finding_title=f"{name[:80]}: interest £{diff:,.2f} not charged to the loan"[:255],
            finding_details=(f"The lender's statement shows £{owed:,.2f} owed at the year end (typed on the Balance "
                             f"sheet tab); the books show £{books:,.2f} after the year's repayments. The repayments "
                             f"were all taken off the loan, but part of them was interest: £{diff:,.2f}, charged to "
                             f"interest. A journal is proposed (Journals tab): {entry}. Check it against the interest "
                             f"on the statement."),
            quantified_amount=diff, suggested_journal=entry, status="OPEN")
        return [f], [_journal(engagement, counter, f"Interest on {name[:80]} (lender's statement)", interest_code,
                              code, diff, chart, f)]
    if diff <= -MIN_AMOUNT:
        return [AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-004",
            procedure_name="Loans: interest from the lender's statement", severity="MEDIUM", source_row_ref=where[:100],
            finding_title=f"{name[:80]}: the books owe £{-diff:,.2f} more than the lender's statement"[:255],
            finding_details=(f"The lender's statement shows £{owed:,.2f} owed at the year end; the books show "
                             f"£{books:,.2f}. A repayment is missing from this loan (paid from another account, or "
                             f"posted to another loan), or last year's balance is wrong."),
            quantified_amount=-diff, status="OPEN")], []
    return [], []


def loan_statement_points(engagement: ClientEngagement, tb_records: List[TBRecord], chart, db: Session,
                          counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.loans.agreements import agreement_schedules
    from backend.app.services.reconciliation.control_accounts import entered_inputs, statement_balance
    from backend.app.services.tax.ct_computation import final_balances
    codes = loan_codes(tb_records)
    if not codes:
        return [], []
    after = final_balances(engagement.id, tb_records, db)
    opening: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code in codes:
            opening[int(t.std_code)] = opening.get(int(t.std_code), 0.0) + float(t.opening_amount or 0)
    inputs = entered_inputs(db, engagement.id)
    register = bool(agreement_schedules(engagement, db))
    findings: List[AuditFinding] = []
    journals: List[ProposedJournal] = []
    settled: set = set()
    if not register:
        findings, journals = _settled_hp(engagement, tb_records, after, chart, counter)
        settled = {c for pair in SETTLED_PAIRS for c in pair
                   if any(f.source_row_ref == chart.name(pair[0])[:100] for f in findings)}
    for code, name in sorted(codes.items()):
        if code in settled:
            continue                     # a paid-off hire purchase: its own point (U-LOAN-008)
        books = round(-after.get(code, 0.0), 2)                              # owed: a credit, as a positive figure
        repaid = round(after.get(code, 0.0) - opening.get(code, 0.0), 2)     # the year's debits less credits
        statement = statement_balance(inputs.get(f"code:{code}"))
        if statement is not None and not register:
            f, j = _interest(engagement, code, name, abs(statement), books, chart, counter)
            findings += f
            journals += j
            continue
        if books <= -MIN_AMOUNT and repaid >= MIN_AMOUNT:
            where = f"{name} ({code})"
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-005",
                procedure_name="Loans: repaid more than owed", severity="HIGH" if -books >= 1000 else "MEDIUM",
                source_row_ref=where[:100],
                finding_title=f"{name[:80]}: £{repaid:,.2f} repaid in the year leaves £{-books:,.2f} in debit"[:255],
                finding_details=(f"Repayments of £{repaid:,.2f} were posted to {where}, which leaves it £{-books:,.2f} "
                                 f"in debit: more paid than the books ever owed. Either the loan is missing from the "
                                 f"books (a mortgage taken out to buy a property is paid by the lender straight to the "
                                 f"solicitor, so it never shows on the bank statement), the payments belong to another "
                                 f"loan, or part of them is interest. Client question: please send the lender's "
                                 f"statement for the year (balance at the year end and interest charged) and, for a new "
                                 f"mortgage, the mortgage offer and the completion statement."),
                quantified_amount=-books, status="OPEN"))
        elif books >= MIN_AMOUNT and not register:
            where = f"{name} ({code})"
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-006",
                procedure_name="Loans: lender statement", severity="MEDIUM" if books >= 1000 else "LOW",
                source_row_ref=where[:100],
                finding_title=f"{name[:80]}: £{books:,.2f} owed, no lender statement"[:255],
                # Our steps first, then the client's question alone (the Queries tab and the client email take only it)
                finding_details=(f"The books owe £{books:,.2f} on {where} at the year end and no lender statement is "
                                 f"entered. Type the statement balance on the Balance sheet tab; the loans tab (G4) "
                                 f"compares it. Interest owed but not yet charged is a journal. Small company accounts "
                                 f"disclose whether the loan is secured and how much falls due after five years (FRS 102 "
                                 f"1AC; a charge is on the company's Companies House record). Client question: please "
                                 f"send the lender's statement at the year end (the balance and the interest charged in "
                                 f"the year), and tell us whether the loan is secured (on what) and how much of it falls "
                                 f"due after five years."),
                quantified_amount=books, status="OPEN"))
    if not register:                     # with a loans register its schedule gives the interest
        findings += _no_interest_points(engagement, tb_records, codes, after, chart, db)
    return findings, journals


HP_PAIRS = ((5000, 5001), (5010, 5011))      # hire purchase / finance lease: due within one year, after one year
# Bank, other and debenture loans: a loan paid off whose balance b/f sits on one code and the repayments on the other
# (e.g. a mortgage b/f on 5100 and its repayments leaving 5500 the same in debit: both are cleared)
LOAN_PAIRS = ((5100, 5500), (5110, 5510), (5120, 5520))
SETTLED_PAIRS = HP_PAIRS + LOAN_PAIRS
KIND = {5000: "Hire purchase", 5010: "Finance lease", 5100: "Bank loan", 5110: "Other loan", 5120: "Debenture"}
SETTLED_PAID = 0.9                           # repaid in the year at least this share of what was owed at the start


def _settled_hp(engagement: ClientEngagement, tb_records: List[TBRecord], after: Dict[int, float], chart,
                counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """U-LOAN-008: a hire purchase paid off in the year whose two accounts are left with balances that cancel or
    overpay (e.g. 5000 in credit and 5001 slightly more in debit after the year's repayments). A finished agreement
    owes nothing (FRS 102 s20, BIM45355): both accounts are cleared and the overpaid part is finance charge (HP
    interest). A small balance still owed may be the last instalment after the year end: asked, not
    cleared."""
    from backend.app.services.review.payroll_journals import _journal_lines
    opening: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code is not None:
            opening[int(t.std_code)] = opening.get(int(t.std_code), 0.0) + float(t.opening_amount or 0)
    findings: List[AuditFinding] = []
    journals: List[ProposedJournal] = []
    for pair in SETTLED_PAIRS:
        kind = KIND[pair[0]]
        owed_start = round(-sum(opening.get(c, 0.0) for c in pair), 2)
        now = {c: round(after.get(c, 0.0), 2) for c in pair}
        combined = round(sum(now.values()), 2)               # debit positive: overpaid
        paid = round(sum(now.values()) - sum(opening.get(c, 0.0) for c in pair), 2)
        if owed_start < 1000 or not any(abs(v) >= MIN_AMOUNT for v in now.values()) or paid < SETTLED_PAID * owed_start:
            continue
        if abs(combined) > max(500.0, 0.05 * owed_start):
            continue                                         # still owing (or overpaid) a real amount: not settled
        names = "; ".join(f"{c} {chart.name(c)} £{abs(v):,.2f} {'Dr' if v > 0 else 'Cr'}" for c, v in now.items() if v)
        interest = INTEREST_CODE.get(pair[0], OTHER_INTEREST)
        if combined < -MIN_AMOUNT:
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-008",
                procedure_name=f"{kind}: paid off?", severity="MEDIUM", source_row_ref=chart.name(pair[0])[:100],
                finding_title=f"{kind}: £{owed_start:,.2f} owed at the start, £{-combined:,.2f} left after "
                              f"£{paid:,.2f} repaid"[:255],
                finding_details=(f"The {kind.lower()} accounts show {names}: almost all of it was repaid this year. "
                                 f"If the agreement is finished, the £{-combined:,.2f} left is finance charge (Dr "
                                 f"{pair[0]} / Cr {interest} {chart.name(interest)}); if a last instalment is due after "
                                 f"the year end, it stays. Client question: has it been paid off? Please send "
                                 f"the lender's settlement statement."),
                quantified_amount=-combined, status="OPEN"))
            continue
        lines = [(c, -v, 0.0) if v < 0 else (c, 0.0, v) for c, v in now.items() if v]
        if combined >= MIN_AMOUNT:
            lines.append((interest, combined, 0.0))          # paid more than owed: the excess was finance charge
        entry = "; ".join(f"{'Dr' if dr else 'Cr'} {c} {chart.name(c)} £{(dr or cr):,.2f}" for c, dr, cr in lines)
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-008",
            procedure_name=f"{kind}: paid off", severity="MEDIUM", source_row_ref=chart.name(pair[0])[:100],
            finding_title=f"{kind} paid off: clear {pair[0]} and {pair[1]}"
                          + (f", £{combined:,.2f} overpaid to HP interest" if combined >= MIN_AMOUNT else ""),
            finding_details=(f"£{owed_start:,.2f} was owed at the start of the year and £{paid:,.2f} repaid, which leaves "
                             f"{names}. A loan or agreement paid off owes nothing (FRS 102 s20, s11): both accounts are cleared"
                             + (f" and the £{combined:,.2f} paid over the balance is finance charge" if combined >= MIN_AMOUNT
                                else "") + f". A journal is proposed (Journals tab): {entry}. Check the finance "
                             f"company's settlement statement."),
            quantified_amount=max(abs(v) for v in now.values()), suggested_journal=entry[:255], status="OPEN")
        findings.append(f)
        journals.append(_journal_lines(engagement, counter, f"{kind} paid off: {pair[0]} and {pair[1]} cleared",
                                       lines, chart, f))
    return findings, journals


def _no_interest_points(engagement: ClientEngagement, tb_records: List[TBRecord], codes: Dict[int, str],
                        after: Dict[int, float], chart, db: Session) -> List[AuditFinding]:
    """U-LOAN-007: last year's paper accrued interest, and this year loans are owed with no interest charged on any
    interest payable account (no interest at all, with no such history, is the library's U-LOAN-001 question).
    Either the lender's interest sits inside the repayments taken off the loan (the statement splits it, U-LOAN-004),
    or interest has built up and not been charged: it is accrued at the year end (FRS 102 s2 accruals basis; e.g. an
    investor loan's interest accrued by days). A loan really interest-free
    says so. Last year's paper accruing interest is quoted: the same loan likely needs it again."""
    from backend.app.models.yearend_adjustments import YearEndAdjustment
    from backend.app.services.sop.common import gl_lines
    owed = {c: round(-after.get(c, 0.0), 2) for c in codes}
    owed = {c: v for c, v in owed.items() if v >= LOAN_INTEREST_MIN}
    if not owed:
        return []
    charged = sum(l.debit - l.credit for l in gl_lines(str(engagement.id), tb_records, db)
                  if chart.section(l.code) == "Interest payable and similar charges")
    if charged >= MIN_AMOUNT:
        return []
    last = [r for r in db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == engagement.id,
                                                           YearEndAdjustment.period == "LAST_YEAR",
                                                           YearEndAdjustment.kind == "ACCRUAL")
            if "interest" in (r.description or "").lower()]
    if not last:
        return []                        # no interest at all is the library's question (U-LOAN-001, query_triggers)
    listed = "; ".join(f"{name[:60]} ({code}) £{owed[code]:,.2f}" for code, name in sorted(codes.items()) if code in owed)
    total = round(sum(owed.values()), 2)
    before = ("" if not last else " Last year's paper accrued interest: " + "; ".join(
        f"{(r.description or '').split(' (last year')[0][:60]} £{float(r.amount):,.2f}" for r in last) + ". The same "
        "loan probably needs this year's interest accrued too.")
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-007",
        procedure_name="Loans: interest", severity="MEDIUM",
        source_row_ref="Loans (G4)", finding_title=f"Interest accrued last year, none charged this year on loans of £{total:,.2f}"[:255],
        finding_details=(f"Owed at the year end: {listed}. No interest is charged in the year on any interest account. "
                         f"Either the lender's interest is inside the repayments taken off the loan (the lender's "
                         f"statement splits it: type its balance on the Balance sheet tab), or interest has built up "
                         f"and has not been charged: accrue it at the year end, balance x rate x days / 365 (Dr 3631 "
                         f"Other interest payable / Cr 5360 Accruals; FRS 102 s2). A loan that is really "
                         f"interest-free: say so (a related party lending below market rate: FRS 102 11.13)."
                         f"{before} Client question: does each loan carry interest, at what rate, and has the lender "
                         f"charged it for the year?"),
        quantified_amount=total, status="OPEN",
        figures=_interest_figures(codes, owed, last, total))]


def _interest_figures(codes, owed, last, total):
    """U-LOAN-007 interest: each loan owed, last year's interest accrued, nothing charged this year."""
    from backend.app.services.review.point_figures import amounts
    return amounts([(f"{name[:60]} ({code})", owed[code]) for code, name in sorted(codes.items()) if code in owed]
                   + [("Loans owed at the year end", total, True)]
                   + [(f"Interest accrued last year: {(r.description or '').split(' (last year')[0][:50]}", float(r.amount))
                      for r in last]
                   + [("Interest charged this year", 0.0, True)])


LOAN_INTEREST_MIN = 1000.0      # a smaller loan's interest is not worth a point
