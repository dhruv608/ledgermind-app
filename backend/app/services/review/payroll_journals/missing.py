"""U-PAY-008 payroll in the report but not in the books; wages from the bank; salary as last year."""

from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, NET_WAGES, PAYE_NIC
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from datetime import date
import json
import re

from backend.app.services.review.payroll_journals.common import (
    DIRECTOR_SALARY_CODES, MIN_AMOUNT, WAGE_COST_CODES, _entry, _journal, _journal_lines, _last_year_pay, _lines, _month, _names_person,
    _net_pay, _only_director, _words, employer_ni_on_wage_codes)


# ---------------------------------------------------------------------------------------------------------------
# U-PAY-008 Payroll not in the books
# ---------------------------------------------------------------------------------------------------------------
PENSION_OWED = 5352
DIFFERENCE_FLOOR, DIFFERENCE_SHARE = 500.0, 0.01   # a payroll difference journal from £500 or 1% of the year's pay
DIRECTORS_LOAN = 5400


# The missing payroll is posted where wages sat (last year or this year): a client whose wages are in
# cost of sales (labour of a trade) keeps them there, so the gross profit is not moved
COST_OF_SALES_WAGES = {3000: 1500, 3001: 1501, 3002: 1502, 3010: 1450}


def wage_codes(tb_records: List[TBRecord]) -> Dict[int, int]:
    """Employee-cost wage code -> the code to post to: its cost of sales twin when the client's wages sit in cost of
    sales (opening or this year) and not in employee costs, else itself."""
    def used(codes) -> bool:
        return any(t.std_code in codes and (abs(float(t.net_amount or 0)) >= 1 or abs(float(t.opening_amount or 0)) >= 1)
                   for t in tb_records)
    in_cos = used({1500, 1501, 1502, 1450}) and not used({3000, 3001, 3002})
    return {k: (v if in_cos else k) for k, v in COST_OF_SALES_WAGES.items()}


