"""Routes for the jobs themselves: the options, the list and its status, making, opening and deleting a job."""

import json
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.deps import owned_engagement
from backend.app.core.database import get_db
from backend.app.sa.models import (SOURCES, TAX_YEARS, SADocument, SAJob, SALine, SAProperty, SAPropertyItem,
                                   SABusiness, SABusinessItem)
from backend.app.sa.api.common import _out, _owned


router = APIRouter()


class NewJob(BaseModel):
    person_name: str = Field(min_length=1, max_length=255)
    tax_year: str = TAX_YEARS[0]
    sources: List[str] = []
    first_return: bool = False
    company_engagement_id: Optional[str] = None
    utr: Optional[str] = None
    ni_number: Optional[str] = None


@router.get("/options")
def options():
    return {"tax_years": list(TAX_YEARS), "sources": list(SOURCES)}


@router.get("/jobs")
def list_jobs(request: Request, db: Session = Depends(get_db)):
    jobs = (db.query(SAJob).filter(SAJob.owner_user_id == request.state.user.id)
            .order_by(SAJob.person_name, SAJob.tax_year.desc()).all())
    return [_out(j, db) for j in jobs]


@router.get("/jobs/status")
def jobs_status(request: Request, db: Session = Depends(get_db)):
    """Where each return stands, for the home page: open blocks, open client queries (and the message asking them) and
    decisions, documents, whether the newest pack is final, and when it was last worked on. A return that cannot be worked out shows no counts."""
    from sqlalchemy import func
    from backend.app.sa.models import SAPack
    from backend.app.sa.queries import client_text, queries
    jobs = db.query(SAJob).filter(SAJob.owner_user_id == request.state.user.id).all()
    ids = [j.id for j in jobs]
    docs = dict(db.query(SADocument.job_id, func.count(SADocument.id)).filter(SADocument.job_id.in_(ids))
                .group_by(SADocument.job_id).all()) if ids else {}
    last_doc = dict(db.query(SADocument.job_id, func.max(SADocument.created_at)).filter(SADocument.job_id.in_(ids))
                    .group_by(SADocument.job_id).all()) if ids else {}
    out = {}
    for j in jobs:
        latest = db.query(SAPack).filter(SAPack.job_id == j.id).order_by(SAPack.version.desc()).first()
        try:
            q = queries(db, j) if docs.get(j.id) else None
        except Exception:
            q = None
        counts = q["counts"] if q else None
        times = [t for t in (j.updated_at, j.created_at, last_doc.get(j.id), latest.created_at if latest else None) if t]
        out[j.id] = {"documents": docs.get(j.id, 0), "final": bool(latest and latest.kind == "FINAL"),
                     "blocks": counts["blocks"] if counts else None, "client": counts["client"] if counts else None,
                     "decisions": counts["decisions"] if counts else None,
                     # The open client queries as one message to send (the Queries page's own wording)
                     "message": client_text(q, j.person_name, j.tax_year) if counts and counts["client"] else None,
                     "last_activity_at": max(times).isoformat() if times else None}
    return out


@router.post("/jobs")
def create_job(body: NewJob, request: Request, db: Session = Depends(get_db)):
    name = body.person_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Enter the person's name.")
    if body.tax_year not in TAX_YEARS:
        raise HTTPException(status_code=400, detail=f"Tax year must be one of {', '.join(TAX_YEARS)}.")
    unknown = [s for s in body.sources if s not in SOURCES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown kind of income: {', '.join(unknown)}.")
    if body.company_engagement_id:
        owned_engagement(db, request.state.user, body.company_engagement_id)
    utr = re.sub(r"\s", "", body.utr or "") or None
    if utr and not re.fullmatch(r"\d{10}", utr):
        raise HTTPException(status_code=400, detail="A UTR is 10 digits.")
    ni = re.sub(r"\s", "", body.ni_number or "").upper() or None
    if ni and not re.fullmatch(r"[A-Z]{2}\d{6}[A-D]", ni):
        raise HTTPException(status_code=400, detail="A National Insurance number looks like QQ123456C.")
    dup = db.query(SAJob).filter(SAJob.owner_user_id == request.state.user.id, SAJob.tax_year == body.tax_year,
                                 SAJob.person_name.ilike(name)).first()
    if dup is not None:
        raise HTTPException(status_code=409, detail=f"{name} already has a {body.tax_year} return.")
    job = SAJob(owner_user_id=request.state.user.id, person_name=name, tax_year=body.tax_year,
                sources=json.dumps([s for s in SOURCES if s in body.sources]), first_return=int(body.first_return),
                company_engagement_id=body.company_engagement_id or None, utr=utr, ni_number=ni)
    db.add(job)
    db.commit()
    db.refresh(job)
    return _out(job, db)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    return _out(_owned(db, request, job_id), db)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    from backend.app.core.s3 import s3_service
    job = _owned(db, request, job_id)
    db.query(SADocument).filter(SADocument.job_id == job.id).delete(synchronize_session=False)
    db.query(SALine).filter(SALine.job_id == job.id).delete(synchronize_session=False)
    db.query(SAPropertyItem).filter(SAPropertyItem.job_id == job.id).delete(synchronize_session=False)
    db.query(SAProperty).filter(SAProperty.job_id == job.id).delete(synchronize_session=False)
    db.query(SABusinessItem).filter(SABusinessItem.job_id == job.id).delete(synchronize_session=False)
    from backend.app.sa.models import SAAllowance
    db.query(SAAllowance).filter(SAAllowance.job_id == job.id).delete(synchronize_session=False)
    db.query(SABusiness).filter(SABusiness.job_id == job.id).delete(synchronize_session=False)
    from backend.app.sa.models import SAAnswer, SABankChoice, SACapital, SADisposal, SAExpect, SAFamily, SAPack
    db.query(SAPack).filter(SAPack.job_id == job.id).delete(synchronize_session=False)
    db.query(SADisposal).filter(SADisposal.job_id == job.id).delete(synchronize_session=False)
    db.query(SACapital).filter(SACapital.job_id == job.id).delete(synchronize_session=False)
    from backend.app.sa.models import SAForeign
    db.query(SAForeign).filter(SAForeign.job_id == job.id).delete(synchronize_session=False)
    from backend.app.sa.models import SAShareTrade
    db.query(SAShareTrade).filter(SAShareTrade.job_id == job.id).delete(synchronize_session=False)
    db.query(SAFamily).filter(SAFamily.job_id == job.id).delete(synchronize_session=False)
    from backend.app.sa.models import SAFosterPlacement, SAFosterYear, SAPayments, SAReading
    db.query(SAPayments).filter(SAPayments.job_id == job.id).delete(synchronize_session=False)
    db.query(SAReading).filter(SAReading.job_id == job.id).delete(synchronize_session=False)
    db.query(SAFosterYear).filter(SAFosterYear.job_id == job.id).delete(synchronize_session=False)
    db.query(SAFosterPlacement).filter(SAFosterPlacement.job_id == job.id).delete(synchronize_session=False)
    db.query(SAExpect).filter(SAExpect.job_id == job.id).delete(synchronize_session=False)
    db.query(SAAnswer).filter(SAAnswer.job_id == job.id).delete(synchronize_session=False)
    db.query(SABankChoice).filter(SABankChoice.job_id == job.id).delete(synchronize_session=False)
    db.delete(job)
    db.commit()
    s3_service.delete_prefix(f"sa_uploads/{job_id}/")
    return {"deleted": job_id}
