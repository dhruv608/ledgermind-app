"""The closing stock line by line (under /engagements/{id}): read, and saved as a whole list (the screen edits them
together, as the accruals and prepayments lines)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.models.stock_lines import StockLine

router = APIRouter()
STOCK_CODES = range(4300, 4311)


class StockLineIn(BaseModel):
    code: Optional[int] = None
    stock_type: str = ""
    description: str = ""
    amount: float = 0.0
    impairment: float = 0.0
    last_year: Optional[float] = None
    note: str = ""


class StockLinesIn(BaseModel):
    lines: List[StockLineIn]
    verified_by: str = ""           # US / CLIENT / ""


def _out(db: Session, engagement_id: str) -> dict:
    rows = db.execute(select(StockLine).where(StockLine.engagement_id == engagement_id).order_by(StockLine.id)).scalars().all()
    books = sum(float(t.net_amount or 0) for t in db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement_id)).scalars()
                if t.std_code in STOCK_CODES)
    lines = [{"code": r.code, "stock_type": r.stock_type, "description": r.description, "amount": r.amount,
              "impairment": r.impairment, "last_year": r.last_year, "note": r.note} for r in rows]
    total = round(sum(l["amount"] - l["impairment"] for l in lines), 2)
    return {"lines": lines, "verified_by": rows[0].verified_by if rows else "", "total": total,
            "books": round(books, 2), "difference": round(books - total, 2) if lines else None}


@router.get("/{engagement_id}/stock-lines")
def get_stock_lines(engagement_id: str, db: Session = Depends(get_db)):
    if not db.get(ClientEngagement, engagement_id):
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return _out(db, engagement_id)


@router.put("/{engagement_id}/stock-lines")
def save_stock_lines(engagement_id: str, body: StockLinesIn, db: Session = Depends(get_db)):
    if not db.get(ClientEngagement, engagement_id):
        raise HTTPException(status_code=404, detail="Client engagement not found")
    if body.verified_by not in ("", "US", "CLIENT"):
        raise HTTPException(status_code=400, detail="Verified by is US or CLIENT")
    db.execute(delete(StockLine).where(StockLine.engagement_id == engagement_id))
    for l in body.lines:
        if not (l.description.strip() or l.amount or l.impairment):
            continue
        db.add(StockLine(engagement_id=engagement_id, code=l.code, stock_type=l.stock_type[:40],
                         description=l.description.strip()[:255], amount=float(l.amount), impairment=float(l.impairment),
                         last_year=l.last_year, verified_by=body.verified_by, note=l.note[:500]))
    db.commit()
    return _out(db, engagement_id)
