"""The firm's payroll query rules the review does not ask, from the payroll report (payroll_p32_records) against the books. Each gives a query for the Queries
tab only: no review point, journal or figure changes.

  PY-03 HMRC paid for PAYE but the payroll shows no tax or NI      PY-04 net wages owed above one month's net pay
  PY-05 PAYE and NI owed not the last month's P32                   PY-06 pension owed not the last month's contributions
  PY-07 pay months missing from the payroll report (or a year-to-date total only)
  PY-09 employer NI nil although someone's pay is above the secondary threshold
  PY-10 staff paid above the auto-enrolment trigger with no workplace pension at all (directors left out)
  PY-11 directors' pay, NI and pension not split from the staff wages, and no per-employee payroll to split it"""

from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, PayrollP32Record
from backend.app.services.mapping.chart_lookup import NET_WAGES, PAYE_NIC
from backend.app.services.queries.r1_rules import _money, _query

PENSION_OWED = 5352
PAYROLL_DIFFERENCE = 50.0      # PY-05 / PY-06: owed at the year end v the last month's figures (over £50)
NIL = 1.0
# The employer's secondary threshold a year (employer NI is due on pay above it): £9,100 to 5 April 2025, £5,000 after
THRESHOLDS = ((date(2025, 4, 5), 9100.0), (date(9999, 12, 31), 5000.0))
YTD_LABEL = ("annual", "year to date", "ytd", "summary", "total")
# Auto-enrolment (Pensions Act 2008): the earnings trigger, £10,000 a year (£833 a month), unchanged for 2025-26 and
# 2026-27 (DWP review of the AE thresholds 2026/27); the employer pays at least 3% (gov.uk workplace pensions)
AE_TRIGGER_MONTH = 10000.0 / 12


def _f(v) -> float:
    return float(v or 0)


def _month(r: PayrollP32Record) -> Optional[Tuple[int, int]]:
    d = r.period_end or r.period_start
    return (d.year, d.month) if d else None


def _year_months(ye: date) -> List[Tuple[int, int]]:
    months, y, m = [], ye.year, ye.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return months[::-1]


def _period_months(eng: ClientEngagement, ye: date) -> List[Tuple[int, int]]:
    """The months of the job's period: from the month the company was formed in a first period (which can run past
    twelve months), else the twelve months to the year end."""
    from backend.app.services.setup.data_check import incorporated_in_year
    formed = incorporated_in_year(eng, eng.profile)
    if not formed:
        return _year_months(ye)
    start = date.fromisoformat(formed)
    months, y, m = [], start.year, start.month
    while (y, m) <= (ye.year, ye.month):
        months.append((y, m))
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return months


def _label(months: List[Tuple[int, int]]) -> str:
    return ", ".join(date(y, m, 1).strftime("%b %Y") for y, m in months)


