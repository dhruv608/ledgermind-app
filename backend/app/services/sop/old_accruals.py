"""
Accruals posted during the year and never reversed (still in the accruals balance at the year end although the
suppliers' bills were also posted, so the cost is counted twice).

A year-end accrual is dated at the year end. One entered weeks or months earlier and never released usually means the
bill came in and was posted as well (a duplicate), or the accrual was simply forgotten. This lists them by supplier,
marks those whose supplier also has bills posted after the accrual (the strongest sign of a duplicate), and asks for
the duplicates to be reversed. A flag only: no journal is proposed (which accruals are duplicates needs the bills).
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List

from sqlalchemy.orm import Session

from backend.app.models.database import TBRecord
from backend.app.services.sop.common import GLLine, gl_lines

ACCRUALS_CODE = 5360
OLD_DAYS = 30                       # entered more than this before the year end
ACCRUAL_WORDS = re.compile(r"^\s*accrual?s?\s*[-:]\s*", re.I)
NAME_JUNK = re.compile(r"\b(ltd|limited|plc|llp|inc|uk|and|the|son|sons|co)\b|[^a-z ]", re.I)


@dataclass
class OldAccrual:
    supplier: str
    lines: List[GLLine] = field(default_factory=list)
    total: float = 0.0
    later_bills: float = 0.0        # the supplier's bills posted after its first open accrual

    @property
    def first(self) -> date:
        return min(l.when for l in self.lines)

    @property
    def last(self) -> date:
        return max(l.when for l in self.lines)


def _supplier(description: str) -> str:
    """'Accruals - AB Smith & Son 14/07/25 - 345584 - ...' -> 'AB Smith & Son'."""
    if (description or "").strip().startswith("("):           # '(Being current year accruals recorded)': no supplier
        return (description or "").strip()[:60]
    text = ACCRUAL_WORDS.sub("", description or "")
    text = text.split(" - ")[0]
    text = re.sub(r"\s+\d{1,2}[/.]\d{1,2}[/.]\d{2,4}.*$", "", text).strip()
    return text[:60] or "(no name)"


def _key(name: str) -> str:
    """A name reduced to its main words, so 'AB Smith & Son' and 'A.B. Smith & Son Ltd' meet."""
    return " ".join(NAME_JUNK.sub(" ", name.lower().replace(".", "")).split())


def old_open_accruals(engagement_id: str, period_end: date, tb_records: Iterable[TBRecord], db: Session) -> List[OldAccrual]:
    lines = gl_lines(engagement_id, list(tb_records), db)
    accruals = [l for l in lines if l.code == ACCRUALS_CODE]
    released = [l for l in accruals if l.debit > 0]
    cutoff = period_end - timedelta(days=OLD_DAYS)

    def reversed_later(a: GLLine) -> bool:
        """A later debit on the accruals account for the same amount and supplier releases it."""
        return any(r.when >= a.when and abs(r.debit - a.credit) < 0.01 and _key(_supplier(r.description)) == _key(_supplier(a.description))
                   for r in released)

    groups: Dict[str, OldAccrual] = {}
    for a in accruals:
        if a.credit <= 0 or a.when > cutoff or "opening" in (a.description or "").lower() or reversed_later(a):
            continue
        name = _supplier(a.description)
        g = groups.setdefault(_key(name), OldAccrual(supplier=name))
        g.lines.append(a)
        g.total = round(g.total + a.credit, 2)

    # The supplier's own bills (not journals, not the accruals account) posted after its first open accrual
    for key, g in groups.items():
        if not key:
            continue
        words = key.split()
        g.later_bills = round(sum(
            l.debit for l in lines
            if l.code != ACCRUALS_CODE and l.debit > 0 and l.when >= g.first and "journal" not in (l.source or "").lower()
            and all(w in _key(l.description) for w in words)), 2)
    return sorted(groups.values(), key=lambda g: -g.total)
