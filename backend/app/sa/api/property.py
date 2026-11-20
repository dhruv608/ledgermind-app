"""Routes for UK and overseas property (SA105), property by property."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.models import SAJob, SAProperty, SAPropertyItem
from backend.app.sa.property import HEADINGS, pooled
from backend.app.sa.api.common import _owned


router = APIRouter()


class PropertyIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    share: float = 1
    use_allowance: bool = False
    losses_bf: float = 0
    finance_bf: float = 0
    country: Optional[str] = Field(None, pattern="^[A-Z]{3}$")
    foreign_tax: float = Field(0, ge=0)
    owner: Optional[str] = Field(None, pattern="^(SOLE|SPOUSE|JOINT|COMPANY)$")
    kind: Optional[str] = Field(None, pattern="^(RESIDENTIAL|COMMERCIAL)$")
    let_from: Optional[date] = None
    let_to: Optional[date] = None
    ended: Optional[str] = Field(None, pattern="^(SOLD|MOVED_IN|OTHER)$")
    own_home: Optional[str] = Field(None, pattern="^(ROOM|FORMER)$")
    rent_a_room: Optional[str] = Field(None, pattern="^(RENT_A_ROOM|ACTUAL)$")
    note: Optional[str] = None


class PropertyPatch(BaseModel):
    name: Optional[str] = None
    share: Optional[float] = None
    use_allowance: Optional[bool] = None
    losses_bf: Optional[float] = None
    finance_bf: Optional[float] = None
    country: Optional[str] = Field(None, pattern="^[A-Z]{3}$")
    foreign_tax: Optional[float] = Field(None, ge=0)
    owner: Optional[str] = Field(None, pattern="^(SOLE|SPOUSE|JOINT|COMPANY)$")
    kind: Optional[str] = Field(None, pattern="^(RESIDENTIAL|COMMERCIAL)$")
    let_from: Optional[date] = None
    let_to: Optional[date] = None
    ended: Optional[str] = Field(None, pattern="^(SOLD|MOVED_IN|OTHER)$")
    own_home: Optional[str] = Field(None, pattern="^(ROOM|FORMER)$")
    rent_a_room: Optional[str] = Field(None, pattern="^(RENT_A_ROOM|ACTUAL)$")
    note: Optional[str] = None


class ItemIn(BaseModel):
    heading: str
    amount: float
    description: str = Field(default="", max_length=255)
    on: Optional[str] = None            # YYYY-MM-DD
    months: int = 1                     # the same amount each month from 'on' (rent, mortgage interest)


def _property(db: Session, job: SAJob, property_id: int) -> SAProperty:
    p = db.get(SAProperty, property_id)
    if p is None or p.job_id != job.id:
        raise HTTPException(status_code=404, detail="Property not found")
    return p


def _property_view(db: Session, job: SAJob, overseas: bool = False) -> dict:
    from backend.app.sa.property import ALLOWANCE
    left = ALLOWANCE - pooled(db, job)["allowance_used"] if overseas else ALLOWANCE
    out = pooled(db, job, overseas=overseas, allowance_left=left)
    items = db.query(SAPropertyItem).filter(SAPropertyItem.job_id == job.id).order_by(SAPropertyItem.on, SAPropertyItem.id).all()
    props = {p.id: p for p in db.query(SAProperty).filter(SAProperty.job_id == job.id).all()}
    for row in out["properties"]:
        p = props[row["id"]]
        row.update({"losses_bf": float(p.losses_bf or 0), "finance_bf": float(p.finance_bf or 0), "note": p.note,
                    "foreign_tax": float(p.foreign_tax or 0), "kind": p.kind, "let_from": p.let_from, "let_to": p.let_to,
                    "ended": p.ended, "own_home": p.own_home, "rent_a_room": p.rent_a_room,
                    "items": [{"id": i.id, "on": i.on, "description": i.description, "heading": i.heading,
                               "amount": float(i.amount or 0), "doc_id": i.doc_id} for i in items if i.property_id == p.id]})
    out["headings"] = {k: {"label": v[0], "box": v[1]} for k, v in HEADINGS.items()}
    if not overseas:
        from backend.app.sa import property_bank
        out["bank_rent"] = property_bank.found(db, job)
    return out


class BankRentIn(BaseModel):
    keys: List[str] = Field(min_length=1)
    property_id: Optional[int] = None
    name: Optional[str] = Field(None, max_length=255)


@router.post("/jobs/{job_id}/property/bank-rent")
def add_bank_rent(job_id: str, body: BankRentIn, request: Request, db: Session = Depends(get_db)):
    """Rent found in the bank put on a property (a new one when none is given)."""
    from backend.app.sa import property_bank
    job = _owned(db, request, job_id)
    if body.property_id is not None:
        _property(db, job, body.property_id)
    property_bank.add(db, job, body.keys, body.property_id, body.name)
    return _property_view(db, job)


@router.get("/jobs/{job_id}/property")
def get_property(job_id: str, request: Request, overseas: bool = False, db: Session = Depends(get_db)):
    """The UK property business, or (overseas) the overseas one."""
    return _property_view(db, _owned(db, request, job_id), overseas)


@router.post("/jobs/{job_id}/property")
def add_property(job_id: str, body: PropertyIn, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    if not 0 < body.share <= 1:
        raise HTTPException(status_code=400, detail="The share is between 0 and 1 (0.5 for a property owned jointly by a couple).")
    db.add(SAProperty(job_id=job.id, name=body.name.strip(), share=body.share, use_allowance=int(body.use_allowance),
                      losses_bf=body.losses_bf, finance_bf=body.finance_bf, note=body.note,
                      country=None if body.country in (None, "GBR") else body.country, foreign_tax=body.foreign_tax,
                      owner=body.owner or "SOLE", kind=body.kind or "RESIDENTIAL",
                      let_from=body.let_from.isoformat() if body.let_from else None,
                      let_to=body.let_to.isoformat() if body.let_to else None, ended=body.ended, own_home=body.own_home))
    db.commit()
    return _property_view(db, job, bool(body.country and body.country != "GBR"))


@router.patch("/jobs/{job_id}/property/{property_id}")
def edit_property(job_id: str, property_id: int, body: PropertyPatch, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    p = _property(db, job, property_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, int(v) if k == "use_allowance" else v.isoformat() if isinstance(v, date) else v)
    db.commit()
    return _property_view(db, job, bool(p.country))


@router.delete("/jobs/{job_id}/property/{property_id}")
def delete_property(job_id: str, property_id: int, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    p = _property(db, job, property_id)
    db.query(SAPropertyItem).filter(SAPropertyItem.property_id == p.id).delete()
    overseas = bool(p.country)
    db.delete(p)
    db.commit()
    return _property_view(db, job, overseas)


@router.post("/jobs/{job_id}/property/{property_id}/items")
def add_items(job_id: str, property_id: int, body: ItemIn, request: Request, db: Session = Depends(get_db)):
    """One amount, or the same amount each month for a run of months (rent, mortgage interest), each dated."""
    job = _owned(db, request, job_id)
    p = _property(db, job, property_id)
    if body.heading not in HEADINGS:
        raise HTTPException(status_code=400, detail=f"Unknown heading {body.heading}")
    if not 1 <= body.months <= 24:
        raise HTTPException(status_code=400, detail="Between 1 and 24 months.")
    start = date.fromisoformat(body.on) if body.on else None
    if body.months > 1 and start is None:
        raise HTTPException(status_code=400, detail="Give the first month's date.")
    for n in range(body.months):
        on = None
        if start is not None:
            y, m = divmod(start.month - 1 + n, 12)
            on = date(start.year + y, m + 1, min(start.day, 28)).isoformat()
        db.add(SAPropertyItem(property_id=p.id, job_id=job.id, on=on, description=body.description.strip(),
                              heading=body.heading, amount=body.amount))
    db.commit()
    return _property_view(db, job, bool(p.country))


@router.delete("/jobs/{job_id}/property/{property_id}/items/{item_id}")
def delete_item(job_id: str, property_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    p = _property(db, job, property_id)
    it = db.get(SAPropertyItem, item_id)
    if it is None or it.property_id != property_id:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(it)
    db.commit()
    return _property_view(db, job, bool(p.country))
