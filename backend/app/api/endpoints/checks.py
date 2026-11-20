"""The client's checks in the background: where the latest run has got, and a way to start one."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.deps import owned_engagement
from backend.app.core.database import get_db
from backend.app.services.checks import runner

router = APIRouter()


@router.get("/{engagement_id}/checks")
def get_checks(engagement_id: str, request: Request, db: Session = Depends(get_db)):
    owned_engagement(db, request.state.user, engagement_id)
    return runner.latest(db, engagement_id)


@router.post("/{engagement_id}/checks")
def start_checks(engagement_id: str, request: Request, db: Session = Depends(get_db)):
    eng = owned_engagement(db, request.state.user, engagement_id)
    return runner.start(db, eng, "accountant", request.state.user.id)