def missing_payroll(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                    chart: ChartLookup, db: Session, counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """U-PAY-008: pay the payroll report shows but the books never posted (e.g. a director's salary for the year, Dr
    3010 / Cr 5400, or payroll missing for some months). The whole year when the ledger has no wages at all, else
    the months the ledger has none for; one journal from the report's figures. Net pay goes to the director's loan when
    only directors are paid and nothing went through net wages, else to net wages."""
    from backend.app.services.tax.ct_computation import final_balances
    from backend.app.services.review.payroll_period import usable
    records, off = usable(engagement, db)
    if off:
        return [], []                       # a report for another period: the Data check asks for this year's
    after = final_balances(engagement.id, tb_records, db)
    if not records:
        found = _wages_from_bank(engagement, profile, tb_records, after, chart, db, counter)
        return found if found[0] else _salary_as_last_year(engagement, after, chart, db, counter)
    # Gross pay in the books, without employer NI the firm codes with the wages (an account named employer NI)
    books = round(sum(after.get(c, 0.0) for c in WAGE_COST_CODES) - employer_ni_on_wage_codes(tb_records), 2)
    report = round(sum(float(r.gross_pay or 0) for r in records), 2)
    short = round(report - books, 2)
    held = _pay_on_the_control(engagement, tb_records, after, short, report, books, chart)
    if held is not None:
        return [held], []
    from backend.app.services.review.dividends import DIVIDEND_WORDS
    on_wages: Dict[Tuple[int, int], float] = {}
    paid_in: Dict[Tuple[int, int], Dict[int, float]] = {}      # wage-cost debits by month and code (net pay paid in)
    journal_net: Dict[Tuple[int, int], float] = {}              # net wages credited by month (the payroll journal)
    net_wages_used = False
    paid_directors: List[str] = []
    paid_staff: List[str] = []
    directors_paid_out = False
    for code, g in _lines(engagement, tb_records, chart, db):
        if DIVIDEND_WORDS.search(g.description or ""):
            continue                        # a dividend posted to salary is not pay (U-DIV-002 moves it)
        key = (g.transaction_date.year, g.transaction_date.month) if g.transaction_date else None
        if code in WAGE_COST_CODES and float(g.debit_amount or 0) > 0 and g.description:
            # Who the books pay as a director and who as staff, by the payee the ledger line names
            (paid_directors if code in DIRECTOR_SALARY_CODES else paid_staff).append(g.description)
            if code in DIRECTOR_SALARY_CODES and "journal" not in str(g.source or "").lower():
                directors_paid_out = True   # the director's net pay paid from the bank (not a journal to the loan)
        if code in WAGE_COST_CODES and key:
            on_wages[key] = on_wages.get(key, 0.0) + float(g.net_amount or 0)
            if float(g.debit_amount or 0) > 0:
                paid_in.setdefault(key, {})
                paid_in[key][code] = paid_in[key].get(code, 0.0) + float(g.debit_amount or 0)
        elif code == NET_WAGES and abs(float(g.net_amount or 0)) >= MIN_AMOUNT:
            net_wages_used = True
            if key and float(g.credit_amount or 0) > 0:
                journal_net[key] = journal_net.get(key, 0.0) + float(g.credit_amount or 0)
    from backend.app.services.setup.engagement_setup import period_of
    period = period_of(engagement)
    first, last = (lambda d: (d.year, d.month))(date.fromisoformat(period["start"])), \
        (lambda d: (d.year, d.month))(date.fromisoformat(period["end"]))
    by_journal = False                      # months found by the payroll journal, below
    months: List[Tuple[int, int]] = []
    scale = 1.0                             # the share of the report's pay posted (below 1: the difference only)
    in_year = [r for r in records if _month(r) is None or first <= _month(r) <= last]
    if not on_wages:
        if books >= MIN_AMOUNT or short < MIN_AMOUNT:
            return [], []                   # wages on the TB but no ledger to tell the months: U-PAY-001 says the gap
        # Only the report's pay periods inside the year (the accruals basis, FRS 102 s2): a report for another year
        # books nothing
        chosen = [r for r in records if _month(r) is None or first <= _month(r) <= last]
        when = "the year" if len(chosen) == len(records) else \
            ", ".join(date(y, m, 1).strftime("%b %Y") for y, m in sorted({_month(r) for r in chosen if _month(r)}))
        if not chosen:
            return [], []
    else:
        # Month by month: a month the report pays and the books have no wages for is missing, even when the year's
        # total looks covered by small extras in other months. Not when the month next to it holds both months' pay
        # (posted a month early or late).
        by_month: Dict[Tuple[int, int], float] = {}
        for r in records:
            if _month(r) is not None and first <= _month(r) <= last:      # only pay periods inside the year
                by_month[_month(r)] = by_month.get(_month(r), 0.0) + float(r.gross_pay or 0)
        step = lambda k, n: (k[0] + (k[1] - 1 + n) // 12, (k[1] - 1 + n) % 12 + 1)
        net_by_month: Dict[Tuple[int, int], float] = {}
        for r in records:
            if _month(r) is not None and first <= _month(r) <= last:
                net_by_month[_month(r)] = net_by_month.get(_month(r), 0.0) + _net_pay(r)
        # The payroll journal (crediting net wages) is what posts a month's pay. When the books post one in most
        # months, a month without it is missing even if net pay was paid straight into the wage costs; else a month
        # the wage costs have nothing for
        journal_months = [k for k, n in net_by_month.items() if n >= MIN_AMOUNT and journal_net.get(k, 0.0) >= 0.5 * n]
        by_journal = len(journal_months) >= max(2, len(net_by_month) // 2)
        if by_journal:
            covered = lambda k: any(journal_net.get(step(k, n), 0.0) >= net_by_month.get(step(k, n), 0.0)
                                    + 0.8 * net_by_month[k] for n in (-1, 1))
            months = sorted(k for k, n in net_by_month.items()
                            if n >= MIN_AMOUNT and journal_net.get(k, 0.0) < 0.2 * n and not covered(k))
            # The year must be short as well: a month's payroll posted with another month's (two months in one
            # journal) is not missing
            short_year = sum(net_by_month.values()) - sum(v for k, v in journal_net.items() if first <= k <= last)
            if short_year < 0.5 * sum(net_by_month[k] for k in months):
                months = []
        else:
            covered = lambda k: any(on_wages.get(step(k, n), 0.0) >= by_month.get(step(k, n), 0.0) + 0.8 * by_month[k]
                                    for n in (-1, 1))
            months = sorted(k for k, pay in by_month.items()
                            if pay >= MIN_AMOUNT and abs(on_wages.get(k, 0.0)) < MIN_AMOUNT and not covered(k))
        # Months holding about twice their pay: the 'missing' ones were posted there
        doubled = sum(1 for k, pay in by_month.items() if pay >= MIN_AMOUNT and on_wages.get(k, 0.0) >= 1.8 * pay)
        chosen = [r for r in records if _month(r) in months]
        if not chosen or doubled >= len(months):
            # No month is missing, yet the report still pays more than the books hold after the journals: the
            # difference is posted so the books agree with the payroll report (reversing and reposting gives the same
            # answer). Only when the report pays MORE: a report paying less is usually part of the year, a point only
            in_year_pay = round(sum(float(r.gross_pay or 0) for r in in_year), 2)
            # Statutory maternity / paternity / adoption pay inside the gross is claimed back from HMRC: books that
            # net the claim off the wages are not short by it
            reclaimed = round(sum(float(r.statutory_pay_recovered or 0) for r in in_year), 2)
            gap = round(in_year_pay - reclaimed - books, 2)
            # Not for rounding-size gaps: a difference of a few hundred pounds is left as it is
            if gap < max(DIFFERENCE_FLOOR, DIFFERENCE_SHARE * in_year_pay) or in_year_pay < MIN_AMOUNT:
                return [], []
            chosen, months, by_journal = in_year, [], False
            scale = gap / in_year_pay
            when = "the year (the difference to the payroll report)"
        else:
            when = ", ".join(date(y, m, 1).strftime("%b %Y") for y, m in months)
    total = lambda attr: round(scale * sum(float(getattr(r, attr) or 0) for r in chosen), 2)
    gross, er_ni, er_pension = total("gross_pay"), total("employer_nic"), total("pension_employer")
    if scale < 1:
        # The difference journal is the gross pay the books miss; employer NI and pension have their own checks
        # (U-PAY-002 and the pension controls), so they are not scaled in here
        er_ni = er_pension = 0.0
    tax, ee_ni, ee_pension, student = (total("tax_deducted"), total("employee_nic"), total("pension_employee"),
                                       total("student_loan"))
    if gross < MIN_AMOUNT:
        return [], []

    # Whose pay: named people (a director by the setup's list or the word), else the directors' total the file
    # gives, else a payroll of directors only (the payroll file or last year's TB tell)
    from backend.app.models.director_pay import PayrollDirectorPay
    directors = [d for d in (json.loads(profile.directors or "[]") if profile else []) if d]
    # ...or the books themselves pay the person as a director: every wage payment naming them is on the directors'
    # pay (e.g. a named payment on 3010 each month: the missing month goes there too)
    by_books = lambda n: (any(_names_person(t, n) for t in paid_directors)
                          and not any(_names_person(t, n) for t in paid_staff))
    is_director =lambda n: bool(re.search(r"\bdirector\b", n, re.I)) or any(
        _names_person(n, d) or _words(n) == _words(d) for d in directors) or by_books(n)
    named = [r for r in chosen if r.employee_name and r.employee_name != "All employees"]
    dp = db.query(PayrollDirectorPay).filter(PayrollDirectorPay.engagement_id == engagement.id).first()
    last_directors, last_staff = _last_year_pay(engagement, db)
    basis = ""
    if named:
        to_directors = round(scale * sum(float(r.gross_pay or 0) for r in named if is_director(r.employee_name)), 2)
    elif dp is not None and float(dp.gross_pay or 0) >= MIN_AMOUNT:
        to_directors = round(gross * min(float(dp.gross_pay) / report, 1.0), 2)
    elif _only_director(engagement, profile, db) or (last_directors >= MIN_AMOUNT and last_staff < MIN_AMOUNT):
        to_directors, basis = gross, "last year's TB shows directors' pay only"
    elif not on_wages and books < MIN_AMOUNT and any(t.std_code == DIRECTORS_LOAN for t in tb_records):
        # No wages in the books at all and a director's loan account: the owner-director's salary
        to_directors, basis = gross, "the books have no wages at all and the director's loan account is used"
    else:
        to_directors = 0.0
    if scale < 1 and not named and dp is None:
        # The difference goes where the books hold the pay (all on 3010 directors' salaries: there too)
        wc0 = wage_codes(tb_records)
        on_directors = sum(after.get(c, 0.0) for c in (3010, wc0[3010]))
        if books >= MIN_AMOUNT and on_directors >= 0.95 * books:
            to_directors = gross
    to_staff = round(gross - to_directors, 2)
    only_directors = to_staff < MIN_AMOUNT
    net = round(gross - tax - ee_ni - ee_pension - student, 2)
    # A director paid from the bank in the other months (no net wages account): the missing month's net pay is owed
    # as wages (net wages); the loan only when the director is never paid out
    net_to = DIRECTORS_LOAN if only_directors and not net_wages_used and not directors_paid_out else NET_WAGES
    # A director's net pay not paid out (no payment into the wages for it) is credited to the director's loan: when
    # the net pay paid into the wage costs
    # those months covers the staff only, the directors' net goes to the loan
    director_net = (round(scale * sum(_net_pay(r) for r in named if is_director(r.employee_name)), 2) if named
                    else round(net * to_directors / gross, 2) if gross else 0.0)
    paid_those_months = sum(a for k in (months if by_journal else []) for a in paid_in.get(k, {}).values())
    unpaid = round(net - paid_those_months, 2)          # net pay of those months not paid into the wages
    to_loan = unpaid if (by_journal and net_to == NET_WAGES and MIN_AMOUNT <= unpaid <= director_net * 1.05) else 0.0
    wc = wage_codes(tb_records)
    lines = [(wc[3010], to_directors, 0.0), (wc[3000], to_staff, 0.0), (wc[3001], er_ni, 0.0),
             (3012 if only_directors else wc[3002], er_pension, 0.0),
             (PAYE_NIC, 0.0, tax + ee_ni + student + er_ni), (PENSION_OWED, 0.0, ee_pension + er_pension),
             (net_to, 0.0, round(net - to_loan, 2)), (DIRECTORS_LOAN, 0.0, to_loan)]
    entry = "; ".join(f"{'Dr' if dr else 'Cr'} {c} {chart.name(c)} £{(dr or cr):,.2f}" for c, dr, cr in lines
                      if round(dr, 2) or round(cr, 2))
    who = ("the directors'" if only_directors else "staff" if to_directors < MIN_AMOUNT
           else f"£{to_directors:,.2f} of it the directors'")
    loan = (" No net pay went through net wages, so it is owed to the director on the director's loan (paid through "
            "the loan account)." if net_to == DIRECTORS_LOAN else
            f" The directors' net pay (£{to_loan:,.2f}) was not paid out with the staff's, so it is credited to the "
            f"director's loan." if to_loan else "")
    guess = ("" if named or dp is not None else
             " The payroll file does not name the people: " + (f"it is taken as the directors' pay, as {basis}; "
             f"check it is not staff pay." if only_directors else "it is taken as staff wages; move the directors' part "
             "to 3010 if they are on it."))
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-008",
        procedure_name="Payroll: pay not in the books", severity="HIGH" if gross >= 1000 else "MEDIUM",
        source_row_ref="Payroll report vs books",
        finding_title=f"Payroll £{gross:,.2f} for {when} is not in the books"[:255],
        finding_details=(f"The payroll report shows gross pay of £{report:,.2f}; the wage accounts hold £{books:,.2f}"
                         + (" and the ledger has no wages at all" if not on_wages else
                            f": the difference, £{gross:,.2f}, is posted so the books agree with the report" if scale < 1
                            else f", with nothing for {when}")
                         + f". The pay ({who}) is missing from the costs, so profit is overstated. A journal from the "
                           f"payroll report is proposed (Journals tab): {entry}.{loan}{guess}"),
        quantified_amount=gross, suggested_journal=entry[:1000], status="OPEN")
    label = ("Director's salary recorded for the year" if only_directors and not on_wages and when == "the year"
             else f"Payroll recorded for {when}")
    journals = [_journal_lines(engagement, counter, f"{label} (payroll report)", lines, chart, f)]
    # The net pay of those months paid straight into the wage costs: moved to net wages, which the payroll journal
    # credits, so the cost is not counted twice
    moved: Dict[int, float] = {}
    if by_journal and net_to == NET_WAGES:
        for k in months:
            for code, amount in paid_in.get(k, {}).items():
                moved[code] = moved.get(code, 0.0) + amount
    moved = {c: round(a, 2) for c, a in moved.items() if a >= MIN_AMOUNT}
    if moved:
        total_moved = round(sum(moved.values()), 2)
        re_lines = [(NET_WAGES, total_moved, 0.0)] + [(c, 0.0, a) for c, a in moved.items()]
        f.finding_details = (f.finding_details + " The net pay for those months was paid straight into the wage "
                             f"costs (£{total_moved:,.2f}): a second journal moves it to {NET_WAGES} "
                             f"{chart.name(NET_WAGES)}, so the cost is not counted twice.")
        journals.append(_journal_lines(engagement, counter, f"Net pay for {when} paid straight into wages, moved to "
                                                            f"net wages", re_lines, chart, f))
    return [f], journals


# A wage cost by its name (not the net wages / PAYE control accounts themselves)
WAGE_COST_NAME = re.compile(r"\b(wages?|salar(y|ies)|remuneration)\b", re.I)
CONTROL_NAME = re.compile(r"\b(net|control|payable|owed|owing|liabilit\w*|accrued|deductions?)\b", re.I)


def _pay_on_the_control(engagement: ClientEngagement, tb_records: List[TBRecord], after: Dict[int, float],
                        short: float, report: float, books: float, chart: ChartLookup) -> Optional[AuditFinding]:
    """Pay the report shows and the wage costs do not may already be in the books on the wrong code (postings
    touching net wages 5330 and the wage codes are looked at first): an account named as a wage cost sitting on net
    wages or PAYE (e.g. 'Admin Wages' coded to net wages). Then nothing is posted: a point to fix the coding first."""
    if short < MIN_AMOUNT:
        return None
    named = [t for t in tb_records if t.std_code in (NET_WAGES, PAYE_NIC) and float(t.net_amount or 0) >= MIN_AMOUNT
             and WAGE_COST_NAME.search(t.raw_account_name or "") and not CONTROL_NAME.search(t.raw_account_name or "")]
    # Only an account named as a wage cost: net wages overdrawn on its own is what a missing payroll journal looks
    # like (net pay paid from the bank, the journal never posted), so it is
    # no sign that the pay is already in the books
    if not named:
        return None
    why = "; ".join(f"{t.raw_account_name} (£{float(t.net_amount or 0):,.2f}) is coded to {t.std_code} "
                    f"{chart.name(t.std_code)} though its name says a wage cost" for t in named)
    return AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-008",
        procedure_name="Payroll: pay not in the books", severity="HIGH", source_row_ref="Payroll report v wage costs",
        finding_title=f"Payroll report £{report:,.2f} v wage costs £{books:,.2f}: check the coding before posting pay"[:255],
        finding_details=(f"The payroll report shows £{short:,.2f} more gross pay than the wage cost codes, but the pay "
                         f"looks already booked on another code: {why}. No journal is proposed: posting the difference "
                         f"would count that pay twice. Recode the account to the wage costs (or check net wages), then "
                         f"run the review again; any pay still missing is then proposed."),
        quantified_amount=short, status="OPEN")


def _wages_from_bank(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                     after: Dict[int, float], chart: ChartLookup, db: Session,
                     counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """No payroll report and no wage costs, but net pay and PAYE paid out of the bank (payments to HMRC coded as PAYE
    but no wages or NI expense): the payroll was
    run but never posted, so net wages and PAYE are left in debit. What was paid is the estimate of the wage cost
    (net pay plus PAYE and NI, employer NI within it), proposed until the payroll report gives the real figures."""
    if sum(after.get(c, 0.0) for c in WAGE_COST_CODES) >= MIN_AMOUNT:
        return [], []
    opening = {}
    for t in tb_records:
        if t.std_code in (NET_WAGES, PAYE_NIC):
            opening[t.std_code] = opening.get(t.std_code, 0.0) + float(t.opening_amount or 0)
    paid = {}
    for code in (NET_WAGES, PAYE_NIC):
        closing = round(after.get(code, 0.0), 2)                     # debit positive: paid more than posted
        if closing >= MIN_AMOUNT and closing - opening.get(code, 0.0) >= MIN_AMOUNT:
            paid[code] = closing
    if NET_WAGES not in paid and PAYE_NIC not in paid:
        return [], []
    total = round(sum(paid.values()), 2)
    wc = wage_codes(tb_records)
    cost = wc[3010] if _only_director(engagement, profile, db) else wc[3000]
    lines = [(cost, total, 0.0)] + [(c, 0.0, v) for c, v in paid.items()]
    entry = "; ".join(f"{'Dr' if dr else 'Cr'} {c} {chart.name(c)} £{(dr or cr):,.2f}" for c, dr, cr in lines)
    what = " and ".join(f"£{v:,.2f} {'net pay' if c == NET_WAGES else 'PAYE and NI'}" for c, v in paid.items())
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-009",
        procedure_name="Payroll: wages from the bank (estimate)", severity="HIGH" if total >= 1000 else "MEDIUM",
        source_row_ref="Wages paid, payroll not posted",
        finding_title=f"Wages of about £{total:,.2f} paid but not in the costs (no payroll report)"[:255],
        finding_details=(f"The bank shows {what} paid in the year, but the books have no wage costs and no payroll "
                         f"report was uploaded: the payroll was run but not posted, so profit is overstated and the "
                         f"net wages and PAYE accounts are left in debit. Until the payroll report comes, what was paid "
                         f"is taken as the wage cost (employer NI is inside the PAYE paid, and the PAYE for the last "
                         f"month, paid after the year end, is not yet in). A journal is proposed (Journals tab): "
                         f"{entry}. Ask the client for the payroll summary (P32 / RTI) for the year; once it is "
                         f"uploaded the payroll is posted from it instead."),
        quantified_amount=total, suggested_journal=entry[:1000], status="OPEN")
    return [f], [_journal_lines(engagement, counter, "Wages paid in the year (estimate from the bank, no payroll report)",
                                lines, chart, f)]


def _salary_as_last_year(engagement: ClientEngagement, after: Dict[int, float], chart: ChartLookup, db: Session,
                         counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """No payroll report and no pay in the books at all, but last year the director had a salary (Dr 3010 /
    Cr 5400): the same amount, for the accountant to confirm."""
    if sum(after.get(c, 0.0) for c in WAGE_COST_CODES) >= MIN_AMOUNT:
        return [], []
    last_directors, last_staff = _last_year_pay(engagement, db)
    if last_directors < MIN_AMOUNT or last_staff >= MIN_AMOUNT:
        return [], []
    entry = _entry(3010, DIRECTORS_LOAN, last_directors, chart)
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-008",
        procedure_name="Payroll: pay not in the books", severity="MEDIUM", source_row_ref="Directors' pay: none this year",
        finding_title=f"No director's salary this year; last year £{last_directors:,.2f}",
        finding_details=(f"Last year's TB shows a director's salary of £{last_directors:,.2f}; this year the books have no "
                         f"pay at all and no payroll report was uploaded. If the director was paid the same (usually the "
                         f"tax-free allowance, £12,570), it is recorded through the director's loan. A journal is "
                         f"proposed (Journals tab): {entry}. Confirm the amount with the payroll (RTI) or the client, "
                         f"or upload the payroll report."),
        quantified_amount=last_directors, suggested_journal=entry, status="OPEN")
    return [f], [_journal(engagement, counter, "Director's salary recorded as per last year", 3010, DIRECTORS_LOAN,
                          last_directors, chart, f)]
