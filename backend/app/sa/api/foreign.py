"""Routes for foreign income."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.income import calculation
from backend.app.sa.models import SAJob
from backend.app.sa.api.common import _owned


router = APIRouter()


class ForeignIn(BaseModel):
    country: str = Field(..., pattern="^[A-Z]{3}$")
    kind: str = Field("INTEREST", pattern="^(INTEREST|DIVIDEND|PENSION|BENEFIT|OTHER)$")
    payer: str = Field("", max_length=255)
    amount: float = Field(0, ge=0)
    foreign_tax: float = Field(0, ge=0)
    share: float = Field(1, gt=0, le=1)
    claim: bool = True
    note: Optional[str] = Field(None, max_length=2000)


def _foreign_view(db: Session, job: SAJob) -> dict:
    from backend.app.sa import foreign
    calc = calculation(db, job)
    rows = calc["foreign"]
    return {"rows": rows, "credit": calc["calculation"]["reductions"].get("foreign_tax_credit", 0.0),
            "issues": [i for r in rows for i in r["issues"]], "notes": [n for r in rows for n in r["notes"]],
            "kinds": [{"kind": k, "label": v} for k, v in foreign.KINDS.items()],
            "countries": [{"code": k, "name": v} for k, v in sorted(foreign.TABLE["names"].items(), key=lambda x: x[1])],
            "treaties": foreign.TABLE["rows"]}


@router.get("/jobs/{job_id}/foreign")
def get_foreign(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Each foreign source with its foreign tax, the treaty and the credit."""
    return _foreign_view(db, _owned(db, request, job_id))


@router.post("/jobs/{job_id}/foreign")
def add_foreign(job_id: str, body: ForeignIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SAForeign
    job = _owned(db, request, job_id)
    db.add(SAForeign(job_id=job.id, **{**body.model_dump(), "claim": int(body.claim), "payer": body.payer.strip()}))
    db.commit()
    return _foreign_view(db, job)


@router.put("/jobs/{job_id}/foreign/{row_id}")
def edit_foreign(job_id: str, row_id: int, body: ForeignIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SAForeign
    job = _owned(db, request, job_id)
    f = db.get(SAForeign, row_id)
    if f is None or f.job_id != job.id:
        raise HTTPException(status_code=404, detail="Foreign source not found")
    for k, v in {**body.model_dump(), "claim": int(body.claim), "payer": body.payer.strip()}.items():
        setattr(f, k, v)
    db.commit()
    return _foreign_view(db, job)


@router.delete("/jobs/{job_id}/foreign/{row_id}")
def delete_foreign(job_id: str, row_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.models import SAForeign
    job = _owned(db, request, job_id)
    f = db.get(SAForeign, row_id)
    if f is None or f.job_id != job.id:
        raise HTTPException(status_code=404, detail="Foreign source not found")
    db.delete(f)
    db.commit()
    return _foreign_view(db, job)
