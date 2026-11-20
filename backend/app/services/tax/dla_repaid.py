"""Director's loan repaid after the year end, from next year's ledger (CTA 2010 s458, s464ZA; HMRC
CTM61610, CTM61630).

s455 is not due on the part of an overdrawn loan repaid within nine months of the year end (s458). Next year's ledger
shows it: money credited to the director's loan account (a bank repayment, salary or a dividend credited) dated after
the year end and up to nine months after it. Opening balance and brought forward lines are not repayments.

The 30 day rule (s464ZA(1)): where, within 30 days, £5,000 or more is repaid and £5,000 or more is lent again, the
repayment is matched to the new loan, not the old one, so it gives no relief. Such repayments are left out and named.
Pay or a dividend credited to the loan is taxed on the director, so the rule does not touch it (s464ZA(6)): known by
its own wording or a same-day debit on a pay or dividend account.

Used only when the accountant has not typed the figure; the computation says where it came from."""

import re
from datetime import date, timedelta
from typing import NamedTuple, Optional, Sequence

from backend.app.services.tax.ct_constants import DLA_CODES

BNB_LIMIT = 5000.0
BNB_DAYS = 30
NOT_A_REPAYMENT = re.compile(r"opening balance|brought forward|\bb/?fwd\b|\bb/f\b|balance b/d", re.I)
# Pay or a dividend credited to the loan: taxed on the director, so the 30 day rule does not apply (s464ZA(6), CTM61642)
TAXED = re.compile(r"dividend|remuneration|salary|salaries|wages|bonus|net pay", re.I)


class Repaid(NamedTuple):
    repaid: float          # counts for s458
    left_out: float        # matched to new lending within 30 days (s464ZA)
    lines: int
    last_seen: Optional[date]
    note: str


def nine_months_after(end: date) -> date:
    m = end.month + 9
    y, m = end.year + (m - 1) // 12, (m - 1) % 12 + 1
    for day in (end.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return end + timedelta(days=274)


def repaid_after(end: date, lines: Sequence, codes=DLA_CODES) -> Repaid:
    limit = nine_months_after(end)
    mine = [l for l in lines if l.code in codes and end < l.when <= limit
            and not NOT_A_REPAYMENT.search(f"{l.description} {l.reference}")]
    pays = sorted([l for l in mine if l.credit >= 0.01], key=lambda l: l.when)
    lends = sorted([l for l in mine if l.debit >= 0.01], key=lambda l: l.when)
    if not pays:
        return Repaid(0.0, 0.0, 0, None, "")
    # s464ZA: repayments in any 30 days of £5,000+ with new lending of £5,000+ in the 30 days that follow
    def taxed(p) -> bool:
        return bool(TAXED.search(f"{p.description} {p.reference}")) or any(
            l.when == p.when and l.debit >= 0.01 and l.code not in codes and TAXED.search(l.account or "") for l in lines)

    left_out, used = 0.0, set()
    for p in pays:
        if taxed(p):
            continue
        window = [l for l in pays if p.when <= l.when <= p.when + timedelta(days=BNB_DAYS) and not taxed(l)]
        again = [(k, l) for k, l in enumerate(lends) if k not in used and p.when <= l.when <= p.when + timedelta(days=BNB_DAYS)]
        if sum(l.credit for l in window) < BNB_LIMIT or sum(l.debit for _k, l in again) < BNB_LIMIT:
            continue
        need = p.credit
        for k, l in again:
            if need < 0.01:
                break
            used.add(k)
            need -= l.debit
        left_out += p.credit - max(0.0, need)
    total = round(sum(p.credit for p in pays), 2)
    left_out = round(min(left_out, total), 2)
    repaid = round(total - left_out, 2)
    last = max(l.when for l in lines) if lines else None
    note = (f"£{repaid:,.2f} credited to the director's loan in the nine months after the year end (to {limit:%d/%m/%Y}), "
            f"from next year's ledger ({len(pays)} line(s)), taken as repaid for s458")
    if left_out:
        note += (f"; £{left_out:,.2f} left out: lent again within 30 days (£5,000 or more each way, CTA 2010 s464ZA, "
                 f"HMRC CTM61630)")
    if last and last < limit:
        note += f". The ledger runs to {last:%d/%m/%Y}: repayments after that up to {limit:%d/%m/%Y} also count"
    return Repaid(repaid, left_out, len(pays), last, note + ". Type the figure on the client setup to change it.")
