"""CIS: the cash basis, the HMRC figures per tax month and the tests T1-T10 (under /engagements/{id})."""

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement
from backend.app.services.shared.activity import mark_changed

router = APIRouter()

def _cis_setup(eng: ClientEngagement) -> Dict[str, Any]:
    profile = getattr(eng, "profile", None)
    return (json.loads(profile.setup or "{}").get("cis") or {}) if profile is not None and profile.setup else {}


@router.get("/{engagement_id}/cis/hmrc")
def cis_hmrc_screen(engagement_id: str, db: Session = Depends(get_db)):
    """The HMRC CIS input screen: one row per tax month, the books on a cash basis beside it."""
    from backend.app.services.cis.hmrc import hmrc_screen
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return hmrc_screen(eng, db, _cis_setup(eng))


@router.get("/{engagement_id}/cis/checks")
def cis_checks_endpoint(engagement_id: str, db: Session = Depends(get_db)):
    """The CIS tests T1-T10: books on a cash basis against HMRC per tax month, with the timing items."""
    from backend.app.services.cis.checks import cis_checks
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    try:
        return cis_checks(eng, db, _cis_setup(eng))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"The CIS checks could not be worked out: {str(e)[:200]}")


@router.post("/{engagement_id}/cis/hmrc")
def save_cis_hmrc(engagement_id: str, body: Dict[str, Any], request: Request, db: Session = Depends(get_db)):
    """Saves the HMRC figures typed per tax month (CIS300, statements / EPS, PAYE and the HMRC account)."""
    from backend.app.services.cis.hmrc import hmrc_screen, save_hmrc
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    try:
        save_hmrc(db, eng, body, getattr(getattr(request.state, "user", None), "id", None))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    mark_changed(db, engagement_id)
    return hmrc_screen(eng, db, _cis_setup(eng))
