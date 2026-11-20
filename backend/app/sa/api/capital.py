"""Routes for capital gains: disposals, losses and share trades."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.income import calculation
from backend.app.sa.models import SAJob
from backend.app.sa.api.common import _owned


router = APIRouter()


class DisposalIn(BaseModel):
    kind: str = Field("LISTED", pattern="^(RESIDENTIAL|CRYPTO|OTHER|LISTED|UNLISTED)$")
    name: str = Field("", max_length=255)
    acquired: Optional[date] = None
    contract_date: Optional[date] = None
    completion_date: Optional[date] = None
    proceeds: float = Field(0, ge=0)
    cost: float = Field(0, ge=0)
    costs: float = Field(0, ge=0)
    improvements: float = Field(0, ge=0)
    share: float = Field(1, gt=0, le=1)
    uk: bool = True
    main_home_months: Optional[int] = Field(None, ge=0, le=1200)
    badr: bool = False
    negligible: bool = False
    rtt_date: Optional[date] = None
    rtt_gain: Optional[float] = None
    rtt_tax: Optional[float] = Field(None, ge=0)
    note: Optional[str] = Field(None, max_length=2000)


class CapitalIn(BaseModel):
    losses_bf: float = Field(0, ge=0)


def _cgt_view(db: Session, job: SAJob) -> dict:
    from backend.app.sa.cgt import KINDS
    from backend.app.sa.models import SACapital
    calc = calculation(db, job)
    cap = db.get(SACapital, job.id)
    c = calc["calculation"]
    return {**calc["cgt"], "kinds": [{"kind": k, "label": v} for k, v in KINDS.items()],
            "losses_bf": float(cap.losses_bf) if cap else 0.0,
            "result": {"cgt": c["cgt"], "cgt_paid": c["cgt_paid"], "balance": c["balance"]}}


def _disposal_fields(body: DisposalIn) -> dict:
    data = body.model_dump()
    for k in ("acquired", "contract_date", "completion_date", "rtt_date"):
        data[k] = data[k].isoformat() if data[k] else None
    for k in ("uk", "badr", "negligible"):
        data[k] = int(data[k])
    data["name"] = data["name"].strip() or "Disposal"
    return data


@router.get("/jobs/{job_id}/capital-gains")
def get_capital_gains(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Each disposal with its gain or loss and what is still to ask, and the year's capital gains tax."""
    return _cgt_view(db, _owned(db, request, job_id))


@router.post("/jobs/{job_id}/capital-gains/disposals")
def add_disposal(job_id: str, body: DisposalIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SADisposal
    job = _owned(db, request, job_id)
    db.add(SADisposal(job_id=job.id, **_disposal_fields(body)))
    db.commit()
    return _cgt_view(db, job)


@router.put("/jobs/{job_id}/capital-gains/disposals/{disposal_id}")
def edit_disposal(job_id: str, disposal_id: int, body: DisposalIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SADisposal
    job = _owned(db, request, job_id)
    d = db.get(SADisposal, disposal_id)
    if d is None or d.job_id != job.id:
        raise HTTPException(status_code=404, detail="Disposal not found")
    for k, v in _disposal_fields(body).items():
        setattr(d, k, v)
    db.commit()
    return _cgt_view(db, job)


@router.delete("/jobs/{job_id}/capital-gains/disposals/{disposal_id}")
def delete_disposal(job_id: str, disposal_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SADisposal
    job = _owned(db, request, job_id)
    d = db.get(SADisposal, disposal_id)
    if d is None or d.job_id != job.id:
        raise HTTPException(status_code=404, detail="Disposal not found")
    db.delete(d)
    db.commit()
    return _cgt_view(db, job)


@router.put("/jobs/{job_id}/capital-gains/losses")
def put_capital_losses(job_id: str, body: CapitalIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SACapital
    job = _owned(db, request, job_id)
    cap = db.get(SACapital, job.id)
    if cap is None:
        cap = SACapital(job_id=job.id)
        db.add(cap)
    cap.losses_bf = body.losses_bf
    db.commit()
    return _cgt_view(db, job)


class ShareTradeIn(BaseModel):
    holding: str = Field(..., min_length=1, max_length=255)
    kind: str = Field("LISTED", pattern="^(LISTED|UNLISTED|CRYPTO)$")
    on: date
    side: str = Field(..., pattern="^(BUY|SELL|POOL)$")
    quantity: float = Field(..., gt=0)
    amount: float = Field(..., ge=0)


@router.post("/jobs/{job_id}/capital-gains/trades")
def add_share_trade(job_id: str, body: ShareTradeIn, request: Request, db: Session = Depends(get_db)):
    """A buy, sale or pool brought forward of a holding: sales are matched by the share rules into disposals."""
    from backend.app.sa.models import SAShareTrade
    job = _owned(db, request, job_id)
    db.add(SAShareTrade(job_id=job.id, holding=body.holding.strip(), kind=body.kind, on=body.on.isoformat(), side=body.side,
                        quantity=body.quantity, amount=body.amount))
    db.commit()
    return _cgt_view(db, job)


@router.delete("/jobs/{job_id}/capital-gains/trades/{trade_id}")
def delete_share_trade(job_id: str, trade_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SAShareTrade
    job = _owned(db, request, job_id)
    t = db.get(SAShareTrade, trade_id)
    if t is None or t.job_id != job.id:
        raise HTTPException(status_code=404, detail="Trade not found")
    db.delete(t)
    db.commit()
    return _cgt_view(db, job)