def payroll_queries(db: Session, eng: ClientEngagement, balances: Dict[int, float], lines) -> List[Dict[str, Any]]:
    from backend.app.services.queries.query_list import ACCOUNTANT, CLIENT
    # (none from a report for another period: the Data check already asks for this year's, payroll_period.py)
    from backend.app.services.review.payroll_period import usable
    records = usable(eng, db)[0]
    ye: Optional[date] = eng.period_end_date
    if not records or ye is None:
        return []
    out: List[Dict[str, Any]] = []
    total = lambda rs, *attrs: round(sum(_f(getattr(r, a)) for r in rs for a in attrs), 2)
    gross = total(records, "gross_pay")
    if gross < NIL:
        return []
    by_month: Dict[Tuple[int, int], List[PayrollP32Record]] = defaultdict(list)
    for r in records:
        k = _month(r)
        if k is not None and k <= (ye.year, ye.month):
            by_month[k].append(r)
    months_in_year = sorted(k for k in by_month if k in _year_months(ye))
    ytd_only = not months_in_year or all(any(w in (r.tax_month_label or "").lower() for w in YTD_LABEL)
                                         for r in records)
    # The last three pay months, latest first: a small employer may pay HMRC quarterly, so up to three months owed
    recent = [by_month[k] for k in months_in_year[::-1][:3]]
    last = recent[0] if recent else []
    used = {l.code for l in lines}

    def agrees(owed: float, attrs: Tuple[str, ...], less: Tuple[str, ...] = ()) -> Tuple[bool, float]:
        """Owed at the year end is the last one, two or three months of the payroll (within £50)."""
        due, dues = 0.0, []
        for month in recent:
            due += total(month, *attrs) - (total(month, *less) if less else 0.0)
            dues.append(round(due, 2))
        return any(abs(owed - d) <= PAYROLL_DIFFERENCE for d in dues), (dues[0] if dues else 0.0)

    # PY-03: payments to HMRC for PAYE while the payroll report shows no tax or NI at all
    paye_paid = round(sum(l.debit for l in lines if l.code == PAYE_NIC), 2)
    deductions = total(records, "tax_deducted", "employee_nic", "employer_nic")
    if deductions < NIL and paye_paid >= NIL:
        out.append(_query("PY-03", CLIENT, f"PAYE paid to HMRC ({_money(paye_paid)}) but the payroll shows no tax or NI",
                          f"We can see payments of {_money(paye_paid)} to HMRC for PAYE, but the payroll report shows "
                          "no tax or National Insurance. Please send the P32 report (amounts due to HMRC each month) "
                          "and your HMRC PAYE account statement.", paye_paid, rule="PY-03"))

    # PY-04: net wages still owed at the year end above one month's net pay
    owed_net = -balances.get(NET_WAGES, 0.0)
    month_net = total(last, "net_pay")
    if month_net >= NIL and owed_net > month_net + PAYROLL_DIFFERENCE:
        out.append(_query("PY-04", CLIENT, f"Wages still owed to staff at the year end: {_money(owed_net)}",
                          f"The accounts show {_money(owed_net)} of wages still owed to staff at {ye:%d %B %Y}, more "
                          f"than the last month's net pay ({_money(month_net)}). Were some wages paid in cash, by a "
                          "director personally, or after the year end? Please send evidence of how and when they "
                          "were paid.", owed_net, rule="PY-04"))

    # PY-05: PAYE and NI owed at the year end v the last month(s) of the P32. Not asked on a year's total only, nor
    # when the books never use the PAYE account (the payroll posting is the review's point, U-PAY-001 / U-PAY-008)
    owed_paye = -balances.get(PAYE_NIC, 0.0)
    has_due = total(records, "total_hmrc_due") >= NIL
    ok, due = agrees(owed_paye, ("total_hmrc_due",)) if has_due else agrees(
        owed_paye, ("tax_deducted", "employee_nic", "employer_nic", "student_loan"), ("statutory_pay_recovered",))
    if not ok:
        # Owed to HMRC is the payroll's due less the employment allowance set off in those months
        # (NIM06575): books that took the allowance off are right, not a question
        from backend.app.models.payroll_allowance import PayrollAllowance
        ea = defaultdict(float)
        for a in db.query(PayrollAllowance).filter(PayrollAllowance.engagement_id == eng.id).all():
            if a.period_end is not None:
                ea[(a.period_end.year, a.period_end.month)] += abs(_f(a.amount))
        if ea:
            running, dues = 0.0, []
            for k in months_in_year[::-1][:3]:
                month = by_month[k]
                base = total(month, "total_hmrc_due") if has_due else (
                    total(month, "tax_deducted", "employee_nic", "employer_nic", "student_loan")
                    - total(month, "statutory_pay_recovered"))
                running += base - ea.get(k, 0.0)
                dues.append(round(running, 2))
            ok = any(abs(owed_paye - d) <= PAYROLL_DIFFERENCE for d in dues)
    if not ytd_only and PAYE_NIC in used and not ok:
        out.append(_query("PY-05", CLIENT, f"PAYE and NI owed at the year end: {_money(owed_paye)}, the payroll "
                                           f"says {_money(due)}",
                          f"The accounts show {_money(owed_paye)} owed to HMRC for PAYE and NI at {ye:%d %B %Y}; the "
                          f"last month's payroll shows {_money(due)} due. Please send your HMRC PAYE account "
                          f"statement showing the amount owed at {ye:%d %B %Y}.", owed_paye - due, rule="PY-05"))

    # PY-06: pension owed at the year end v the last month's employee and employer contributions
    owed_pension = -balances.get(PENSION_OWED, 0.0)
    ok, contributions = agrees(owed_pension, ("pension_employee", "pension_employer"))
    if not ytd_only and PENSION_OWED in used and not ok:
        out.append(_query("PY-06", CLIENT, f"Pension owed at the year end: {_money(owed_pension)}, the payroll says "
                                           f"{_money(contributions)}",
                          f"The accounts show {_money(owed_pension)} owed to the pension provider at {ye:%d %B %Y}; "
                          f"the last month's payroll shows contributions of {_money(contributions)}. Please send the "
                          f"pension provider's statement showing the contributions due at {ye:%d %B %Y}.",
                          owed_pension - contributions, rule="PY-06"))

    # PY-07: a year-to-date total only, or a regular payroll (three months or more) with months missing in between
    # or after its last month (one or two pay months is a director paid once or twice, not missing months)
    dated = sorted(k for k in (_month(r) for r in records) if k is not None)
    if not months_in_year and dated and not any(any(w in (r.tax_month_label or "").lower() for w in YTD_LABEL)
                                                for r in records):
        # A monthly report for another year (calendar 2024 against an April 2025 - March 2026 year): this year's
        # report is missing, not a year's total
        year = _period_months(eng, ye)
        out.append(_query("PY-07", CLIENT, "Payroll report for another year",
                          f"The payroll report we have is for {_label([dated[0]])} to {_label([dated[-1]])}, not this "
                          f"year ({_label([year[0]])} to {_label([year[-1]])}). Please send this year's payroll "
                          f"reports, or tell us no one was paid this year.", round_=1, rule="PY-07"))
    elif ytd_only:
        out.append(_query("PY-07", CLIENT, "Payroll for the year as a total only",
                          "The payroll report gives a total for the year, not each month. Please send the monthly "
                          "payroll reports (gross pay, tax, NI, pension and net pay for each month).", round_=1,
                          rule="PY-07"))
    else:
        # Every month of the period, also those before the first payroll month (reports from February, the company
        # formed in December): the client says if no one was paid then
        missing = [k for k in _period_months(eng, ye) if k not in by_month]
        # A quarterly payroll (Jun, Sep, Dec, Mar) has no months missing in between
        steps = {(b[0] - a[0]) * 12 + b[1] - a[1] for a, b in zip(months_in_year, months_in_year[1:])}
        if steps == {3}:
            missing = [k for k in missing if k > months_in_year[-1] and (k[0] - months_in_year[-1][0]) * 12
                       + k[1] - months_in_year[-1][1] >= 3]
        if missing and len(months_in_year) >= 3:
            out.append(_query("PY-07", CLIENT, f"Payroll months missing: {len(missing)}",
                              f"The payroll reports cover {_label(sorted(months_in_year))}. Please send the reports "
                              f"for {_label(missing)}, or tell us no one was paid in those months.", round_=1,
                              rule="PY-07"))

    # PY-09: employer NI nil although someone's pay is above the secondary threshold (the Employment Allowance?)
    threshold = next(t for until, t in THRESHOLDS if ye <= until)
    pay: Dict[str, float] = defaultdict(float)
    for r in records:
        pay[r.employee_name or "All employees"] += _f(r.gross_pay)
    named = {n: v for n, v in pay.items() if n != "All employees"}
    above = max(named.values()) if named else gross
    if total(records, "employer_nic") < NIL and above > threshold:
        out.append(_query("PY-09", ACCOUNTANT, "Employer NI is nil",
                          f"Employer NI is nil although gross pay is {_money(gross)} "
                          f"({'one person' if named else 'the payroll'} above the £{threshold:,.0f} threshold). Please "
                          "confirm the Employment Allowance was claimed and the company is eligible (not a company "
                          "whose only paid employee is a director).", gross, rule="PY-09"))

    out += auto_enrolment_query(eng, records)
    return out


