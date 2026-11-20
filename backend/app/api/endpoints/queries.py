"""The Queries tab (under /engagements/{id}): one list of everything the app asks about the job, for the client, the
accountant or the preparer, and what was done to each (answered, cleared)."""

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement
from backend.app.services.queries.query_list import query_list, raise_query, remove_raised, update_query

router = APIRouter()


class QueryUpdate(BaseModel):
    key: str
    status: Optional[str] = None                 # OPEN, ANSWERED, CLEARED
    answer: Optional[str] = None
    audience: Optional[str] = None               # CLIENT, ACCOUNTANT, INTERNAL
    item_answers: Optional[Dict[str, str]] = None   # a bank query's lines: {"bank:40": "rent from a tenant"}


@router.get("/{engagement_id}/queries")
def get_queries(engagement_id: str, db: Session = Depends(get_db)):
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return query_list(db, eng)


@router.post("/{engagement_id}/queries")
def save_query(engagement_id: str, payload: QueryUpdate, request: Request, db: Session = Depends(get_db)):
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    try:
        update_query(db, eng, payload.key, request.state.user.id, status=payload.status, answer=payload.answer,
                     audience=payload.audience, item_answers=payload.item_answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return query_list(db, eng)


class RaisedQueryIn(BaseModel):
    title: str
    detail: str = ""
    audience: str = "CLIENT"
    area: str = ""
    amount: float = 0.0
    finding_id: Optional[int] = None             # the point it is raised on, if any


@router.post("/{engagement_id}/queries/raised")
def add_raised_query(engagement_id: str, payload: RaisedQueryIn, request: Request, db: Session = Depends(get_db)):
    """A query raised by hand on an area page; the whole list comes back."""
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    try:
        raise_query(db, eng, request.state.user.id, payload.title, payload.detail, payload.audience, payload.area,
                    payload.amount, payload.finding_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return query_list(db, eng)


@router.delete("/{engagement_id}/queries/raised/{raised_id}")
def delete_raised_query(engagement_id: str, raised_id: int, db: Session = Depends(get_db)):
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    try:
        remove_raised(db, eng, raised_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return query_list(db, eng)
