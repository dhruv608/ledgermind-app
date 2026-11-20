"""
Prepayments (description-based): a P&L expense whose description shows a period running past the year end (a date
range, or annual wording such as 'annual', '12 months', 'subscription', 'licence', 'insurance', 'renewal', taken as
12 months from the transaction date) has a future portion to prepay: months after the year end / months of the
period x amount.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientProfile, MasterCOA, TBRecord
from backend.app.services.sop.common import (GLLine, MIN_LINE_AMOUNT, NOT_PREPAYABLE_SECTIONS, PAYROLL_CODES, gl_lines,
                                             supplier_name)

PREPAY_MIN_AMOUNT = 100.0       # review material items only
PREPAY_MIN_PORTION = 100.0      # a prepaid portion under this is not raised (small ones are left in the cost)
MONTHLY_PATTERN_MONTHS = 6      # annual wording in 6+ months of the year = a monthly payment, not annual
ANNUAL_WORDS = re.compile(r"\b(annual|annually|yearly|12 months|twelve months|1 year|one year|subscriptions?|"
                          r"licen[cs]es?|insurance|renewals?)\b", re.IGNORECASE)
MONTHLY_WORDS = re.compile(r"\bmonthly\b|\bper month\b|\bp/?m\b", re.IGNORECASE)
MONTH_NAMES = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
# '01 Apr 2025', and '17-Oct-25' / '17/Oct/2025' as invoices write it ('17-Oct-25 to 16-Jan-26')
DAY_MONTH_YEAR = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+|[-/.])" + _MON + r"(?:\s+|[-/.,]\s*)(\d{4}|\d{2})\b",
                            re.IGNORECASE)
NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b")
MONTH_YEAR = re.compile(r"\b" + _MON + r"\s*'?(\d{4}|\d{2})\b", re.IGNORECASE)

# Business rates bills cover the rates year, 1 April to 31 March
BUSINESS_RATES = re.compile(r"\bbusiness rates?\b|\bnndr\b|\bnon[- ]domestic rates?\b", re.IGNORECASE)
# Accounts where a single payment in the year is most likely a yearly plan (software, subscriptions, insurance)
YEARLY_PLAN_MULTIPLE = 5           # one payment at least 5x the supplier's usual one = a yearly plan
ANNUAL_PLAN_ACCOUNTS = re.compile(r"subscription|software|licen[cs]|insurance|hosting|domain|internet", re.IGNORECASE)

FLAG_PREPAYMENT = "Expense relates to a period beyond the year-end. Prepayment required for the future portion."
PREPAY_QUESTION = ("This expense appears to cover a period beyond the year-end. Please confirm whether the future "
                   "portion should be treated as a prepayment.")


@dataclass
class PrepaymentFlag:
    when: date
    code: int
    account: str
    description: str
    amount: float
    start: date
    end: date
    total_months: int
    months_after: int
    prepaid: float                  # straight-line estimate, for review only
    basis: str                      # how the period was found
    guessed: bool = False           # no period in the wording: a single payment taken as a yearly plan


def _year(text: str) -> int:
    y = int(text)
    return y + 2000 if y < 100 else y


def _dates_in(description: str) -> List[Tuple[int, date, bool]]:
    """Dates written in a description, in order: (position, date, month_only). '01 Apr 2025', '1/4/25', 'Apr 2025'."""
    found, taken = [], []
    for m in DAY_MONTH_YEAR.finditer(description):
        try:
            found.append((m.start(), date(_year(m.group(3)), MONTH_NAMES[m.group(2).lower()[:3]], int(m.group(1))), False))
            taken.append(m.span())
        except ValueError:
            pass
    for m in NUMERIC_DATE.finditer(description):
        if any(a <= m.start() < b for a, b in taken):
            continue
        try:
            found.append((m.start(), date(_year(m.group(3)), int(m.group(2)), int(m.group(1))), False))
            taken.append(m.span())
        except ValueError:
            pass
    for m in MONTH_YEAR.finditer(description):
        if any(a <= m.start() < b for a, b in taken):
            continue
        found.append((m.start(), date(_year(m.group(2)), MONTH_NAMES[m.group(1).lower()[:3]], 1), True))
    return sorted(found)


def service_period(description: str, when: date) -> Optional[Tuple[date, date, str]]:
    """The period an expense covers: a date range written in the description, or 12 months from the transaction
    date when the description uses annual wording."""
    if BUSINESS_RATES.search(description):
        year = when.year if when.month >= 2 else when.year - 1   # a February/March bill is for the coming rates year
        return date(year, 4, 1), date(year + 1, 3, 31), "business rates: the rates year 1 April to 31 March"
    dates = _dates_in(description)
    for (_, first, _), (_, second, second_month_only) in zip(dates, dates[1:]):
        end = date(second.year, second.month, calendar.monthrange(second.year, second.month)[1]) if second_month_only else second
        if 27 <= (end - first).days <= 3 * 366:
            return first, end, "date range in the description"
    if ANNUAL_WORDS.search(description) and not MONTHLY_WORDS.search(description):
        end = date(when.year + 1, when.month, min(when.day, calendar.monthrange(when.year + 1, when.month)[1])) - timedelta(days=1)
        return when, end, f"'{ANNUAL_WORDS.search(description).group(0)}': 12 months from the transaction date assumed"
    # One month named and nothing else ('Rent - Nov 2025' invoiced in October): the bill is for that month
    # (next month's rent invoiced before the year end is a prepayment)
    if len(dates) == 1 and dates[0][2]:
        first = dates[0][1]
        return first, date(first.year, first.month, calendar.monthrange(first.year, first.month)[1]), "the month named in the description"
    return None


STATED_PERIODS = ("date range in the description", "business rates:", "the month named in the description")


def period_is_stated(basis: str) -> bool:
    """The bill's own wording gives its period (a date range, the rates year, the month it names): sure. A period
    assumed from 'annual' wording or a payment pattern is not (12 months from the payment date is a guess)."""
    return basis.startswith(STATED_PERIODS)


def find_prepayments(period_end: date, lines: Iterable[GLLine], chart: Dict[int, MasterCOA],
                     min_amount: float = PREPAY_MIN_AMOUNT) -> List[PrepaymentFlag]:
    expense = [l for l in lines if l.when <= period_end and l.code in chart
               and chart[l.code].financial_class == "Profit and Loss"
               and chart[l.code].category not in NOT_PREPAYABLE_SECTIONS and l.code not in PAYROLL_CODES
               and "journal" not in l.source.lower()]   # journals are ignored (openings, reversals, releases)
    # Each supplier's payments from each account this year: a yearly plan is paid once, or stands out as one large
    # payment among small monthly ones (a switch from a monthly to a yearly plan)
    payments: Dict[Tuple[str, str], List[float]] = {}
    for l in expense:
        if l.debit >= MIN_LINE_AMOUNT:
            payments.setdefault((l.account, supplier_name(l.description)), []).append(l.debit)

    def yearly_plan_reason(l: GLLine) -> Optional[str]:
        if not ANNUAL_PLAN_ACCOUNTS.search(l.account):
            return None
        supplier = supplier_name(l.description)
        paid = payments.get((l.account, supplier), [])
        if len(paid) == 1:
            return f"only payment this year to '{supplier}' from '{l.account}'"
        others = sorted(paid)
        others.remove(l.debit)
        usual = others[len(others) // 2]
        if l.debit >= YEARLY_PLAN_MULTIPLE * usual:
            return f"payment to '{supplier}' is {l.debit / usual:.0f}x its usual £{usual:,.2f}"
        return None
    # The other lines of the same transaction: QuickBooks writes a bill's period on one line only (the period on the
    # creditors line, only the landlord's name on its Rent line)
    lines = list(lines)
    siblings: Dict[Tuple[date, str], List[str]] = {}
    for l in lines:
        if getattr(l, "reference", "") and l.description:
            siblings.setdefault((l.when, l.reference), []).append(l.description)
    lines = [l for l in expense if l.debit >= min_amount]
    # Annual wording that recurs in most months of the year is a monthly charge (e.g. monthly insurance)
    worded_months: Dict[str, set] = {}
    for l in lines:
        if ANNUAL_WORDS.search(l.description) and not _dates_in(l.description):
            worded_months.setdefault(l.account, set()).add((l.when.year, l.when.month))
    monthly_accounts = {a for a, ms in worded_months.items() if len(ms) >= MONTHLY_PATTERN_MONTHS}

    # Business rates paid in monthly instalments (three or more in one rates year): each is a part of the year's bill,
    # not a bill for the whole rates year. Prepaid = paid for the rates year less its cost to the year end, the bill
    # taken as the usual ten instalments; an estimate, so a question (FRS 102 s2)
    rates_years: Dict[int, list] = {}
    for l in lines:
        if BUSINESS_RATES.search(l.description):
            rates_years.setdefault(l.when.year if l.when.month >= 4 else l.when.year - 1, []).append(l)
    instalments = {id(l) for ls in rates_years.values() if len({(x.when.year, x.when.month) for x in ls}) >= 3 for l in ls}
    flags = []
    for year, ls in rates_years.items():
        if not any(id(l) in instalments for l in ls):
            continue
        start, end = date(year, 4, 1), date(year + 1, 3, 31)
        if end <= period_end:
            continue
        paid = sum(l.debit for l in ls)
        bill = max(paid, paid / len(ls) * RATES_INSTALMENTS)
        days = (end - start).days + 1
        used = max(0, (min(period_end, end) - start).days + 1)
        prepaid = round(paid - bill * used / days, 2)
        if prepaid < 1:
            continue
        last = max(ls, key=lambda x: x.when)
        flags.append(PrepaymentFlag(
            when=last.when, code=last.code, account=last.account,
            description=f"Business rates: {len(ls)} instalments paid for {year}/{str(year + 1)[2:]}",
            amount=round(paid, 2), start=start, end=end, total_months=12,
            months_after=max(1, round((end - period_end).days / 30.44)), prepaid=prepaid,
            basis=f"instalments: paid £{paid:,.2f} less {used} of {days} days of a bill of about £{bill:,.2f}",
            guessed=True))
    for l in lines:
        if id(l) in instalments:
            continue
        period = service_period(l.description, l.when)
        if period is None and getattr(l, "reference", ""):
            for other in siblings.get((l.when, l.reference), []):
                found = service_period(other, l.when) if other != l.description else None
                if found:
                    period = (found[0], found[1], f"{found[2]} (on another line of the same transaction, no. {l.reference})")
                    break
        reason = yearly_plan_reason(l) if period is None else None
        if reason:
            end = date(l.when.year + 1, l.when.month, min(l.when.day, calendar.monthrange(l.when.year + 1, l.when.month)[1])) - timedelta(days=1)
            period = (l.when, end, f"{reason}: a yearly plan assumed (12 months from the transaction date)")
        if period is None:
            continue
        start, end, basis = period
        if basis.startswith("'") and l.account in monthly_accounts:
            continue
        if end <= period_end:
            continue
        total_days = (end - start).days + 1
        after_days = (end - max(start, period_end + timedelta(days=1))).days + 1
        total_months = max(1, round(total_days / 30.44))
        months_after = min(total_months, round(after_days / 30.44))
        if months_after < 1:
            continue
        flags.append(PrepaymentFlag(
            when=l.when, code=l.code, account=l.account, description=l.description, amount=round(l.debit, 2),
            start=start, end=end, total_months=total_months, months_after=months_after,
            prepaid=round(l.debit * min(after_days, total_days) / total_days, 2), basis=basis,   # by days, as on E3
            guessed=bool(reason),
        ))
    flags += _regular_in_advance(period_end, lines, {(f.when, f.amount, f.description) for f in flags})
    flags.sort(key=lambda f: -f.prepaid)
    return flags


RATES_INSTALMENTS = 10         # councils bill business rates in ten monthly instalments by default
REGULAR_MIN_GAP = 80            # quarterly or longer (monthly ones are left in the cost)
REGULAR_SAME_AMOUNT = 0.15      # the same charge each time, within 15%
REGULAR_GAP_TOLERANCE = 0.25    # each of the last gaps within 25% of the usual one


def _regular_in_advance(period_end: date, lines: List[GLLine], seen: set) -> List[PrepaymentFlag]:
    """A charge paid on a steady quarterly (or longer) cycle, the same amount each time, covers the time until the next
    payment: the part of the last one after the year end may be prepaid (rent paid a quarter in advance). A guess, so a
    question, never a journal.
    Payments to one supplier a few days apart are one payment."""
    groups: Dict[Tuple[str, str], List[GLLine]] = {}
    for l in sorted(lines, key=lambda l: l.when):
        groups.setdefault((l.account, supplier_name(l.description)), []).append(l)
    out = []
    for (account, supplier), ls in groups.items():
        merged: List[List] = []
        for l in ls:
            if merged and (l.when - merged[-1][0]).days <= 7:
                merged[-1][1] += l.debit
            else:
                merged.append([l.when, l.debit, l])
        last = merged[-1]
        same = [m for m in merged if abs(m[1] - last[1]) <= REGULAR_SAME_AMOUNT * last[1]]
        if not supplier or len(same) < 3:
            continue
        gaps = [(b[0] - a[0]).days for a, b in zip(same, same[1:])]
        usual = sorted(gaps)[len(gaps) // 2]
        if usual < REGULAR_MIN_GAP or any(abs(g - usual) > REGULAR_GAP_TOLERANCE * usual for g in gaps[-3:]):
            continue
        start, end = last[0], last[0] + timedelta(days=usual - 1)
        if end <= period_end or (last[2].when, round(last[2].debit, 2), last[2].description) in seen:
            continue
        after = (end - period_end).days
        out.append(PrepaymentFlag(
            when=start, code=last[2].code, account=account, description=last[2].description, amount=round(last[1], 2),
            start=start, end=end, total_months=max(1, round(usual / 30.44)), months_after=max(1, round(after / 30.44)),
            prepaid=round(last[1] * after / usual, 2),
            basis=f"paid every {usual} days, the same amount each time: the last payment covers to {end:%d/%m/%Y}",
            guessed=True,
        ))
    return out


def prepayment_review(engagement_id: str, period_end: date, tb_records: Iterable[TBRecord], db: Session) -> List[PrepaymentFlag]:
    tb_records = list(tb_records)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    # The client's prepayment threshold from the setup replaces the firm's
    from backend.app.services.review.setup_checks import policy_threshold
    profile = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement_id).first()
    limit = policy_threshold(profile, "prepayment_threshold")
    return find_prepayments(period_end, gl_lines(engagement_id, tb_records, db), chart,
                            PREPAY_MIN_AMOUNT if limit is None else limit)