def auto_enrolment_query(eng: ClientEngagement, records) -> List[Dict[str, Any]]:
    """PY-10: someone (not a director) paid above the auto-enrolment trigger in a month, with no pension from either
    side all year: enrolled, opted out, or outside the age band (22 to State Pension age)? A director with no contract
    of employment is not a worker for auto-enrolment, so directors are left out."""
    from backend.app.services.queries.query_list import CLIENT
    from backend.app.services.queries.r1_rules import _directors
    from backend.app.services.review.payroll_journals.common import _names_person
    out: List[Dict[str, Any]] = []
    directors = _directors(eng.profile)
    month_pay: Dict[str, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))
    pension: Dict[str, float] = defaultdict(float)
    for r in records:
        name = (r.employee_name or "").strip()
        if not name or name == "All employees" or any(_names_person(name, d) for d in directors):
            continue
        month_pay[name][_month(r)] += _f(r.gross_pay)
        pension[name] += _f(r.pension_employer) + _f(r.pension_employee)
    none = sorted((n, sum(m.values())) for n, m in month_pay.items()
                  if max(m.values()) >= AE_TRIGGER_MONTH and pension[n] < NIL)
    if none:
        listing = "; ".join(f"{n} ({_money(v)})" for n, v in none[:8]) + (f" and {len(none) - 8} more" if len(none) > 8 else "")
        out.append(_query("PY-10", CLIENT, f"Staff with no workplace pension: {len(none)}",
                          f"The payroll shows no pension for {listing}, paid above the auto-enrolment trigger "
                          f"(£10,000 a year, £833 a month). An employer must enrol staff aged 22 to State Pension age who "
                          f"earn above it into a workplace pension, paying at least 3% (Pensions Act 2008). Please confirm "
                          f"for each: enrolled (and the contributions), opted out, or outside the age band.",
                          round(sum(v for _n, v in none), 2), rule="PY-10"))

    return out


