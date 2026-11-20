"""Shared parts of the payroll journals: journal and entry helpers, the client's ledger lines by firm code."""

from backend.app.models.database import (
    AuditFinding, ClientEngagement, ClientProfile, PayrollP32Record, ProposedJournal, TBRecord)
from backend.app.services.mapping.chart_lookup import ChartLookup
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from datetime import date
import json
import re


EMPLOYER_NI_CODES = (3001, 3011, 1501, 1451)
# Staff code -> the directors' code beside it (employee costs and cost of sales)
SALARY_TO_DIRECTORS = {3000: 3010, 1500: 1450}
PENSION_TO_DIRECTORS = {3002: 3012, 1502: 1452}       # defined contribution pensions
DIRECTOR_PENSION_CODES = (3012, 3013, 1452, 1453)
EA_BEFORE_APRIL_2025 = 5000.0
# 'Employment allowance', 'Employer's allowance', or just 'EA' / 'Being EA' (as QuickBooks payroll journals say it)
EA_WORDS = re.compile(r"(?i:employ(?:ment|er'?s?)\s+allowance)|\bEA\b")
MIN_AMOUNT = 1.0


def _journal(engagement: ClientEngagement, counter: List[int], description: str, dr: int, cr: int, amount: float,
             chart: ChartLookup, point: AuditFinding) -> ProposedJournal:
    j = ProposedJournal(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{counter[0]:02d}",
                        description=description[:255], debit_code=dr, debit_name=chart.name(dr), credit_code=cr,
                        credit_name=chart.name(cr), amount=round(amount, 2), status="PROPOSED")
    counter[0] += 1
    j._point = point
    return j


def _entry(dr: int, cr: int, amount: float, chart: ChartLookup) -> str:
    return f"Dr {dr} {chart.name(dr)} (£{amount:,.2f}) / Cr {cr} {chart.name(cr)} (£{amount:,.2f})"


def _gl_codes(tb_records: List[TBRecord], chart: ChartLookup) -> Dict[str, int]:
    return chart.gl_account_codes(tb_records)


def _lines(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session):
    """(code, line) for every ledger line of the year whose account maps to a firm code."""
    from backend.app.services.sop.common import code_matcher, ledger_rows
    # Either side may carry the '710 - ' prefix or a 'Parent:' path (the review's one read of the ledger)
    code_of = code_matcher(_gl_codes(tb_records, chart))
    for g in ledger_rows(str(engagement.id), db):
        code = code_of(g.raw_account_name)
        if code is not None:
            yield code, g


# ---------------------------------------------------------------------------------------------------------------
# U-PAY-003 Employment allowance
# ---------------------------------------------------------------------------------------------------------------
def _allowance_for(start: date, end: date) -> Tuple[float, str]:
    """The allowance of the tax year (6 Apr - 5 Apr) holding most of the accounting period."""
    from backend.app.services.tax.ct_computation import tax_parameters
    best, best_days = None, -1
    year = start.year - 1
    while date(year, 4, 6) <= end:
        ty_start, ty_end = date(year, 4, 6), date(year + 1, 4, 5)
        days = (min(end, ty_end) - max(start, ty_start)).days + 1
        if days > best_days:
            best, best_days = ty_start, days
        year += 1
    label = f"{best.year}/{str(best.year + 1)[2:]}"
    if best >= date(2025, 4, 6):
        return float(tax_parameters().get("P-EA", 10500.0)), label
    return EA_BEFORE_APRIL_2025, label


