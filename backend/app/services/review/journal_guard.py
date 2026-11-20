"""The same journal is never posted twice: same codes, same amount and same narrative are blocked at posting (a
duplicated journal can, for example, make cash negative).

A journal's signature is its narrative and its lines (code, debit, credit), or for a two-line journal its debit code,
credit code and amount. Approving a journal whose twin is already approved is refused, and the workbook takes each
approved signature once."""

from typing import Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import ProposedJournal


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").lower().split())


def signature(j: ProposedJournal) -> Tuple:
    lines = list(getattr(j, "lines", None) or [])
    if lines:
        body = tuple(sorted((int(l.account_code), round(float(l.debit or 0), 2), round(float(l.credit or 0), 2))
                            for l in lines))
    else:
        body = ((int(j.debit_code or 0), round(float(j.amount or 0), 2), 0.0),
                (int(j.credit_code or 0), 0.0, round(float(j.amount or 0), 2)))
    return _norm(j.description), body


def approved_twin(db: Session, j: ProposedJournal) -> Optional[ProposedJournal]:
    """Another journal of the same engagement, already approved, with the same signature."""
    mine = signature(j)
    for other in db.query(ProposedJournal).filter(ProposedJournal.engagement_id == j.engagement_id,
                                                  ProposedJournal.status == "APPROVED",
                                                  ProposedJournal.id != j.id):
        if signature(other) == mine:
            return other
    return None


def once_each(journals: Iterable[ProposedJournal]) -> Tuple[List[ProposedJournal], List[ProposedJournal]]:
    """(the journals to post, each signature once in order; the twins left out)."""
    seen, keep, twins = set(), [], []
    for j in journals:
        s = signature(j)
        (twins if s in seen else keep).append(j)
        seen.add(s)
    return keep, twins