STAFF_WAGES = (3000, 3004, 1500)
DIRECTOR_NI = (3011, 1451)
SPLIT_MIN = 1000.0


def director_split_query(db: Session, eng: ClientEngagement, balances: Dict[int, float]) -> List[Dict[str, Any]]:
    """PY-11: the directors' pay (salary, employer's NI, pension) cannot be split from the staff wages: the company has
    directors and pays staff, the books show no directors' NI or pension, and no payroll data says which pay is the
    directors' (no director line, column or block in the payroll file, and no employee in it named as a director), and
    either no payroll report was sent or the directors' salaries are nil (all the pay in staff wages). The accounts show directors' pay on its own (firm chart 3010-3014;
    CA 2006 s412) and it is split only by the payroll report, never by guess."""
    from backend.app.models.director_pay import PayrollDirectorPay
    from backend.app.services.queries.query_list import CLIENT
    from backend.app.services.queries.r1_rules import _directors
    from backend.app.services.review.payroll_journals.common import (
        DIRECTOR_PENSION_CODES, DIRECTOR_SALARY_CODES, _names_person)
    directors = [d for d in _directors(eng.profile) if d]
    staff = round(sum(balances.get(c, 0.0) for c in STAFF_WAGES), 2)
    if not directors or staff < SPLIT_MIN:
        return []
    if any(abs(balances.get(c, 0.0)) >= NIL for c in DIRECTOR_NI + tuple(DIRECTOR_PENSION_CODES)):
        return []                        # the books already split the directors' costs
    split = db.query(PayrollDirectorPay).filter(PayrollDirectorPay.engagement_id == eng.id).first()
    if split is not None and _f(split.gross_pay) >= NIL:
        return []
    named = db.query(PayrollP32Record.employee_name).filter(PayrollP32Record.engagement_id == eng.id).distinct()
    if any(n and any(_names_person(n, d) for d in directors) for (n,) in named):
        return []                        # a per-employee report naming them: the review splits it
    salaries = round(sum(balances.get(c, 0.0) for c in DIRECTOR_SALARY_CODES), 2)
    has_report = db.query(PayrollP32Record.id).filter(PayrollP32Record.engagement_id == eng.id).first() is not None
    if has_report and salaries >= NIL:
        return []                        # a report, and the directors' salaries already on their own: the firm keeps
                                         # their NI with the staff's then
    return [_query("PY-11", CLIENT, "Directors' pay, NI and pension: payroll report per employee needed",
                   f"The books show staff wages of {_money(staff)}"
                   + (f" and directors' salaries of {_money(salaries)}" if salaries >= NIL else "")
                   + ", with no directors' employer's NI or pension. The accounts show the directors' pay on its own, "
                     "and "
                   + ("the payroll report we have does not say which pay is the directors'" if has_report else
                      "no payroll report has been sent")
                   + f". Please send the payroll report per employee for the year (each person's gross pay, employer's "
                     f"NI and pension for the year), and confirm which of them are directors "
                     f"({', '.join(directors[:4])}).", staff, rule="PY-11")]
