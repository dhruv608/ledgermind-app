"""The Books tab (clients with no accounting software): the books worked out from the bank statement and Dext lists,
the accountant's choices on them, and the trial balance the rest of the app reads."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement
from backend.app.services.bank_only import books as raw_books
from backend.app.services.shared.activity import mark_changed

router = APIRouter()


class ChoiceRequest(BaseModel):
    key: str                    # "bank:40", "bill:12", "confirm:bank:40", "answer:bank:40"
    value: Optional[Any] = None  # {"head": ...} or {"code": 3290}, {"confirmed": true}, {"text": ...}; null to undo


def _books_client(engagement_id: str, db: Session) -> ClientEngagement:
    eng = db.get(ClientEngagement, engagement_id)
    if eng is None or not raw_books.is_books_client(eng):
        raise HTTPException(status_code=404, detail="This client's books are not prepared in the app")
    return eng


def upload_books_client(request: Request, files_data, chosen, db: Session, year_end=None):
    """New client (or the same client and year again) from a bank statement and Dext lists: the client is saved,
    its files kept, and a first trial balance made from the books so every tab has something to show."""
    import json
    from sqlalchemy import delete
    from backend.app.core.s3 import s3_service
    from backend.app.models.database import AuditFinding, GLTransaction, TBRecord
    from backend.app.models.schemas import IngestionResponse, TBRecordSchema
    from backend.app.services.bank_only import input_files as raw_input
    from backend.app.services.ingestion.client_identity import find_engagement
    from backend.app.api.endpoints.upload import _stored_name

    roles = {k: v for k, v in (chosen or {}).items() if v in raw_input.RAW_ROLES or v == raw_input.SKIP}
    raw = raw_input.read_input_files(files_data, roles, year_end=year_end)
    blocking = [p.text for p in raw.problems if p.severity == "HIGH" and p.where in ("Bank", "Files") and p.blocks_upload]
    if raw.year_end is None:
        # Statements rarely say the year end: the upload screen asks for it and sends the files again
        raise HTTPException(status_code=422, detail={"message": "Bank statements do not say the client's year end: enter it.",
                                                     "need": "year_end"})
    if blocking:
        raise HTTPException(status_code=400, detail=" ".join(blocking))
    name = raw.client_name or files_data[0][0].rsplit(".", 1)[0]

    owner_id = request.state.user.id
    eng = find_engagement(db, name, raw.year_end, owner_id)
    if eng is not None:
        # The same client and year uploaded again: its earlier books, choices and review points are replaced
        eng.source_system = raw_books.SOURCE_SYSTEM
        for model in (GLTransaction, AuditFinding, TBRecord):
            db.execute(delete(model).where(model.engagement_id == eng.id))
        raw_books.clear_choices(db, eng.id)
    else:
        eng = ClientEngagement(client_name=name, period_end_date=raw.year_end, source_system=raw_books.SOURCE_SYSTEM,
                               owner_user_id=owner_id)
        db.add(eng)
    db.commit()

    # The files, with what each file or tab was taken as
    prefix = f"raw_uploads/{eng.id}/"
    taken = {p["filename"]: roles.get(p["filename"], p["role"]) for p in raw_input.identify_parts(files_data)}
    s3_service.delete_prefix(prefix)
    for fname, fbytes in files_data:
        s3_service.upload_file_bytes(fbytes, prefix + _stored_name(fname))
    s3_service.upload_file_bytes(json.dumps(taken).encode(), prefix + raw_books.ROLES_FILE)

    raw_books.look_up_register(eng, db)
    try:
        raw_books.make_trial_balance(eng, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    mark_changed(db, eng.id)
    tb = db.query(TBRecord).filter(TBRecord.engagement_id == eng.id).all()
    return IngestionResponse(
        engagement_id=eng.id, client_name=eng.client_name, period_end_date=eng.period_end_date.strftime("%d/%m/%Y"),
        source_system=eng.source_system, total_tb_rows=len(tb),
        total_gl_rows=db.query(GLTransaction).filter(GLTransaction.engagement_id == eng.id).count(),
        tb_net_balance=round(sum(float(t.net_amount or 0) for t in tb), 2), tb_records=[TBRecordSchema.model_validate(t) for t in tb],
    )


@router.get("/{engagement_id}")
def get_books(engagement_id: str, db: Session = Depends(get_db)):
    eng = _books_client(engagement_id, db)
    try:
        return raw_books.books(eng, db)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"The client's files could not be read: {str(e)[:200]}")


@router.post("/{engagement_id}/choice")
def save_choice(engagement_id: str, payload: ChoiceRequest, request: Request, db: Session = Depends(get_db)):
    _books_client(engagement_id, db)
    kind = payload.key.split(":", 1)[0]
    if kind not in ("bank", "bill", "confirm", "answer", "payee", "opening"):
        raise HTTPException(status_code=400, detail="Unknown choice")
    if kind == "opening" and payload.value is not None and (
            payload.value.get("code") is None or raw_books.resolve(payload.value, raw_books.firm_chart(db)) is None):
        raise HTTPException(status_code=400, detail="Choose a code of the chart")
    if kind in ("bank", "bill", "payee") and payload.value is not None and (
            raw_books.resolve(payload.value, raw_books.firm_chart(db)) is None
            or (payload.value.get("code") is None and payload.value.get("head") not in raw_books.CHOICES)):
        raise HTTPException(status_code=400, detail="Choose one of the listed types")
    raw_books.save_choice(db, engagement_id, payload.key, payload.value, request.state.user.id)
    return {"status": "saved"}


@router.post("/{engagement_id}/ai-suggest")
def ai_suggest(engagement_id: str, db: Session = Depends(get_db)):
    """The AI's suggested code for each payee no rule could sort (shown on the lines, applied only by a click)."""
    from backend.app.services.bank_only.ai_suggest import suggest
    return suggest(_books_client(engagement_id, db), db)


@router.post("/{engagement_id}/trial-balance")
def make_trial_balance(engagement_id: str, db: Session = Depends(get_db)):
    eng = _books_client(engagement_id, db)
    try:
        out = raw_books.make_trial_balance(eng, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    mark_changed(db, engagement_id)
    return out
