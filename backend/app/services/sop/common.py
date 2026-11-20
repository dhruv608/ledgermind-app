"""
Shared by the SOP checks: the ledger lines with their firm codes, the months of the year, supplier names.
"""

import calendar
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Dict, Iterable, Iterator, List, NamedTuple, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import GLTransaction, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, account_name_keys

PAYROLL_CODES = set(range(3000, 3016))
MIN_LINE_AMOUNT = 1.0           # ignore pennies (rounding lines)

# P&L expenses only (no income, depreciation or tax; salaries are never prepaid)
NOT_PREPAYABLE_SECTIONS = {"Sales", "Other operating income", "Income from shares in group undertakings",
                           "Income from participating interests", "Income from other fixed asset investments",
                           "Income from other current asset investments", "Interest receivable and similar income",
                           "Depreciation", "Current tax", "Deferred tax"}


class GLLine(NamedTuple):
    when: date
    code: int
    account: str
    debit: float
    credit: float
    description: str
    source: str
    tracking: str = ""      # property / class / location tag, when the ledger has one
    reference: str = ""     # the transaction's number (a QuickBooks bill's 'No.'): its lines share it


def year_months(period_end: date) -> List[date]:
    """Month ends of the 12 months of the financial year, oldest first."""
    months, y, m = [], period_end.year, period_end.month
    for _ in range(12):
        months.insert(0, date(y, m, calendar.monthrange(y, m)[1]))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return months


# While a review runs, the job's ledger is read from the database once and every check shares it (otherwise a review
# reads it about 15 times, half the time of a review on a big ledger). Outside ledger_read_once() nothing is kept.
_ledger_cache: ContextVar[Optional[Dict[tuple, list]]] = ContextVar("_ledger_cache", default=None)


@contextmanager
def ledger_read_once() -> Iterator[None]:
    """Within it, ledger_rows() and gl_lines() read each job's ledger once (for the same account codes)."""
    token = _ledger_cache.set({})
    try:
        yield
    finally:
        _ledger_cache.reset(token)


def ledger_rows(engagement_id: str, db: Session) -> List[GLTransaction]:
    """The job's ledger rows (GLTransaction): from the database, or the copy read earlier in this review."""
    cache = _ledger_cache.get()
    key = ("rows", str(engagement_id))
    if cache is not None and key in cache:
        return cache[key]
    rows = list(db.execute(select(GLTransaction).where(GLTransaction.engagement_id == engagement_id)).scalars())
    if cache is not None:
        cache[key] = rows
    return rows


def code_matcher(codes: Dict[str, int]):
    """A ledger account name -> its firm code (None: no TB account matches), each name worked out once."""
    seen: Dict[str, Optional[int]] = {}

    ambiguous = getattr(codes, "ambiguous", set())

    def code_of(raw_name: Optional[str]) -> Optional[int]:
        name = raw_name or ""
        if name not in seen:
            keys = account_name_keys(name)
            parts = [p.strip() for p in name.lower().split(":")]
            if len(parts) > 1:
                # A QuickBooks sub-account ('Parent:Child') takes its parent's code when the TB has no account of its
                # own for it; and when the TB uses its own name under two parents, the parent decides
                # ('Sub-Contractors:<name>' is a subcontractor cost, not the '<name>' sale account)
                parents = [":".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]
                if parts[-1] in ambiguous:
                    keys = [k for k in keys if k != parts[-1]]
                keys = keys + [p for p in parents if p not in keys]
            seen[name] = next((codes[k] for k in keys if k in codes), None)
        return seen[name]
    return code_of


def gl_lines(engagement_id: str, tb_records: Iterable[TBRecord], db: Session) -> List[GLLine]:
    """Every ledger line whose account is mapped in the TB, with its firm code."""
    tb_records = list(tb_records)
    cache = _ledger_cache.get()
    key = ("lines", str(engagement_id), tuple(sorted((t.raw_account_name or "", t.std_code or -1) for t in tb_records)))
    if cache is not None and key in cache:
        return list(cache[key])
    code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))
    lines = []
    for tx in ledger_rows(engagement_id, db):
        code = code_of(tx.raw_account_name)
        if code is not None and tx.transaction_date:
            lines.append(GLLine(tx.transaction_date, code, tx.raw_account_name, float(tx.debit_amount or 0),
                                float(tx.credit_amount or 0), tx.description or "", tx.source or "", tx.tracking or "",
                                tx.reference or ""))
    if cache is not None:
        cache[key] = lines
    return list(lines)


def supplier_name(description: str) -> str:
    """The supplier part of a ledger description ('Slack - Slack T010r1rlsjk' -> 'slack')."""
    return (description or "").split(" - ")[0].strip().lower()[:60]