def _only_director(engagement: ClientEngagement, profile: Optional[ClientProfile], db: Session) -> bool:
    """The only person the payroll pays above the secondary threshold is a director: no employment allowance
    claim. The directors are those on Companies House / the setup, those the payroll file
    names as directors, or, when it gives only their total, the people whose pay makes it up."""
    from itertools import combinations
    from backend.app.models.director_pay import PayrollDirectorPay
    from backend.app.services.setup.engagement_setup import period_of
    gross: Dict[str, float] = {}
    monthly: Dict[str, Dict[str, float]] = {}
    for p in _report(engagement, db):
        gross[p.employee_name or ""] = gross.get(p.employee_name or "", 0.0) + float(p.gross_pay or 0)
        by_month = monthly.setdefault(p.employee_name or "", {})
        by_month[p.tax_month_label or ""] = by_month.get(p.tax_month_label or "", 0.0) + float(p.gross_pay or 0)
    dp = db.query(PayrollDirectorPay).filter(PayrollDirectorPay.engagement_id == engagement.id).first()
    if not gross and dp is None:
        return _only_director_by_books(engagement, db)
    people = {n: g for n, g in gross.items() if n and n != "All employees"}
    if not people:
        # A summary of monthly totals: all the pay is one director's
        total = sum(gross.values())
        return (dp is not None and total >= MIN_AMOUNT and abs(float(dp.gross_pay) - total) < MIN_AMOUNT
                and len(json.loads(dp.people or "{}")) <= 1)
    directors = [d for d in (json.loads(profile.directors or "[]") if profile else []) if d]
    directors += list(json.loads(dp.people or "{}")) if dp is not None else []
    is_director = {n: bool(re.search(r"\bdirector\b", n, re.I)) or any(_names_person(n, d) or _words(n) == _words(d)
                                                                       for d in directors) for n in people}
    if dp is not None and not any(is_director.values()):
        # The file gives the directors' total only: the people whose pay adds up to it
        names = sorted(people)
        for size in range(1, min(len(names), 6) + 1):
            match = next((c for c in combinations(names, size)
                          if abs(sum(people[n] for n in c) - float(dp.gross_pay)) < MIN_AMOUNT), None)
            if match:
                is_director.update({n: True for n in match})
                break
    if not any(is_director.values()):
        # The payroll names no director (no directors on the setup or Companies House): the books' own split of pay
        return _only_director_by_books(engagement, db)
    period = period_of(engagement)
    _amount, tax_year = _allowance_for(date.fromisoformat(period["start"]), date.fromisoformat(period["end"]))
    threshold = 5000.0 if tax_year >= "2025/26" else 9100.0
    # HMRC: not available when the only employee the company pays employer NI on is a director (two directors paid
    # above it, or a director and a member of staff, can claim; NIM06545). A director's threshold is for the year (an
    # annual earnings period); a member of staff's is per pay period, so a month above a twelfth of it counts
    above = [n for n, g in people.items()
             if (g > threshold if is_director[n] else
                 g > threshold or any(m > threshold / 12 for m in (monthly.get(n) or {}).values()))]
    return len(above) == 1 and is_director[above[0]]


def _only_director_by_books(engagement: ClientEngagement, db: Session) -> bool:
    """No payroll report: the year's pay in the books by the chart's own split. Staff pay below the secondary
    threshold, and directors' pay too little for two directors to both be above it, leave at most one person above
    the threshold, a director: no employment allowance (the £478.86 a year of employer NI on a £12,570 director's
    salary in 2024/25 stays owed to HMRC)."""
    from backend.app.services.setup.engagement_setup import period_of
    from backend.app.services.tax.ct_computation import final_balances
    tb = db.query(TBRecord).filter(TBRecord.engagement_id == engagement.id).all()
    chart = ChartLookup(db)
    after = final_balances(engagement.id, tb, db)
    pay = {c: v for c, v in after.items() if chart.is_gross_wages(c) or DIRECTOR_PAY_NAME.search(chart.name(c, ""))}
    directors = sum(v for c, v in pay.items() if DIRECTOR_PAY_NAME.search(chart.name(c, "")))
    staff = sum(v for c, v in pay.items() if not DIRECTOR_PAY_NAME.search(chart.name(c, "")))
    # The secondary threshold of the tax year most of the accounting year falls in (as the allowance itself)
    period = period_of(engagement)
    _amount, tax_year = _allowance_for(date.fromisoformat(period["start"]), date.fromisoformat(period["end"]))
    threshold = 5000.0 if tax_year >= "2025/26" else 9100.0
    return threshold < directors <= 2 * threshold and staff <= threshold


# ---------------------------------------------------------------------------------------------------------------
# U-PAY-004 Directors' pay in the staff accounts
# ---------------------------------------------------------------------------------------------------------------
def _words(text: str) -> List[str]:
    return re.sub(r"[^a-z]+", " ", (text or "").lower()).split()


def _names_person(text: str, director: str) -> bool:
    """The text names the director: the surname (all its parts, in order) with a first name or initial before it
    that fits ('Sam Smith' for Samuel John Smith, 'N Smith-Jones')."""
    d = _words(director)
    if len(d) < 2:
        return False
    first, surname = d[0], [w for w in re.sub(r"[^a-z\-]+", " ", director.lower()).split()[-1].split("-") if w]
    t = _words(text)
    n = len(surname)
    for i in range(1, len(t) - n + 1):
        if t[i:i + n] == surname:
            before = t[i - 1]
            # the full first name, its initial, or a short form of it ('Josh' for Joshua, 'Chris' for Christopher)
            if before == first or (first.startswith(before) and (len(before) == 1 or len(before) >= 3)):
                return True
    return False


# U-PAY-007 Directors' pay per the payroll file
# ---------------------------------------------------------------------------------------------------------------
DIRECTOR_SALARY_CODES = (3010, 3014, 3015, 1450)
DIRECTOR_PAY_NAME = re.compile(r"director'?s?'?\s*(?:salar|remun|wage|pay|fee)", re.IGNORECASE)


