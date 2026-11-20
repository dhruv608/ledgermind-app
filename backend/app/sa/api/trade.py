"""Routes for self-employment (SA103), business by business, with its items and capital allowances."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.models import SAJob, SABusiness, SABusinessItem
from backend.app.sa.trade import HEADINGS as TRADE_HEADINGS, all_businesses
from backend.app.sa.api.common import _owned


router = APIRouter()


class BusinessIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None


class BusinessPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    cash_basis: Optional[bool] = None
    use_trading_allowance: Optional[bool] = None
    home_hours: Optional[int] = None
    home_months: Optional[int] = None
    car_miles: Optional[int] = None
    motorcycle_miles: Optional[int] = None
    capital_allowances: Optional[float] = None
    balancing_charges: Optional[float] = None
    losses_bf: Optional[float] = None
    cis_deducted: Optional[float] = None
    note: Optional[str] = None


class TradeItemIn(BaseModel):
    heading: str
    amount: float
    disallowed: float = 0
    description: str = Field(default="", max_length=255)


def _business(db: Session, job: SAJob, business_id: int) -> SABusiness:
    b = db.get(SABusiness, business_id)
    if b is None or b.job_id != job.id:
        raise HTTPException(status_code=404, detail="Business not found")
    return b


def _trade_view(db: Session, job: SAJob) -> dict:
    out = all_businesses(db, job)
    items = db.query(SABusinessItem).filter(SABusinessItem.job_id == job.id).order_by(SABusinessItem.id).all()
    bizs = {b.id: b for b in db.query(SABusiness).filter(SABusiness.job_id == job.id).all()}
    for row in out["businesses"]:
        b = bizs[row["id"]]
        row["settings"] = {k: (float(getattr(b, k)) if k in ("capital_allowances", "balancing_charges", "losses_bf", "cis_deducted")
                               else bool(getattr(b, k)) if k in ("cash_basis", "use_trading_allowance") else getattr(b, k))
                           for k in BusinessPatch.model_fields}
        row["items"] = [{"id": i.id, "heading": i.heading, "description": i.description, "amount": float(i.amount or 0),
                         "disallowed": float(i.disallowed or 0), "doc_id": i.doc_id} for i in items if i.business_id == b.id]
        # A trade built from the bank: its small balance sheet (SEF 5) and the check that proves it (balance_sheet.py)
        row["balance_sheet"] = None
        from backend.app.sa.books import FROM_BANK
        if any(i.business_id == b.id and i.description == FROM_BANK for i in items):
            try:
                from backend.app.sa.balance_sheet import build as _bs
                row["balance_sheet"] = _bs(db, job, b)
            except Exception:
                row["balance_sheet"] = None    # statements that cannot be put together: no balance sheet
    out["headings"] = {k: {"label": v[0], "box": v[1], "kind": v[2]} for k, v in TRADE_HEADINGS.items()}
    return out


@router.get("/jobs/{job_id}/trade")
def get_trade(job_id: str, request: Request, db: Session = Depends(get_db)):
    return _trade_view(db, _owned(db, request, job_id))


@router.post("/jobs/{job_id}/trade")
def add_business(job_id: str, body: BusinessIn, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    db.add(SABusiness(job_id=job.id, name=body.name.strip(), description=body.description))
    db.commit()
    return _trade_view(db, job)


@router.patch("/jobs/{job_id}/trade/{business_id}")
def edit_business(job_id: str, business_id: int, body: BusinessPatch, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    b = _business(db, job, business_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in ("home_hours", "home_months", "car_miles", "motorcycle_miles") and v is not None and v < 0:
            raise HTTPException(status_code=400, detail="Hours, months and miles cannot be negative.")
        if k == "home_months" and v is not None and v > 12:
            raise HTTPException(status_code=400, detail="At most 12 months.")
        setattr(b, k, int(v) if k in ("cash_basis", "use_trading_allowance") else v)
    db.commit()
    return _trade_view(db, job)


@router.delete("/jobs/{job_id}/trade/{business_id}")
def delete_business(job_id: str, business_id: int, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    b = _business(db, job, business_id)
    db.query(SABusinessItem).filter(SABusinessItem.business_id == b.id).delete()
    from backend.app.sa.models import SAAllowance
    db.query(SAAllowance).filter(SAAllowance.business_id == b.id).delete()
    db.delete(b)
    db.commit()
    return _trade_view(db, job)


@router.post("/jobs/{job_id}/trade/{business_id}/items")
def add_trade_item(job_id: str, business_id: int, body: TradeItemIn, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    b = _business(db, job, business_id)
    if body.heading not in TRADE_HEADINGS:
        raise HTTPException(status_code=400, detail=f"Unknown heading {body.heading}")
    if body.disallowed and abs(body.disallowed) > abs(body.amount) + 0.005:
        raise HTTPException(status_code=400, detail="The part not allowed cannot be more than the cost.")
    if TRADE_HEADINGS[body.heading][2] == "income" and body.disallowed:
        raise HTTPException(status_code=400, detail="Income has no part to disallow.")
    db.add(SABusinessItem(business_id=b.id, job_id=job.id, heading=body.heading, description=body.description.strip(),
                          amount=body.amount, disallowed=body.disallowed))
    db.commit()
    return _trade_view(db, job)


@router.delete("/jobs/{job_id}/trade/{business_id}/items/{item_id}")
def delete_trade_item(job_id: str, business_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    _business(db, job, business_id)
    it = db.get(SABusinessItem, item_id)
    if it is None or it.business_id != business_id:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(it)
    db.commit()
    return _trade_view(db, job)


class AllowanceIn(BaseModel):
    kind: str = Field(..., pattern="^(AIA|MAIN|SPECIAL|SMALL|ZEC|FYA|SBA|BALANCING)$")
    description: str = Field("", max_length=255)
    amount: float = Field(..., ge=0)
    private_use: float = Field(0, ge=0, lt=1)


@router.post("/jobs/{job_id}/trade/{business_id}/allowances")
def add_allowance(job_id: str, business_id: int, body: AllowanceIn, request: Request, db: Session = Depends(get_db)):
    """A capital allowance line: its total replaces the business's single capital allowances figure."""
    from backend.app.sa.models import SAAllowance
    job = _owned(db, request, job_id)
    biz = _business(db, job, business_id)
    db.add(SAAllowance(business_id=biz.id, job_id=job.id, kind=body.kind, description=body.description.strip(),
                       amount=body.amount, private_use=body.private_use))
    db.commit()
    return _trade_view(db, job)


@router.delete("/jobs/{job_id}/trade/{business_id}/allowances/{allowance_id}")
def delete_allowance(job_id: str, business_id: int, allowance_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SAAllowance
    job = _owned(db, request, job_id)
    biz = _business(db, job, business_id)
    a = db.get(SAAllowance, allowance_id)
    if a is None or a.business_id != biz.id:
        raise HTTPException(status_code=404, detail="Allowance not found")
    db.delete(a)
    db.commit()
    return _trade_view(db, job)
