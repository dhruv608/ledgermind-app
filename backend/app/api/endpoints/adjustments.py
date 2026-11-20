"""The client's accruals and prepayments screen (under /engagements/{id}): this year's lines, last year's lines to
reverse (or last year's client's own, when it is in the app), and what the books still hold brought forward."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord
from backend.app.models.yearend_adjustments import YearEndAdjustment
from backend.app.services.shared.activity import mark_changed
from backend.app.services.review.adjustments import ACCRUALS, KINDS, PREPAYMENTS, last_year_lines

router = APIRouter()


class AdjustmentLine(BaseModel):
    kind: str                                  # ACCRUAL / PREPAYMENT
    description: str = ""
    cost_code: int
    amount: float = Field(gt=0)
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    invoice_amount: Optional[float] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None


class AdjustmentsSave(BaseModel):
    this_year: List[AdjustmentLine] = []
    last_year: Optional[List[AdjustmentLine]] = None     # None: leave last year's lines as they are


def _line(r: YearEndAdjustment, names) -> dict:
    iso = lambda d: d.isoformat() if d else None
    return {"id": r.id, "kind": r.kind, "description": r.description, "cost_code": r.cost_code,
            "cost_name": names.get(r.cost_code, ""), "amount": round(float(r.amount or 0), 2),
            "invoice_number": getattr(r, "invoice_number", None), "invoice_date": iso(getattr(r, "invoice_date", None)),
            "invoice_amount": None if getattr(r, "invoice_amount", None) is None else round(float(r.invoice_amount), 2),
            "period_from": iso(getattr(r, "period_from", None)), "period_to": iso(getattr(r, "period_to", None))}


@router.get("/{engagement_id}/adjustments")
def get_adjustments(engagement_id: str, db: Session = Depends(get_db)):
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    from backend.app.services.tax.ct_computation import final_balances
    names = {c.std_code: c.std_name for c in db.query(MasterCOA)}
    this_year = db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == engagement_id,
                                                   YearEndAdjustment.period == "THIS_YEAR").order_by(YearEndAdjustment.id).all()
    last, source = last_year_lines(eng, db)
    tb = db.query(TBRecord).filter(TBRecord.engagement_id == engagement_id).all()
    after = final_balances(engagement_id, tb, db)
    return {
        "this_year": [_line(r, names) for r in this_year],
        "last_year": [_line(r, names) for r in last],
        "last_year_source": source,             # 'last year in the app' (read only here) / 'entered' / ''
        "last_year_editable": source != "last year in the app",
        "in_books": {"accruals": round(-after.get(ACCRUALS, 0.0), 2), "prepayments": round(after.get(PREPAYMENTS, 0.0), 2)},
    }


@router.put("/{engagement_id}/adjustments")
def save_adjustments(engagement_id: str, body: AdjustmentsSave, request: Request, db: Session = Depends(get_db)):
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    chart = {c.std_code: c for c in db.query(MasterCOA)}
    for line in body.this_year + (body.last_year or []):
        if line.kind not in KINDS:
            raise HTTPException(status_code=400, detail=f"Unknown type '{line.kind}': accrual or prepayment")
        c = chart.get(line.cost_code)
        if c is None or c.financial_class != "Profit and Loss":
            raise HTTPException(status_code=400, detail=f"Code {line.cost_code} is not a P&L account in the chart")
    user = getattr(request.state, "user", None)
    periods = [("THIS_YEAR", body.this_year)] + ([("LAST_YEAR", body.last_year)] if body.last_year is not None else [])
    for period, lines in periods:
        db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == engagement_id,
                                           YearEndAdjustment.period == period).delete(synchronize_session=False)
        for line in lines:
            db.add(YearEndAdjustment(engagement_id=engagement_id, kind=line.kind, period=period,
                                     description=line.description.strip()[:255], cost_code=line.cost_code,
                                     amount=round(line.amount, 2), created_by=getattr(user, "id", None),
                                     invoice_number=(line.invoice_number or "").strip()[:60] or None,
                                     invoice_date=line.invoice_date, invoice_amount=line.invoice_amount,
                                     period_from=line.period_from, period_to=line.period_to))
    db.commit()
    mark_changed(db, engagement_id)
    return get_adjustments(engagement_id, db)
