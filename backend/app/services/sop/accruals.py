"""
Missing accruals (consistency-based): an expense account that normally has a cost every month but has none in some
month (above all the final month of the year) is reviewed for an accrual. Pattern-based, not description-based.
Bills dated after the year end that relate back are not checked, as uploaded ledgers stop at the year end.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientProfile, MasterCOA, TBRecord
from backend.app.services.sop.common import GLLine, MIN_LINE_AMOUNT, PAYROLL_CODES, gl_lines, year_months

# Accounts the accruals check looks at: running costs. Cost of sales (stock, purchases), depreciation, tax, the
# payroll accounts (checked month by month on G6.2) and the catch-all 'other operating costs' (where unclear or
# wrongly mapped accounts land) are left out.
ACCRUAL_SECTIONS = {"Distribution costs", "Employee costs", "Premises expenses", "General admin",
                    "Interest payable and similar charges"}
REGULAR_MIN_MONTHS = 8          # a regular expense has a cost in most months (8 to 11)
# Costs that come when they are incurred, not as a monthly bill, so a month without one is not a missing bill:
# staff expenses, travel and subsistence (3070-3090), audit, accountancy, legal and other professional fees
# (accountancy is accrued through the A4 fee accrual), and entertaining. Regular suppliers (rent, utilities, phone,
# software, a management fee) stay in
NOT_MONTHLY_BILLS = set(range(3070, 3091)) | {3300, 3301, 3302, 3303, 3304, 3307, 3308, 3309, 3310, 3385}


FLAG_FINAL_MONTH = "No expense recorded in the final month for a regular cost. Accrual likely required."
FLAG_MISSING_MONTH = "Expense normally occurs monthly but is missing in this month. Review whether an accrual is required."


@dataclass
class AccrualFlag:
    account: str                    # the client's account name
    code: int
    monthly: List[float]            # cost (debits) in each month of the year, first month first
    months: List[date] = field(default_factory=list)   # month ends, same order
    missing: List[date] = field(default_factory=list)
    final_missing: bool = False
    average: float = 0.0            # average cost of the months that have one (for review only)

    @property
    def message(self) -> str:
        return FLAG_FINAL_MONTH if self.final_missing else FLAG_MISSING_MONTH

    @property
    def client_question(self) -> str:
        months = ", ".join(m.strftime("%B %Y") for m in self.missing)
        return (f"This expense usually occurs every month but is missing in {months}. "
                f"Please confirm whether an accrual should be recorded.")


def missing_accruals(period_end: date, lines: Iterable[GLLine],
                     chart: Dict[int, MasterCOA]) -> List[AccrualFlag]:
    """Regular running-cost accounts (a cost in at least 8 of the 12 months) with a month that has
    no cost; the final month missing is the main finding. A month counts when it has a cost line (debit), so a
    reversal of last year's accrual in the first month doesn't hide or create a gap."""
    months = year_months(period_end)
    index = {(m.year, m.month): i for i, m in enumerate(months)}
    per_account: Dict[str, Tuple[int, List[float]]] = {}
    for when, code, account, debit, *_ in lines:
        section = chart[code].category if code in chart else None
        if section not in ACCRUAL_SECTIONS or code in PAYROLL_CODES or code in NOT_MONTHLY_BILLS or debit < MIN_LINE_AMOUNT:
            continue
        i = index.get((when.year, when.month))
        if i is None:
            continue
        per_account.setdefault(account, (code, [0.0] * 12))[1][i] += debit

    flags = []
    for account, (code, monthly) in sorted(per_account.items()):
        present = [i for i, v in enumerate(monthly) if v >= MIN_LINE_AMOUNT]
        if len(present) < REGULAR_MIN_MONTHS or len(present) == 12:
            continue
        missing = [months[i] for i in range(12) if i not in present]
        flags.append(AccrualFlag(
            account=account, code=code, monthly=[round(v, 2) for v in monthly], months=months, missing=missing,
            final_missing=monthly[11] < MIN_LINE_AMOUNT,
            average=round(sum(monthly[i] for i in present) / len(present), 2),
        ))
    flags.sort(key=lambda f: (not f.final_missing, f.account))
    return flags


# Bills that come every quarter for the quarter just gone (in arrears): power, water, phone and broadband: the months
# since the last bill are accrued. Rent, rates and insurance are paid ahead: the
# prepayments check takes those
ARREARS_CODES = {3130, 3131, 3290, 3291}
ARREARS_WORDS = re.compile(r"electric|\bgas\b|energy|light and heat|\bwater\b|telephone|\bphone\b|broadband|telecom|"
                           r"\bbt\b|virgin media|octopus|british gas|edf|e\.on|thames water|severn trent", re.I)
QUARTER_GAP = (70, 110)          # days between bills on a quarterly cycle
QUARTER_BILLS = (3, 5)           # bills in the year on that cycle (three show the cycle)


@dataclass
class QuarterlyFlag:
    account: str
    code: int
    supplier: str
    bills: List[Tuple[date, float]]
    months_since: int               # whole months from the last bill to the year end (1 to 3)
    estimate: float                 # the average bill for those months


def quarterly_in_arrears(period_end: date, lines: Iterable[GLLine], is_cost=None) -> List[QuarterlyFlag]:
    """A supplier billing every quarter in arrears whose last bill is a month or more before the year end: the
    months since are owed at the year end (estimated from the average bill). The cycle: all but one gap between bills
    a quarter (a catch-up or final bill breaks one, e.g. gaps of 87, 87, 91, 56 days). is_cost(code) keeps the cost
    accounts only (the same supplier on the VAT or creditors account is not a bill)."""
    from backend.app.services.sop.common import supplier_name
    start = year_months(period_end)[0].replace(day=1)
    bills: Dict[Tuple[str, str], Tuple[int, List[Tuple[date, float]]]] = {}
    for when, code, account, debit, *rest in lines:
        description = rest[1] if len(rest) > 1 else ""
        if debit < MIN_LINE_AMOUNT or not (start <= when <= period_end):
            continue
        if is_cost is not None and not is_cost(code):
            continue
        if code not in ARREARS_CODES and not ARREARS_WORDS.search(f"{account} {description}"):
            continue
        key = (account, supplier_name(description) or account)
        bills.setdefault(key, (code, []))[1].append((when, debit))
    out: List[QuarterlyFlag] = []
    for (account, supplier), (code, rows) in sorted(bills.items()):
        rows.sort()
        dates = sorted({d for d, _a in rows})
        if not QUARTER_BILLS[0] <= len(dates) <= QUARTER_BILLS[1]:
            continue
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        good = sum(1 for g in gaps if QUARTER_GAP[0] <= g <= QUARTER_GAP[1])
        if good < 2 or good < len(gaps) - 1:
            continue
        since = (period_end - dates[-1]).days
        if since > QUARTER_GAP[1] + 15:
            continue                     # no bill for longer than a quarter: the supply stopped (or moved), not owed
        months = min(3, int(round(since / 30.4)))
        if months < 1:
            continue
        per_bill = sum(a for _d, a in rows) / len(dates)
        out.append(QuarterlyFlag(account, code, supplier, [(d, round(sum(a for x, a in rows if x == d), 2)) for d in dates],
                                 months, round(per_bill * months / 3, 2)))
    return out


@dataclass
class ArrearsFlag:
    account: str
    code: int
    covered_to: date                # the last day the bills' own periods cover
    days: int                       # days from then to the year end, owed
    per_day: float
    estimate: float
    bills: int                      # bills with a stated period


ARREARS_MIN_BILLS = 3
ARREARS_MAX_PERIOD = 100            # days one bill covers: monthly or quarterly bills only
ARREARS_MAX_GAP = 100               # no bill for longer: the supply stopped or moved


def billed_to_before_year_end(period_end: date, lines: Iterable[GLLine], is_cost=None) -> List[ArrearsFlag]:
    """A supplier billing in arrears (power, water, phone) whose bills state the period they cover, the latest
    covering to a day before the year end: the days from then to the year end are used and not yet billed, so owed
    (FRS 102 s2 accruals). A posting-date check misses it, as each month has a bill posted for the month before.
    Estimated at the stated bills' cost per day, for the bill after the year end to replace. Per cost account: two
    suppliers in turn (a switch) continue one another."""
    from backend.app.services.sop.prepayments import service_period
    start = year_months(period_end)[0].replace(day=1)
    groups: Dict[Tuple[str, int], Dict[Tuple[date, date], float]] = {}
    for when, code, account, debit, *rest in lines:
        description = rest[1] if len(rest) > 1 else ""
        source = rest[2] if len(rest) > 2 else ""
        if debit < MIN_LINE_AMOUNT or not (start <= when <= period_end) or "journal" in (source or "").lower():
            continue
        if is_cost is not None and not is_cost(code):
            continue
        if code not in ARREARS_CODES and not ARREARS_WORDS.search(f"{account} {description}"):
            continue
        p = service_period(description or "", when)
        if p is None or not p[2].startswith(("date range", "the month named")):
            continue
        s, e = p[0], p[1]
        if not 0 < (e - s).days + 1 <= ARREARS_MAX_PERIOD or e > period_end:
            continue
        periods = groups.setdefault((account, code), {})
        periods[(s, e)] = periods.get((s, e), 0.0) + debit
    out: List[ArrearsFlag] = []
    for (account, code), periods in sorted(groups.items()):
        if len(periods) < ARREARS_MIN_BILLS:
            continue
        covered_to = max(e for _s, e in periods)
        gap = (period_end - covered_to).days
        if gap < 7 or gap > ARREARS_MAX_GAP:
            continue
        days = sum((e - s).days + 1 for s, e in periods)
        per_day = sum(periods.values()) / days
        out.append(ArrearsFlag(account, code, covered_to, gap, round(per_day, 4), round(per_day * gap, 2), len(periods)))
    return out


def accrual_review(engagement_id: str, period_end: date, tb_records: Iterable[TBRecord], db: Session) -> List[AccrualFlag]:
    tb_records = list(tb_records)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    flags = missing_accruals(period_end, gl_lines(engagement_id, tb_records, db), chart)
    # The client's accrual threshold from the setup: a regular cost averaging less a month is not accrued
    from backend.app.services.review.setup_checks import policy_threshold
    profile = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement_id).first()
    limit = policy_threshold(profile, "accrual_threshold")
    return flags if limit is None else [f for f in flags if f.average >= limit]
