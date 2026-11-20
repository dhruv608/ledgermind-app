"""Notes on an area page (under /engagements/{id}): threaded comments, who and when, on the account or on one point."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.area_notes import AreaNote
from backend.app.models.database import AuditFinding, ClientEngagement
from backend.app.models.point_signoffs import initials_of, point_key

router = APIRouter()


class NoteIn(BaseModel):
    area: str
    text: str
    parent_id: Optional[int] = None              # the note this answers
    finding_id: Optional[int] = None             # the point it is about


def _notes(db: Session, engagement_id: str) -> list:
    """Every note of the job, oldest first; a note about a point carries the point's id now (after a re-run, the
    rebuilt point's)."""
    points = {point_key(f.procedure_ref, f.finding_title, f.source_row_ref): f.id
              for f in db.query(AuditFinding).filter(AuditFinding.engagement_id == engagement_id).all()}
    rows = db.query(AreaNote).filter(AreaNote.engagement_id == engagement_id).order_by(AreaNote.id).all()
    return [{"id": n.id, "area": n.area, "parent_id": n.parent_id, "text": n.text, "author": n.author or "",
             "initials": n.initials or "", "user_id": n.user_id,
             "created_at": n.created_at.isoformat() if n.created_at else None,
             "finding_id": points.get(n.point_key) if n.point_key else None, "point_title": n.point_title or ""}
            for n in rows]


def _engagement(db: Session, engagement_id: str) -> ClientEngagement:
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return eng


@router.get("/{engagement_id}/notes")
def get_notes(engagement_id: str, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    return _notes(db, engagement_id)


@router.post("/{engagement_id}/notes")
def add_note(engagement_id: str, payload: NoteIn, request: Request, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Write the note")
    save_note(db, engagement_id, payload.area, payload.text, getattr(request.state, "user", None),
              payload.parent_id, payload.finding_id)
    return _notes(db, engagement_id)


def save_note(db: Session, engagement_id: str, area: str, text: str, user, parent_id: Optional[int] = None,
              finding_id: Optional[int] = None) -> AreaNote:
    """A note signed by the user (also added by the assistant when the user confirms one)."""
    note = AreaNote(engagement_id=engagement_id, area=area[:20], text=text.strip())
    if parent_id:
        parent = db.get(AreaNote, parent_id)
        if not parent or parent.engagement_id != engagement_id:
            raise HTTPException(status_code=404, detail="Note not found")
        # A reply joins the thread of the first note, with its area and point
        note.parent_id = parent.parent_id or parent.id
        note.area, note.point_key, note.point_title = parent.area, parent.point_key, parent.point_title
    elif finding_id:
        f = db.get(AuditFinding, finding_id)
        if not f or f.engagement_id != engagement_id:
            raise HTTPException(status_code=404, detail="Point not found")
        note.point_key = point_key(f.procedure_ref, f.finding_title, f.source_row_ref)
        note.point_title = (f.finding_title or "")[:300]
    name, email = getattr(user, "name", "") or "", getattr(user, "email", "") or ""
    note.user_id, note.author, note.initials = getattr(user, "id", None), (name or email)[:120], initials_of(name, email)
    db.add(note)
    db.commit()
    return note


@router.delete("/{engagement_id}/notes/{note_id}")
def delete_note(engagement_id: str, note_id: int, request: Request, db: Session = Depends(get_db)):
    """A note is removed only by the person who wrote it, with its replies."""
    note = db.get(AreaNote, note_id)
    if not note or note.engagement_id != engagement_id:
        raise HTTPException(status_code=404, detail="Note not found")
    user = getattr(request.state, "user", None)
    if note.user_id is not None and note.user_id != getattr(user, "id", None):
        raise HTTPException(status_code=403, detail="Only the person who wrote a note can remove it")
    db.query(AreaNote).filter(AreaNote.engagement_id == engagement_id, AreaNote.parent_id == note.id).delete()
    db.delete(note)
    db.commit()
    return _notes(db, engagement_id)