def _journal_lines(engagement: ClientEngagement, counter: List[int], description: str,
                   lines: List[Tuple[int, float, float]], chart: ChartLookup, point: AuditFinding) -> ProposedJournal:
    """A journal of several lines [(code, debit, credit)], as the accountant writes a payroll journal."""
    from backend.app.models.database import JournalLine
    lines = [(c, round(dr, 2), round(cr, 2)) for c, dr, cr in lines if round(dr, 2) or round(cr, 2)]
    first_dr = next(c for c, dr, _ in lines if dr)
    first_cr = next(c for c, _, cr in lines if cr)
    j = ProposedJournal(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{counter[0]:02d}",
                        description=description[:255], debit_code=first_dr, debit_name=chart.name(first_dr),
                        credit_code=first_cr, credit_name=chart.name(first_cr),
                        amount=round(sum(dr for _, dr, _ in lines), 2), status="PROPOSED",
                        lines=[JournalLine(line_no=i, account_code=c, account_name=chart.name(c), debit=dr, credit=cr)
                               for i, (c, dr, cr) in enumerate(lines, start=1)])
    counter[0] += 1
    j._point = point
    return j


def _last_year_pay(engagement: ClientEngagement, db: Session) -> Tuple[float, float]:
    """(directors' pay, staff wages) on last year's TB, or (0, 0) when there is none."""
    from backend.app.services.review.last_year import _from_files
    try:
        _, lines = _from_files(engagement, db)
    except Exception:
        return 0.0, 0.0
    directors = sum(l.amount for l in lines if (l.code in DIRECTOR_SALARY_CODES if l.code is not None
                                                else bool(DIRECTOR_PAY_NAME.search(l.name or ""))))
    staff = sum(l.amount for l in lines if l.code in SALARY_TO_DIRECTORS)
    return round(directors, 2), round(staff, 2)


def _report(engagement: ClientEngagement, db: Session) -> List[PayrollP32Record]:
    """The payroll report's rows; none when it is for another period (payroll_period.py: the Data check asks)."""
    from backend.app.services.review.payroll_period import usable
    return usable(engagement, db)[0]


def _month(r: PayrollP32Record) -> Optional[Tuple[int, int]]:
    d = r.period_end or r.period_start
    return (d.year, d.month) if d else None


def _net_pay(r: PayrollP32Record) -> float:
    """A pay run's net pay: gross less tax, employee NI, employee pension and student loan (as the journal works it)."""
    return float(r.gross_pay or 0) - sum(float(getattr(r, a) or 0) for a in
                                         ("tax_deducted", "employee_nic", "pension_employee", "student_loan"))


# ---------------------------------------------------------------------------------------------------------------
# U-PAY-006 Net wages cleared from another account
# ---------------------------------------------------------------------------------------------------------------
WAGE_COST_CODES = (3000, 3004, 3010, 3014, 3015, 1500, 1450)   # staff and directors' pay, also in cost of sales
# An account named as employer NI ('Employers NI', 'Employer's NI contributions', 'Er's NIC')
EMPLOYER_NI_NAME = re.compile(r"\bemployer'?s?'?\s*(?:n\.?i\.?c?s?|national\s+insurance)\b|\ber'?s?\s+nics?\b", re.I)


def employer_ni_on_wage_codes(tb_records: List[TBRecord]) -> float:
    """Employer NI the books hold on a pay code: an account named employer NI that the firm codes with the wages
    (3000 / 3010 / 1500, the client's own codes). It is employer NI, not gross pay, when the books are set against the
    payroll report's NI and gross pay (else the NI is posted twice and the gross looks over)."""
    return round(sum(float(t.net_amount or 0) for t in tb_records
                     if t.std_code in WAGE_COST_CODES and EMPLOYER_NI_NAME.search(t.raw_account_name or "")), 2)


def paye_after(tb_records: List[TBRecord], earlier: List[ProposedJournal]) -> float:
    """5320's closing balance (debit +) with the journals already proposed in this review."""
    from backend.app.services.mapping.chart_lookup import PAYE_NIC
    bal = sum(float(t.net_amount or 0.0) for t in tb_records if t.std_code == PAYE_NIC)
    for j in earlier:
        lines = list(getattr(j, "lines", None) or [])
        if lines:                                     # a journal of several lines (the payroll recorded by month)
            bal += sum(float(l.debit or 0) - float(l.credit or 0) for l in lines if int(l.account_code) == PAYE_NIC)
            continue
        amount = float(j.amount or 0.0)
        bal += amount if j.debit_code == PAYE_NIC else -amount if j.credit_code == PAYE_NIC else 0.0
    return round(bal, 2)
