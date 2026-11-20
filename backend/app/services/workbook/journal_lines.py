"""The approved journals as the workbook's B2 tab takes them: one record per line, with where each journal came from
and its status (No | Date | Code | Account | Dr | Cr | Narrative | Source | Status). Used by the
workpapers endpoint and the test runner, so both build the tab from the same records."""

from typing import Any, Dict, List, Sequence

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ProposedJournal


def journal_source(j: ProposedJournal, refs: Dict[int, str]) -> str:
    """Where the journal came from: its review point by name ('Review point: Prepayment of insurance'), or a manual
    journal."""
    if (j.source or "").upper() == "MANUAL":
        return "Manual journal"
    title = refs.get(j.finding_id) if j.finding_id else None
    return f"Review point: {title[:80]}" if title else "Review"


def workbook_journals(db: Session, journals: Sequence[ProposedJournal]) -> List[Dict[str, Any]]:
    """One record per journal line, numbered 1, 2 ... in the order given."""
    ids = [j.finding_id for j in journals if j.finding_id]
    refs = {f.id: f.finding_title for f in db.query(AuditFinding).filter(AuditFinding.id.in_(ids))} if ids else {}
    out: List[Dict[str, Any]] = []
    for i, j in enumerate(journals, start=1):
        common = {"no": i, "source": journal_source(j, refs), "status": (j.status or "").title()}
        if j.lines:
            out += [{**common, "narrative": line.narrative or j.description, "code": str(line.account_code),
                     "debit": float(line.debit) if line.debit else None,
                     "credit": float(line.credit) if line.credit else None} for line in j.lines]
            continue
        out += [{**common, "narrative": j.description, "code": str(j.debit_code), "debit": float(j.amount),
                 "credit": None},
                {**common, "narrative": j.description, "code": str(j.credit_code), "debit": None,
                 "credit": float(j.amount)}]
    return out
