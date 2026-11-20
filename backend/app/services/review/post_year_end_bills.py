"""U-ACC-010 Accruals from next year's ledger: bills and payments after the year end that relate to the year are
accrued (post-year-end evidence). Needs next year's ledger uploaded; nothing without it.

  1. A cost after the year end whose own wording states a period in the year (a date range, 'Mar 2025', the month it
     names): the share of its days up to the year end is accrued.
  2. A regular monthly cost with nothing in the final month: the first cost on that account
     after the year end, within 45 days and about one month's cost (within half of the average either way), is the
     final month's bill: accrued.

Accrued net of VAT as the ledger holds it, from £500 (smaller ones are not material). A cost account that already has an accrual journal in this run (as last
year, the fee, a line typed by the accountant) is left alone, so nothing is accrued twice. Each is a proposed journal:
Dr the cost / Cr accruals (5360)."""

from datetime import timedelta
from typing import List, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord

ACCRUALS = 5360
FIRST_BILL_DAYS = 45
CLOSE = 0.5                 # the first bill within half of the monthly average either way is one month's bill
MIN_AMOUNT = 25.0          # a line worth looking at
MIN_ACCRUAL = 500.0        # a smaller accrual is not made (not material)


def _accrued_codes(journals: List[ProposedJournal]) -> Set[int]:
    out = set()
    for j in journals:
        lines = [(int(l.account_code), float(l.debit or 0), float(l.credit or 0)) for l in (j.lines or [])]
        if not lines:
            lines = [(int(j.debit_code), float(j.amount or 0), 0.0), (int(j.credit_code), 0.0, float(j.amount or 0))]
        if any(c == ACCRUALS and cr > 0 for c, _d, cr in lines):
            out |= {c for c, d, _cr in lines if d > 0 and c != ACCRUALS}
    return out


def post_year_end_accruals(engagement: ClientEngagement, tb_records: List[TBRecord], chart, db: Session,
                           counter: List[int], earlier: List[ProposedJournal]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.ingestion.next_year import next_year_lines
    from backend.app.services.review.yearend_journals import _entry, _journal, _point
    from backend.app.services.sop.accruals import accrual_review
    from backend.app.services.sop.prepayments import period_is_stated, service_period
    after = next_year_lines(str(engagement.id), db)
    end = engagement.period_end_date
    if not after or end is None:
        return [], []
    done = _accrued_codes(earlier)
    findings, journals = [], []

    def propose(code: int, amount: float, text: str, why: str) -> None:
        amount = round(amount, 2)
        if amount < MIN_ACCRUAL or code in done:
            return
        done.add(code)
        entry = _entry(code, ACCRUALS, amount, chart)
        point = _point(engagement, "U-ACC-010", "Accruals: post-year-end bill",
                       f"{chart.name(code, str(code))}: £{amount:,.2f} accrued from a bill after the year end"[:255],
                       f"{why} A journal is proposed (Journals tab): {entry}.", amount, entry)
        findings.append(point)
        journals.append(_journal(engagement, counter, f"Accrual (post-year-end bill): {text}"[:255], code, ACCRUALS,
                                 amount, chart, point))

    def is_cost(code) -> bool:
        c = chart.accounts.get(code) if hasattr(chart, "accounts") else None
        return code is not None and c is not None and c.financial_class == "Profit and Loss" and \
            c.category not in ("Sales", "Other operating income") and code < 4000

    # 1. A stated period in the year
    for l in after:
        if not is_cost(l.code) or l.debit < MIN_AMOUNT:
            continue
        period = service_period(l.description, l.when)
        if period is None or not period_is_stated(period[2]) or period[0] > end:
            continue
        start, finish, basis = period
        days = (finish - start).days + 1
        in_year = (min(finish, end) - start).days + 1
        if days <= 0 or in_year <= 0:
            continue
        propose(l.code, l.debit * in_year / days, l.description[:120],
                f"'{l.description[:80]}' dated {l.when:%d/%m/%Y} (next year's ledger) is for {start:%d/%m/%Y} to "
                f"{finish:%d/%m/%Y} ({basis}): {in_year} of its {days} days are in the year, so £{l.debit * in_year / days:,.2f} "
                f"of its £{l.debit:,.2f} is a cost of the year, owed at the year end.")

    # 2. The final month of a regular cost, from its first bill after the year end
    for f in accrual_review(str(engagement.id), end, tb_records, db):
        if not f.final_missing or f.average < MIN_AMOUNT:
            continue
        first = next((l for l in after if l.code == f.code and l.debit >= MIN_AMOUNT
                      and l.when <= end + timedelta(days=FIRST_BILL_DAYS)), None)
        if first is None or not (1 - CLOSE) * f.average <= first.debit <= (1 + CLOSE) * f.average:
            continue
        propose(f.code, first.debit, f"{f.account} - {first.description[:80]}",
                f"{f.account} has a cost in most months but none in the final month; the first one after the year end, "
                f"'{first.description[:80]}' on {first.when:%d/%m/%Y} (next year's ledger) for £{first.debit:,.2f}, is "
                f"about one month's cost (average £{f.average:,.2f}): the final month's bill, owed at the year end.")
    return findings, journals
