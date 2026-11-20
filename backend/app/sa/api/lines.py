"""Routes for the income lines and the tax calculation, with what feeds it: director dividends, foster care,
payments on account and family."""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.income import KINDS, calculation, director_dividends, sync_p60_lines
from backend.app.sa.models import SAJob, SALine
from backend.app.sa.api.common import _owned


router = APIRouter()


class LineIn(BaseModel):
    source: str
    kind: str
    label: str = Field(default="", max_length=255)
    amount: float = 0
    tax_paid: float = 0
    share: float = 1
    extra: Optional[float] = None
    include: bool = True
    note: Optional[str] = None
    paid_on: Optional[str] = None


class LinePatch(BaseModel):
    label: Optional[str] = None
    amount: Optional[float] = None
    tax_paid: Optional[float] = None
    share: Optional[float] = None
    extra: Optional[float] = None
    include: Optional[bool] = None
    note: Optional[str] = None


def _line_out(l: SALine) -> dict:
    return {"id": l.id, "source": l.source, "kind": l.kind, "label": l.label, "amount": float(l.amount or 0),
            "tax_paid": float(l.tax_paid or 0), "share": float(l.share if l.share is not None else 1),
            "extra": float(l.extra) if l.extra is not None else None, "include": bool(l.include), "doc_id": l.doc_id,
            "auto": bool(l.auto), "note": l.note, "paid_on": l.paid_on}


def _lines(db: Session, job: SAJob) -> list:
    return [_line_out(l) for l in db.query(SALine).filter(SALine.job_id == job.id).order_by(SALine.source, SALine.id).all()]


