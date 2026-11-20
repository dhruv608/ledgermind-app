"""Helpers every Self Assessment route uses: the job as the screen sees it, and the job looked up for its owner."""

import json
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.sa.models import SAJob


def _masked(value: Optional[str]) -> Optional[str]:
    """The last 3 characters only: '•••••••123'."""
    if not value:
        return None
    return "•" * max(len(value) - 3, 0) + value[-3:]


def _out(job: SAJob, db: Session) -> dict:
    from backend.app.models.database import ClientEngagement
    company = db.get(ClientEngagement, job.company_engagement_id) if job.company_engagement_id else None
    return {
        "id": job.id,
        "person_name": job.person_name,
        "tax_year": job.tax_year,
        "sources": json.loads(job.sources or "[]"),
        "first_return": bool(job.first_return),
        "company": {"engagement_id": company.id, "name": company.client_name} if company else None,
        "utr": _masked(job.utr),
        "ni_number": _masked(job.ni_number),
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _owned(db: Session, request: Request, job_id: str) -> SAJob:
    job = db.get(SAJob, job_id)
    if job is None or job.owner_user_id != request.state.user.id:
        raise HTTPException(status_code=404, detail="Self Assessment job not found")
    return job
