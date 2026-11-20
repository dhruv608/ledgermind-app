"""U-PAY-003 employment allowance: the year's allowance, claimed through the payroll or the books."""

from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, PAYE_NIC
from typing import Dict, Iterable, List, Optional, Tuple
from sqlalchemy.orm import Session
from datetime import date
import re

from backend.app.services.review.payroll_journals.common import (
    EA_WORDS, EMPLOYER_NI_CODES, MIN_AMOUNT, _allowance_for, _entry, _journal, _lines, _only_director, _report,
    employer_ni_on_wage_codes)


def _allowance_in_period(start: date, end: date, employer_ni: float,
                         monthly: Optional[Dict[date, float]] = None) -> Tuple[float, str]:
    """The employment allowance the accounting period can use. Each tax year (6 April to 5 April) has its own
    allowance, set against employer NI as it arises from 6 April and not carried to another year (NIM06575, NIM06585).
    The period's employer NI is taken to arise evenly: for each tax year, its allowance less the NI of that tax year's
    months before the period, capped at the NI of its months inside the period. (Year end 30 June 2025, NI £3,000 a
    month: 2024/25's £5,000 was used by June 2024, 2025/26 gives £9,000 for April to June 2025.)"""
    days = (end - start).days + 1
    per_day = employer_ni / days if days > 0 else 0.0
    # The file's months are used only when they hold the year's NI (within 10%): a file with a few months would
    # understate it
    months_used = bool(monthly) and abs(sum(v for d, v in monthly.items() if start <= d <= end) - employer_ni)         <= 0.1 * employer_ni
    total, labels = 0.0, []
    year = start.year - 1
    while date(year, 4, 6) <= end:
        ty_start, ty_end = date(year, 4, 6), date(year + 1, 4, 5)
        inside = (min(end, ty_end) - max(start, ty_start)).days + 1
        if inside > 0:
            allowance = _allowance_for(ty_start, ty_end)[0]
            before = max(0, (start - ty_start).days) * per_day
            ni_inside = inside * per_day
            if months_used:
                # The payroll file's own months: this tax year's NI inside the period, and before it when the file
                # holds those months (else the even estimate before it stands)
                in_ty = {d: v for d, v in monthly.items() if ty_start <= d <= ty_end}
                ni_inside = sum(v for d, v in in_ty.items() if start <= d <= end)
                if any(d < start for d in in_ty):
                    before = sum(v for d, v in in_ty.items() if d < start)
            total += min(max(0.0, allowance - before), ni_inside)
            labels.append(f"{year}/{str(year + 1)[2:]}")
        year += 1
    return round(min(total, employer_ni), 2), " and ".join(labels)


CLASS_1A_WORDS = re.compile(r"\bp11d\b|class\s*1a", re.I)
NETTED_TOLERANCE = 5.0


def payroll_file_allowance(engagement: ClientEngagement, db: Session) -> float:
    """The employment allowance the uploaded payroll file shows for the year (its allowance column), or 0. Only the
    pay periods inside the accounts period count (the allowance is claimed per tax year, NIM06570): a
    file covering more months, or another year, does not add its other months. A file with no dated rows gives its
    one total."""
    from backend.app.models.payroll_allowance import PayrollAllowance
    from backend.app.services.review.frs102_checks import period_start
    rows = db.query(PayrollAllowance).filter(PayrollAllowance.engagement_id == engagement.id).all()
    dated = [a for a in rows if a.period_end is not None]
    if dated:
        start, end = period_start(engagement), engagement.period_end_date
        rows = [a for a in dated if start <= a.period_end <= end]
    # Payroll reports show the allowance as a deduction (-£5,000): the amount claimed is its size
    return abs(round(sum(float(a.amount or 0) for a in rows), 2))


def allowance_in_payroll(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                         chart: ChartLookup, db: Session, report_employer_ni: float, books_employer_ni: float,
                         ni_codes: Iterable[int]) -> float:
    """The employment allowance the books already hold off employer NI, or 0.

    When the allowance is claimed through the payroll, the payroll software's own journals post employer NI net of
    it, while the payroll report shows the NI before it. The gap between the two is then exactly the allowance (once
    P11D / Class 1A NI, which the payroll report does not include, is left out of the books)."""
    from backend.app.services.setup.engagement_setup import period_of
    if report_employer_ni < MIN_AMOUNT or _only_director(engagement, profile, db):
        return 0.0
    codes = set(ni_codes)
    class_1a = sum(float(g.net_amount or 0) for code, g in _lines(engagement, tb_records, chart, db)
                   if code in codes and CLASS_1A_WORDS.search(f"{g.description or ''} {g.reference or ''}"))
    gap = report_employer_ni - (books_employer_ni - class_1a)
    # The payroll file's own allowance column says how much; else the year's allowance
    expected = payroll_file_allowance(engagement, db)
    if expected < MIN_AMOUNT:
        period = period_of(engagement)
        allowance, _ = _allowance_for(date.fromisoformat(period["start"]), date.fromisoformat(period["end"]))
        expected = round(min(allowance, report_employer_ni), 2)
    if abs(gap - expected) <= NETTED_TOLERANCE or _used_up_in_payroll(engagement, db):
        return expected
    return 0.0