@router.get("/jobs/{job_id}/lines")
def list_lines(job_id: str, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    sync_p60_lines(db, job)
    return _lines(db, job)


@router.post("/jobs/{job_id}/lines")
def add_line(job_id: str, body: LineIn, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    if body.kind not in KINDS.get(body.source, ()):
        raise HTTPException(status_code=400, detail=f"Not a kind of {body.source}: {body.kind}")
    if not 0 < body.share <= 1:
        raise HTTPException(status_code=400, detail="The share is between 0 and 1 (0.5 for a joint account).")
    db.add(SALine(job_id=job.id, source=body.source, kind=body.kind, label=body.label.strip(), amount=body.amount,
                  tax_paid=body.tax_paid, share=body.share, extra=body.extra,
                  include=0 if body.kind in ("ISA", "SALARY_SACRIFICE") else int(body.include),
                  note=body.note, paid_on=body.paid_on))
    db.commit()
    return _lines(db, job)


@router.patch("/jobs/{job_id}/lines/{line_id}")
def edit_line(job_id: str, line_id: int, body: LinePatch, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    line = db.get(SALine, line_id)
    if line is None or line.job_id != job.id:
        raise HTTPException(status_code=404, detail="Line not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(line, k, int(v) if k == "include" else v)
    db.commit()
    return _lines(db, job)


@router.delete("/jobs/{job_id}/lines/{line_id}")
def delete_line(job_id: str, line_id: int, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    line = db.get(SALine, line_id)
    if line is None or line.job_id != job.id:
        raise HTTPException(status_code=404, detail="Line not found")
    db.delete(line)
    db.commit()
    return _lines(db, job)


@router.get("/jobs/{job_id}/director-dividends")
def get_director_dividends(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Dividends paid in the tax year in the company's books, each marked when already on the return."""
    job = _owned(db, request, job_id)
    on = {(l.paid_on, round(float(l.amount or 0), 2)) for l in
          db.query(SALine).filter(SALine.job_id == job.id, SALine.source == "DIVIDENDS").all()}
    found = director_dividends(db, job)
    for d in found:
        d["added"] = (d["date"], d["amount"]) in on
    return found


@router.post("/jobs/{job_id}/director-dividends")
def add_director_dividends(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Each dividend from the company's books not yet on the return, as a line."""
    job = _owned(db, request, job_id)
    for d in get_director_dividends(job_id, request, db):
        if not d["added"]:
            db.add(SALine(job_id=job.id, source="DIVIDENDS", kind="DIVIDEND", label=d["company"], amount=d["amount"],
                          paid_on=d["date"], note=f"From {d['company']}'s books: {d['description']}"[:500]))
    db.commit()
    return _lines(db, job)


def _calc_view(db: Session, job: SAJob) -> dict:
    from backend.app.sa.models import SAPayments
    out = calculation(db, job)
    paid = db.get(SAPayments, job.id)
    from backend.app.sa.income import CLASS4_KEY, LOSS_KEY
    from backend.app.sa.signals import _answers
    kept = _answers(db, job)
    out["payments"] = {"poa_paid": float(paid.poa_paid or 0) if paid else 0.0,
                       "class2_voluntary": bool(paid.class2_voluntary) if paid else False, "set": paid is not None,
                       "class4_exempt": (kept[CLASS4_KEY].value or "") if CLASS4_KEY in kept else "",
                       "loss_claim": (kept[LOSS_KEY].value or "") if LOSS_KEY in kept else ""}
    return out


@router.get("/jobs/{job_id}/calculation")
def get_calculation(job_id: str, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    sync_p60_lines(db, job)
    return _calc_view(db, job)


# ---- Foster, kinship and shared-lives care (foster.py, R-SP-01) ----

class FosterIn(BaseModel):
    receipts: Optional[float] = Field(None, ge=0, le=10_000_000)
    carers: int = Field(1, ge=1, le=10)
    method: Optional[str] = Field(None, pattern="^(SIMPLIFIED|ACTUAL)$")
    actual_costs: Optional[float] = Field(None, ge=0, le=10_000_000)


class PlacementIn(BaseModel):
    label: str = Field("", max_length=120)
    band: str = Field(..., pattern="^(UNDER_11|ELEVEN_PLUS|ADULT)$")
    weeks: int = Field(..., ge=1, le=53)


def _foster_view(db: Session, job: SAJob) -> dict:
    from backend.app.sa.foster import for_job
    return for_job(db, job)


@router.get("/jobs/{job_id}/foster")
def get_foster(job_id: str, request: Request, db: Session = Depends(get_db)):
    return _foster_view(db, _owned(db, request, job_id))


@router.put("/jobs/{job_id}/foster")
def put_foster(job_id: str, body: FosterIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SAFosterYear
    job = _owned(db, request, job_id)
    row = db.get(SAFosterYear, job.id) or SAFosterYear(job_id=job.id)
    row.receipts, row.carers, row.method, row.actual_costs = body.receipts, body.carers, body.method, body.actual_costs
    db.add(row)
    db.commit()
    return _foster_view(db, job)


@router.post("/jobs/{job_id}/foster/placements")
def add_placement(job_id: str, body: PlacementIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SAFosterPlacement
    job = _owned(db, request, job_id)
    db.add(SAFosterPlacement(job_id=job.id, label=body.label.strip(), band=body.band, weeks=body.weeks))
    db.commit()
    return _foster_view(db, job)


@router.delete("/jobs/{job_id}/foster/placements/{placement_id}")
def delete_placement(job_id: str, placement_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SAFosterPlacement
    job = _owned(db, request, job_id)
    db.query(SAFosterPlacement).filter(SAFosterPlacement.job_id == job.id, SAFosterPlacement.id == placement_id).delete()
    db.commit()
    return _foster_view(db, job)


class PaymentsIn(BaseModel):
    poa_paid: float = Field(0, ge=0, le=10_000_000)
    class2_voluntary: bool = False
    class4_exempt: Optional[str] = Field(None, max_length=20)     # PENSION_AGE / UNDER_16 / NON_RESIDENT, "" none
    loss_claim: Optional[str] = Field(None, max_length=20)        # CURRENT / PRIOR / CARRY_FORWARD, "" not chosen


@router.put("/jobs/{job_id}/payments")
def put_payments(job_id: str, body: PaymentsIn, request: Request, db: Session = Depends(get_db)):
    """Payments on account already made for the year (R-FAM-03) and the voluntary Class 2 choice (R-NIC-01)."""
    from backend.app.sa.models import SAPayments
    job = _owned(db, request, job_id)
    row = db.get(SAPayments, job.id) or SAPayments(job_id=job.id)
    row.poa_paid, row.class2_voluntary = round(body.poa_paid, 2), int(body.class2_voluntary)
    db.add(row)
    db.commit()
    from backend.app.sa import signals
    from backend.app.sa.income import CLASS4_CHOICES, CLASS4_KEY, LOSS_CLAIMS, LOSS_KEY
    for key, value, allowed in ((CLASS4_KEY, body.class4_exempt, CLASS4_CHOICES), (LOSS_KEY, body.loss_claim, LOSS_CLAIMS)):
        if value is None:
            continue                     # not sent: kept as it was
        if value and value not in allowed:
            raise HTTPException(status_code=400, detail="Unknown choice")
        signals.answer(db, job, key, value or None)
    return _calc_view(db, job)


class FamilyIn(BaseModel):
    child_benefit: Optional[float] = Field(None, ge=0)
    children: Optional[int] = Field(None, ge=0, le=20)
    cb_stopped: Optional[date] = None
    higher_income: Optional[str] = Field(None, pattern="^(ME|PARTNER)$")
    marriage: Optional[str] = Field(None, pattern="^(TRANSFERRED|RECEIVED)$")
    spouse_name: Optional[str] = Field(None, max_length=255)
    loan_plans: List[str] = []
    postgraduate: bool = False
    studying: bool = False
    sl_deducted: Optional[float] = Field(None, ge=0)
    pgl_deducted: Optional[float] = Field(None, ge=0)


@router.get("/jobs/{job_id}/family")
def get_family(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Child Benefit, Marriage Allowance and student loans: the facts, what they do to the tax, what is still to ask."""
    from backend.app.sa import family
    return family.view(db, _owned(db, request, job_id))


@router.put("/jobs/{job_id}/family")
def put_family(job_id: str, body: FamilyIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import family
    job = _owned(db, request, job_id)
    unknown = [p for p in body.loan_plans if p not in family.PLANS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown loan plan: {', '.join(unknown)}")
    data = body.model_dump()
    data["cb_stopped"] = body.cb_stopped.isoformat() if body.cb_stopped else None
    data["spouse_name"] = (body.spouse_name or "").strip() or None
    family.save(db, job, data)
    return family.view(db, job)
