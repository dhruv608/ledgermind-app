"""An accrual or prepayment the app found, edited by the accountant: the reviewer can add, edit or delete a schedule
row, and its journal changes with it.

The app's proposed journal (a prepayment found in the ledger, an accrual from a bill) becomes the accountant's own line
for this year (models/yearend_adjustments.py) with the amount, description and cost they give; the app's proposal is
marked rejected (replaced); the next run proposes the journal from the accountant's line. From then on the
accountant's line for that cost wins: the app does not propose its own accrual or prepayment on the same cost again,
so nothing is posted twice. The line is then edited or deleted on the accruals and prepayments panel like any other."""

from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal
from backend.app.models.yearend_adjustments import YearEndAdjustment

ACCRUALS, PREPAYMENTS = 5360, 4900
EDITED = " (edited from review point {ref})"


def kind_of(journal: ProposedJournal) -> Optional[Tuple[str, int]]:
    """('ACCRUAL', cost) for Dr cost / Cr accruals, ('PREPAYMENT', cost) for Dr prepayments / Cr cost; None for any
    other journal (a release of last year's is the other way round and is not this year's item)."""
    if journal.credit_code == ACCRUALS and journal.debit_code != ACCRUALS:
        return "ACCRUAL", int(journal.debit_code)
    if journal.debit_code == PREPAYMENTS and journal.credit_code != PREPAYMENTS:
        return "PREPAYMENT", int(journal.credit_code)
    return None


def _typed(engagement: ClientEngagement, db: Session) -> Set[Tuple[str, int]]:
    return {(l.kind, int(l.cost_code)) for l in db.query(YearEndAdjustment).filter(
        YearEndAdjustment.engagement_id == engagement.id, YearEndAdjustment.period == "THIS_YEAR")
        if l.cost_code}


def accountant_wins(engagement: ClientEngagement, db: Session, findings: List[AuditFinding],
                    journals: List[ProposedJournal]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """The app's accrual and prepayment journals less those on a cost the accountant has their own line for (of the
    same kind), and their points with them."""
    typed = _typed(engagement, db)
    if not typed:
        return findings, journals
    dropped = [j for j in journals if kind_of(j) in typed]
    if not dropped:
        return findings, journals
    gone = {id(getattr(j, "_point", None)) for j in dropped}
    return ([f for f in findings if id(f) not in gone], [j for j in journals if j not in dropped])


def edit_into_line(db: Session, journal: ProposedJournal, amount: float, description: str,
                   cost_code: Optional[int], user_id: Optional[int]) -> YearEndAdjustment:
    """The app's proposed accrual or prepayment as the accountant's own line, the proposal rejected. ValueError when it
    cannot be edited (approved, entered by hand, or not an accrual or prepayment)."""
    if journal.status == "APPROVED":
        raise ValueError("An approved journal is not edited: un-approve it first.")
    if (journal.source or "REVIEW") == "MANUAL":
        raise ValueError("A journal you entered is edited on the Journals tab.")
    kind = kind_of(journal)
    if kind is None:
        raise ValueError("Only an accrual or a prepayment the app proposed can be edited here.")
    if amount is None or float(amount) <= 0:
        raise ValueError("Give an amount above nil.")
    finding = db.get(AuditFinding, journal.finding_id) if journal.finding_id else None
    ref = finding.procedure_ref if finding is not None else journal.journal_ref
    text = (description or journal.description or "").strip()
    line = YearEndAdjustment(engagement_id=journal.engagement_id, kind=kind[0], period="THIS_YEAR",
                             description=(text[:200] + EDITED.format(ref=ref))[:255],
                             cost_code=int(cost_code or kind[1]), amount=round(float(amount), 2), created_by=user_id)
    db.add(line)
    journal.status = "REJECTED"
    db.commit()
    db.refresh(line)
    return line
