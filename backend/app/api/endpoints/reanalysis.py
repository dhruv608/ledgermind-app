"""The reanalysis area of a client: the moves the engine proposes, and the accountant's decision on each."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api.deps import owned_engagement
from backend.app.core.database import get_db
from backend.app.services.reanalysis import misposting
from backend.app.services.reanalysis.run import decide_group, groups

router = APIRouter()


class DecisionRequest(BaseModel):
    key: str
    action: str     # APPROVE or REJECT


@router.get("/{engagement_id}/reanalysis")
def get_reanalysis(engagement_id: str, request: Request, db: Session = Depends(get_db)):
    eng = owned_engagement(db, request.state.user, engagement_id)
    return groups(eng, db)


@router.post("/{engagement_id}/reanalysis/decide")
def post_decision(engagement_id: str, payload: DecisionRequest, request: Request, db: Session = Depends(get_db)):
    eng = owned_engagement(db, request.state.user, engagement_id)
    action = payload.action.upper()
    if action not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="Approve or reject")
    try:
        return decide_group(eng, db, payload.key, action, request.state.user.id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


class MispostingRequest(BaseModel):
    merchant_key: str
    action: str                             # MOVE, IGNORE or UNDO
    line_keys: List[str] = []
    to_code: Optional[int] = None
    remark: str = ""


@router.get("/{engagement_id}/mispostings")
def get_mispostings(engagement_id: str, request: Request, db: Session = Depends(get_db)):
    """Suppliers split across profit and loss accounts (the misposting review)."""
    eng = owned_engagement(db, request.state.user, engagement_id)
    return misposting.review(eng, db)


@router.post("/{engagement_id}/mispostings/decide")
def post_misposting(engagement_id: str, payload: MispostingRequest, request: Request, db: Session = Depends(get_db)):
    eng = owned_engagement(db, request.state.user, engagement_id)
    try:
        return misposting.decide(eng, db, payload.merchant_key, payload.action.upper(), request.state.user.id,
                                 payload.line_keys, payload.to_code, payload.remark)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