def _used_up_in_payroll(engagement: ClientEngagement, db: Session) -> bool:
    """The payroll report itself is after the allowance: from April, months that pay wages with nil employer NI, then
    employer NI again once the allowance is used up.
    The books post the same net figure, so the allowance is already claimed (NIM06570): no journal."""
    from backend.app.services.review.payroll_period import usable
    by_month = {}
    for r in usable(engagement, db)[0]:
        if r.period_end is not None:
            m = by_month.setdefault((r.period_end.year, r.period_end.month), [0.0, 0.0])
            m[0] += float(r.gross_pay or 0)
            m[1] += float(r.employer_nic or 0)
    nil_from_april = [k for k, (gross, ni) in by_month.items() if k[1] in (4, 5) and gross >= MIN_AMOUNT and abs(ni) < 0.005]
    ni_later = [k for k, (gross, ni) in by_month.items() if ni >= MIN_AMOUNT and any(k > n for n in nil_from_april)]
    return bool(nil_from_april) and bool(ni_later)


def _allowance_in_books(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                        db: Session) -> Dict[date, float]:
    """The employment allowance the ledger already holds off employer NI, by tax year (its 6 April start)."""
    out: Dict[date, float] = {}
    for code, g in _lines(engagement, tb_records, chart, db):
        if code in EMPLOYER_NI_CODES and EA_WORDS.search(f"{g.description or ''} {g.reference or ''}"):
            d = g.transaction_date or engagement.period_end_date
            ty = date(d.year if (d.month, d.day) >= (4, 6) else d.year - 1, 4, 6)
            out[ty] = out.get(ty, 0.0) - float(g.net_amount or 0)
    return out


def allowance_in_books_total(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                             db: Session) -> float:
    """The employment allowance the ledger holds off employer NI for the year ('EA' / 'Employment allowance' lines)."""
    return round(sum(_allowance_in_books(engagement, tb_records, chart, db).values()), 2)


def employment_allowance(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                         chart: ChartLookup, db: Session, counter: List[int], missing_employer_ni: float = 0.0,
                         claimed_in_payroll: float = 0.0, ni_not_in_books: bool = False
                         ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """U-PAY-003, plus the allowance already in the books checked against each tax year's limit (a year's journals
    can straddle two tax years: £1,922.70 for 2024/25 and £10,500 for 2025/26 is not over the limit)."""
    findings, journals = _employment_allowance(engagement, profile, tb_records, chart, db, counter,
                                               missing_employer_ni, claimed_in_payroll, ni_not_in_books)
    over = []
    for ty, amount in sorted(_allowance_in_books(engagement, tb_records, chart, db).items()):
        limit = _allowance_for(ty, date(ty.year + 1, 4, 5))[0]
        if amount > limit + MIN_AMOUNT:
            over.append(f"{ty.year}/{str(ty.year + 1)[2:]}: £{amount:,.2f} in the books v the £{limit:,.0f} allowance")
    if over:
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-003",
            procedure_name="Payroll: employment allowance", severity="MEDIUM", source_row_ref="Employment allowance",
            finding_title="Employment allowance in the books is more than the allowance for the tax year",
            finding_details=("; ".join(over) + ". The allowance is per tax year (6 April to 5 April): £5,000 up to "
                             "2024/25, £10,500 from 2025/26. Check the payroll's employment allowance journals; the "
                             "excess is employer NI still owed."),
            quantified_amount=0.0, status="OPEN"))
    return findings, journals


