"""The Opening balances area: each balance's opening in the books against last year's closing, why they differ,
and the reserve brought forward at the foot."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import owned_engagement
from backend.app.core.database import get_db
from backend.app.models.database import TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.opening_balances import opening_points

router = APIRouter()


@router.get("/{engagement_id}/opening-balances")
def get_opening_balances(engagement_id: str, request: Request, db: Session = Depends(get_db)):
    eng = owned_engagement(db, request.state.user, engagement_id)
    tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == eng.id)).scalars())
    table = {"source": "", "rows": []}
    # The same comparison as the review's (its points and journals are not kept here)
    _points, _journals, compared = opening_points(eng, tb, ChartLookup(db), db, [1], table=table)
    db.rollback()
    return {**table, "compared": compared}
