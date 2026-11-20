"""Working papers added by the accountant to an area (under /engagements/{id}): Detailed, Supporting, Reconciliation."""

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.custom_papers import CustomPaper
from backend.app.models.database import ClientEngagement

router = APIRouter()
KINDS = ("DETAILED", "SUPPORTING", "RECONCILIATION", "LOAN_SCHEDULE")   # a loan schedule keeps its terms in note (JSON)


class PaperLine(BaseModel):
    side: str                       # DEBIT / CREDIT
    label: str
    amount: float

    @field_validator("side")
    @classmethod
    def _side(cls, v: str) -> str:
        if v not in ("DEBIT", "CREDIT"):
            raise ValueError("side is DEBIT or CREDIT")
        return v


class PaperIn(BaseModel):
    area: str
    kind: str
    name: str
    codes: List[int] = []
    note: str = ""
    lines: List[PaperLine] = []


class PaperUpdate(BaseModel):
    name: Optional[str] = None
    codes: Optional[List[int]] = None
    note: Optional[str] = None
    lines: Optional[List[PaperLine]] = None


def _out(p: CustomPaper) -> dict:
    lines = json.loads(p.lines or "[]")
    debit = round(sum(l["amount"] for l in lines if l["side"] == "DEBIT"), 2)
    credit = round(sum(l["amount"] for l in lines if l["side"] == "CREDIT"), 2)
    return {"id": p.id, "area": p.area, "kind": p.kind, "name": p.name, "codes": json.loads(p.codes or "[]"),
            "note": p.note or "", "lines": lines, "debit": debit, "credit": credit, "difference": round(debit - credit, 2),
            "updated_at": p.updated_at.isoformat() if p.updated_at else None}


def _engagement(db: Session, engagement_id: str) -> None:
    if not db.get(ClientEngagement, engagement_id):
        raise HTTPException(status_code=404, detail="Client engagement not found")


def _paper(db: Session, engagement_id: str, paper_id: int) -> CustomPaper:
    p = db.get(CustomPaper, paper_id)
    if p is None or p.engagement_id != engagement_id:
        raise HTTPException(status_code=404, detail="Working paper not found")
    return p


@router.get("/{engagement_id}/custom-papers")
def list_papers(engagement_id: str, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    rows = db.query(CustomPaper).filter(CustomPaper.engagement_id == engagement_id).order_by(CustomPaper.id).all()
    return [_out(p) for p in rows]


@router.post("/{engagement_id}/custom-papers")
def add_paper(engagement_id: str, body: PaperIn, request: Request, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    if body.kind not in KINDS or not body.name.strip() or not body.area.strip():
        raise HTTPException(status_code=400, detail="A working paper needs a name, an area and a type")
    if body.kind == "DETAILED" and not body.codes:
        raise HTTPException(status_code=400, detail="Pick the account the Detailed paper is for")
    user = getattr(request.state, "user", None)
    p = CustomPaper(engagement_id=engagement_id, area=body.area[:20], kind=body.kind, name=body.name.strip()[:255],
                    codes=json.dumps(body.codes), note=body.note, lines=json.dumps([l.model_dump() for l in body.lines]),
                    user_id=getattr(user, "id", None))
    db.add(p)
    db.commit()
    return _out(p)


@router.put("/{engagement_id}/custom-papers/{paper_id}")
def update_paper(engagement_id: str, paper_id: int, body: PaperUpdate, db: Session = Depends(get_db)):
    p = _paper(db, engagement_id, paper_id)
    if body.name is not None and body.name.strip():
        p.name = body.name.strip()[:255]
    if body.codes is not None:
        p.codes = json.dumps(body.codes)
    if body.note is not None:
        p.note = body.note
    if body.lines is not None:
        p.lines = json.dumps([l.model_dump() for l in body.lines])
    p.updated_at = datetime.utcnow()
    db.commit()
    return _out(p)


@router.delete("/{engagement_id}/custom-papers/{paper_id}")
def delete_paper(engagement_id: str, paper_id: int, db: Session = Depends(get_db)):
    db.delete(_paper(db, engagement_id, paper_id))
    db.commit()
    return {"ok": True}