def _employment_allowance(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                          chart: ChartLookup, db: Session, counter: List[int], missing_employer_ni: float = 0.0,
                          claimed_in_payroll: float = 0.0, ni_not_in_books: bool = False
                          ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.tax.ct_computation import final_balances
    from backend.app.services.setup.engagement_setup import period_of
    after = final_balances(engagement.id, tb_records, db)
    # The allowance is set against Class 1 employer NI only, not P11D Class 1A (NIM06505)
    class_1a = sum(float(g.net_amount or 0) for code, g in _lines(engagement, tb_records, chart, db)
                   if code in EMPLOYER_NI_CODES and CLASS_1A_WORDS.search(f"{g.description or ''} {g.reference or ''}"))
    employer_ni = round(sum(after.get(c, 0.0) for c in EMPLOYER_NI_CODES) + employer_ni_on_wage_codes(tb_records)
                        - max(class_1a, 0.0)
                        + max(missing_employer_ni, 0.0), 2)
    if employer_ni < MIN_AMOUNT:
        return [], []

    # Already claimed: ledger lines or approved journals that say so
    claimed = sum(_allowance_in_books(engagement, tb_records, chart, db).values())
    # An approved journal claims it when it says so, or has its shape: NI owed (a creditor) debited and employer NI
    # credited in the same journal (as the accountant writes it)
    for j in db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement.id,
                                              ProposedJournal.status == "APPROVED").all():
        lines = [(int(l.account_code), float(l.debit or 0), float(l.credit or 0)) for l in (j.lines or [])] or                 [(int(j.debit_code), float(j.amount or 0), 0.0), (int(j.credit_code), 0.0, float(j.amount or 0))]
        ni_credit = sum(cr for code, dr, cr in lines if code in EMPLOYER_NI_CODES)
        creditor_debit = any(dr > 0 and (chart.section(code) or "").startswith("Current liabilities") for code, dr, cr in lines)
        worded = EA_WORDS.search(j.description or "") or any(EA_WORDS.search(l.narrative or "") for l in (j.lines or []))
        if ni_credit > 0 and (creditor_debit or worded):
            claimed += ni_credit
    # Already netted off the NI by the payroll journals (see allowance_in_payroll)
    claimed = round(max(claimed, 0.0) + max(claimed_in_payroll, 0.0), 2)

    period = period_of(engagement)
    # The payroll file's employer NI month by month, when it gives months (all its rows, so the months of a tax year
    # before the accounting year are seen too)
    monthly: Dict[date, float] = {}
    for p in _report(engagement, db):
        if p.period_end and float(p.employer_nic or 0):
            monthly[p.period_end] = monthly.get(p.period_end, 0.0) + float(p.employer_nic or 0)
    # The allowance is set against the employer NI the payroll actually charged (NIM06575), so never more than the
    # payroll report's own employer NI when it covers the year: the books can hold more on the NI code when the HMRC
    # payments (PAYE and NI together) were posted there
    start_d, end_d = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    in_period = round(sum(v for d, v in monthly.items() if start_d <= d <= end_d), 2)
    months_in = {(d.year, d.month) for d in monthly if start_d <= d <= end_d}
    period_months = (end_d.year - start_d.year) * 12 + end_d.month - start_d.month + 1
    if in_period >= MIN_AMOUNT and len(months_in) >= 0.8 * period_months:
        employer_ni = min(employer_ni, in_period)
    allowance, tax_year = _allowance_in_period(date.fromisoformat(period["start"]), date.fromisoformat(period["end"]),
                                               employer_ni + claimed, monthly or None)
    # Not available when a director is the only employee (the payroll report tells; otherwise a note)
    if _only_director(engagement, profile, db):
        return [AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-003",
            procedure_name="Payroll: employment allowance", severity="LOW", source_row_ref="Employment allowance",
            finding_title="Employment allowance not available: the only employee is a director",
            finding_details=("The only person paid above the secondary threshold is a director ("
                             + ("the payroll report" if _report(engagement, db) else
                                "the pay in the books: no staff wages above the threshold, and directors' pay too little "
                                "for two directors above it")
                             + "): a company whose only employee paid above the secondary threshold is a director "
                             "cannot claim the employment allowance, so no allowance journal is proposed."),
            quantified_amount=0.0, status="OPEN")], []

    # The payroll file shows the allowance claimed through the payroll: that amount, and the question is answered
    in_file = payroll_file_allowance(engagement, db)
    to_claim = round(min(in_file if in_file >= MIN_AMOUNT else allowance, employer_ni + claimed) - claimed, 2)
    if to_claim < MIN_AMOUNT:
        return [], []

    # Whether the client claimed it through the payroll (EPS) is in HMRC's records, not in the books or the payroll
    # report: the accountant answers it on the setup (Payroll). Not claimed: the client is entitled and can still
    # claim, but nothing is booked until HMRC has given it.
    from backend.app.services.review.setup_checks import setup_of
    payroll = setup_of(profile).get("payroll") or {}
    answer = payroll.get("allowance_claimed") or ("YES" if "Employment Allowance" in (payroll.get("features") or []) else None)
    if in_file >= MIN_AMOUNT and answer != "NO":
        answer = "YES"
    # The books hold no employer NI of their own and the review posts it from the payroll report: the client booked
    # only what it paid, and with the allowance claimed little or no employer NI was paid (NIM06575). Such clients'
    # NI is posted less the allowance (staff cost = report less the allowance): booked as claimed, with a check,
    # unless the setup says No
    assumed = answer is None and ni_not_in_books and missing_employer_ni >= MIN_AMOUNT
    if assumed:
        answer = "YES"
    if answer == "NO":
        return [AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-003",
            procedure_name="Payroll: employment allowance", severity="MEDIUM", source_row_ref="Employment allowance",
            finding_title=f"Employment allowance £{to_claim:,.2f} not claimed: the client can still claim it",
            finding_details=(f"Employer NI for the year is £{employer_ni:,.2f}; the employment allowance for {tax_year} "
                             f"is £{allowance:,.0f}. The setup says the client has not claimed it through the payroll, so "
                             f"nothing is booked. Tell the client: it is claimed on the EPS from the payroll software and "
                             f"can still be claimed for this year (up to four tax years back)."),
            quantified_amount=to_claim, status="OPEN")], []

    credit = max(EMPLOYER_NI_CODES, key=lambda c: after.get(c, 0.0)) if any(after.get(c, 0.0) > 0 for c in EMPLOYER_NI_CODES) else 3001
    entry = _entry(PAYE_NIC, credit, to_claim, chart)
    # Not known whether it was claimed (the payroll file does not show it and the setup is not answered): whether the
    # client claimed it on the EPS is in HMRC's records, not the books, and a company can also be outside it (a
    # director the only employee, or the group's one allowance used by another company). Asked, not booked: most
    # such clients turn out to need no allowance journal
    if answer != "YES":
        return [AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-003",
            procedure_name="Payroll: employment allowance", severity="MEDIUM", source_row_ref="Employment allowance",
            finding_title=f"Employment allowance up to £{to_claim:,.2f}: was it claimed through the payroll?"[:255],
            finding_details=(f"Employer NI for the year is £{employer_ni:,.2f}; the employment allowance for {tax_year} "
                             f"is £{allowance:,.0f}, so up to £{to_claim:,.2f} could be set against it (NIM06575). The "
                             f"books do not show whether the client claimed it on the payroll's EPS. Yes: answer it on "
                             f"the setup (Payroll) and the journal follows ({entry}). No: the client can still claim it "
                             f"from HMRC (up to four tax years back), so nothing is booked. Not available if a director "
                             f"is the only employee paid above the secondary threshold, or if a connected company "
                             f"claims the group's one allowance."),
            quantified_amount=to_claim, status="OPEN")], []
    unanswered = (" The books hold no employer NI of their own (the client booked what it paid), so the allowance is "
                  "taken as claimed through the payroll. Check the HMRC PAYE account or the EPS; if it was not "
                  "claimed, reject this journal and answer No on the setup (Payroll)." if assumed else
                  "" if answer == "YES" else
                  " Was it claimed through the payroll? Yes: approve the journal. No: reject it and ask the client to "
                  "claim it from HMRC. Answer it on the setup (Payroll) so the app remembers.")
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-003",
        procedure_name="Payroll: employment allowance", severity="HIGH" if to_claim >= 1000 else "MEDIUM",
        source_row_ref="Employment allowance",
        finding_title=f"Employment allowance £{to_claim:,.2f} not claimed in the books",
        finding_details=(f"Employer NI for the year is £{employer_ni:,.2f}"
                         + (f" (the payroll file shows an employment allowance of £{in_file:,.2f} claimed through the "
                            f"payroll)" if in_file >= MIN_AMOUNT else "")
                         + (f" (including £{missing_employer_ni:,.2f} from the payroll report not yet in the books)" if missing_employer_ni >= MIN_AMOUNT else "")
                         + f"; the employment allowance for {tax_year} is £{allowance:,.0f}"
                         + (f", of which £{claimed:,.2f} is already in the books" if claimed else "")
                         + f". Claimed through the payroll, it lowers employer NI and the NI owed. A journal is proposed "
                           f"(Journals tab): {entry}. Check: not available if a director is the only employee paid above "
                           f"the secondary threshold, or if the allowance is not being claimed through the payroll."
                         + unanswered
                         # Claimed (the payroll file shows it) but not shown in PAYE: a query
                         + (f" Query to the client: Please send the HMRC PAYE account statement for {tax_year}, so "
                            f"the employment allowance claimed through the payroll (£{in_file:,.2f}) can be agreed to "
                            f"the PAYE owed." if in_file >= MIN_AMOUNT else "")),
        quantified_amount=to_claim, suggested_journal=entry, status="OPEN")
    return [f], [_journal(engagement, counter, f"Employment allowance claimed ({tax_year})", PAYE_NIC, credit,
                          to_claim, chart, f)]
