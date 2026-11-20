"""GL scrutiny (Accounts tab): the ledger one code at a time, each line marked OK or moved to another code by a
proposed journal (under /engagements/{id})."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement
from backend.app.services.papers import scrutiny
from backend.app.services.shared.activity import mark_changed

router = APIRouter()


def _engagement(db: Session, engagement_id: str) -> ClientEngagement:
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return eng


@router.get("/{engagement_id}/scrutiny")
def scrutiny_accounts(engagement_id: str, db: Session = Depends(get_db)):
    """Each code with ledger lines: its total and how many lines are checked."""
    return scrutiny.accounts(_engagement(db, engagement_id), db)


@router.get("/{engagement_id}/scrutiny/lines")
def scrutiny_lines(engagement_id: str, code: str, db: Session = Depends(get_db)):
    """One code's ledger lines ("none": lines whose account matches no TB account)."""
    if code != scrutiny.NOT_MATCHED and not code.isdigit():
        raise HTTPException(status_code=400, detail="Unknown code")
    return scrutiny.lines(_engagement(db, engagement_id), db, code)


class CheckRequest(BaseModel):
    keys: List[str]
    ok: bool = True


@router.get("/{engagement_id}/ledger-views")
def ledger_views(engagement_id: str, code: int, db: Session = Depends(get_db)):
    """One code's ledger as originally uploaded, as it is now, the lines moved off and onto it, and its journals."""
    from backend.app.services.papers.ledger_views import views
    return views(_engagement(db, engagement_id), db, code)


@router.get("/{engagement_id}/point-ledger/{finding_id}")
def point_ledger(engagement_id: str, finding_id: int, db: Session = Depends(get_db)):
    """The ledger of the contacts a duplicates point is about: each bill, payment and direct payment."""
    from backend.app.models.database import AuditFinding
    from backend.app.services.sop.duplicates import contact_ledger, point_contacts
    eng = _engagement(db, engagement_id)
    f = db.get(AuditFinding, finding_id)
    if f is None or str(f.engagement_id) != str(eng.id):
        raise HTTPException(status_code=404, detail="Point not found")
    return contact_ledger(str(eng.id), point_contacts(f.source_row_ref, f.finding_details), db)


@router.post("/{engagement_id}/scrutiny/check")
def scrutiny_check(engagement_id: str, body: CheckRequest, request: Request, db: Session = Depends(get_db)):
    """Marks lines OK, or takes the OK off (ok=false)."""
    changed = scrutiny.set_ok(_engagement(db, engagement_id), db, body.keys, body.ok, request.state.user.id)
    return {"changed": changed}


class MoveRequest(BaseModel):
    key: str
    to_code: int


@router.post("/{engagement_id}/scrutiny/move")
def scrutiny_move(engagement_id: str, body: MoveRequest, request: Request, db: Session = Depends(get_db)):
    """Proposes a journal moving one line to another code (approved on the Journals tab like any journal)."""
    eng = _engagement(db, engagement_id)
    try:
        out = scrutiny.move(eng, db, body.key, body.to_code, request.state.user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    mark_changed(db, engagement_id)
    return out


class UndoRequest(BaseModel):
    key: str


@router.post("/{engagement_id}/scrutiny/undo-move")
def scrutiny_undo_move(engagement_id: str, body: UndoRequest, db: Session = Depends(get_db)):
    """Takes a move back: its journal is deleted (only while not approved)."""
    try:
        scrutiny.undo_move(_engagement(db, engagement_id), db, body.key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    mark_changed(db, engagement_id)
    return {"status": "SUCCESS"}


class AskRequest(BaseModel):
    key: str
    question: str = ""


@router.post("/{engagement_id}/scrutiny/ask")
def scrutiny_ask(engagement_id: str, body: AskRequest, request: Request, db: Session = Depends(get_db)):
    """Saves a question to the client about one line (a query on the Queries tab); an empty question takes it off."""
    try:
        scrutiny.ask(_engagement(db, engagement_id), db, body.key, body.question, request.state.user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "SUCCESS"}
