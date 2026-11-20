"""The job's own details (under /engagements/{id}), as on the Create Workpaper form: the first and last day in
the pack, the job's start and due dates, who it is assigned to, who manages it and the partner. Kept in the client
setup's "job" part; saving them changes no figure, so no check runs."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement
from backend.app.services.setup.profile_service import ProfileService

router = APIRouter()
FIELDS = ("first_day", "last_day", "start_date", "due_date", "assigned_to", "managed_by", "partner")


class JobDetails(BaseModel):
    first_day: Optional[str] = None        # yyyy-mm-dd
    last_day: Optional[str] = None
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    assigned_to: Optional[str] = None
    managed_by: Optional[str] = None
    partner: Optional[str] = None


def _job(profile) -> dict:
    return (json.loads(profile.setup or "{}") or {}).get("job") or {}


@router.get("/{engagement_id}/job-details")
def get_job_details(engagement_id: str, db: Session = Depends(get_db)):
    if not db.get(ClientEngagement, engagement_id):
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return {k: _job(ProfileService.get_or_create_profile(db, engagement_id)).get(k) for k in FIELDS}


@router.put("/{engagement_id}/job-details")
def save_job_details(engagement_id: str, body: JobDetails, db: Session = Depends(get_db)):
    if not db.get(ClientEngagement, engagement_id):
        raise HTTPException(status_code=404, detail="Client engagement not found")
    profile = ProfileService.get_or_create_profile(db, engagement_id)
    setup = json.loads(profile.setup or "{}") or {}
    setup["job"] = {k: (v.strip()[:120] if isinstance(v, str) and v.strip() else None) for k, v in body.model_dump().items()}
    profile.setup = json.dumps(setup)
    db.commit()
    return setup["job"]
