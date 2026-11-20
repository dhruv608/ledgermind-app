"""The assistant's chat panel (under /assistant): the user's chats (per client, newest first), one chat's messages,
and a new message answered as a stream of events (Server-Sent Events)."""

import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.deps import assistant_user as current_user, owned_engagement
from backend.app.core.database import SessionLocal, get_db
from backend.app.models.chat import ChatFile, ChatMessage, ChatSession, ChatUpload
from backend.app.models.database import ClientEngagement, User

logger = logging.getLogger(__name__)

router = APIRouter()


def _own_chat(db: Session, user: User, session_id: str) -> ChatSession:
    chat = db.get(ChatSession, session_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


TEST_MAX_CHARS = 6000


def _within_limit(db: Session, user: User) -> None:
    """The test page stops for the day once its AI spend reaches the limit."""
    from backend.app.core.config import settings
    from backend.app.services.assistant import chat_access
    if chat_access.over_limit(db, user):
        raise HTTPException(status_code=429, detail=f"Today's test limit of ${settings.CHAT_DAILY_LIMIT_USD:.2f} "
                                                    "is used up. It starts again tomorrow (UK time, midnight UTC).")


def _chat_json(c: ChatSession, client_name: Optional[str] = None):
    return {"id": c.id, "title": c.title, "engagement_id": c.engagement_id, "client_name": client_name,
            "updated_at": c.updated_at.isoformat() + "Z" if c.updated_at else None,
            "cost_usd": float(c.cost_usd or 0), "tokens_in": int(c.tokens_in or 0), "tokens_out": int(c.tokens_out or 0)}


@router.get("/sessions")
def list_chats(request: Request, engagement_id: Optional[str] = None, q: str = "", all_clients: bool = False,
               db: Session = Depends(get_db)):
    """The user's chats, newest first: this client's (or those with no client), or every client's."""
    user = current_user(request, db)
    stmt = (select(ChatSession, ClientEngagement.client_name)
            .join(ClientEngagement, ClientEngagement.id == ChatSession.engagement_id, isouter=True)
            .where(ChatSession.user_id == user.id))
    if not all_clients:
        stmt = stmt.where(ChatSession.engagement_id == engagement_id if engagement_id else ChatSession.engagement_id.is_(None))
    if q.strip():
        like = f"%{q.strip()}%"
        in_messages = select(ChatMessage.session_id).where(ChatMessage.content.ilike(like))
        stmt = stmt.where(ChatSession.title.ilike(like) | ChatSession.id.in_(in_messages))
    rows = db.execute(stmt.order_by(ChatSession.updated_at.desc()).limit(100)).all()
    return [_chat_json(c, name) for c, name in rows]


class NewChat(BaseModel):
    engagement_id: Optional[str] = None


@router.post("/sessions")
def new_chat(body: NewChat, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if body.engagement_id:
        owned_engagement(db, user, body.engagement_id)
    chat = ChatSession(user_id=user.id, engagement_id=body.engagement_id or None)
    db.add(chat)
    db.commit()
    return _chat_json(chat)


@router.get("/sessions/{session_id}")
def get_chat(session_id: str, request: Request, db: Session = Depends(get_db)):
    from backend.app.services.assistant.chat import message_json
    user = current_user(request, db)
    chat = _own_chat(db, user, session_id)
    msgs = db.execute(select(ChatMessage).where(ChatMessage.session_id == chat.id).order_by(ChatMessage.id)).scalars()
    return {**_chat_json(chat), "messages": [message_json(m) for m in msgs]}


@router.delete("/sessions/{session_id}")
def delete_chat(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    chat = _own_chat(db, user, session_id)
    delete_chat_files(db, [chat.id])
    delete_uploads(db, user, session_id=chat.id)
    db.query(ChatMessage).filter(ChatMessage.session_id == chat.id).delete()
    db.delete(chat)
    db.commit()
    return {"deleted": session_id}


class NewMessage(BaseModel):
    text: str
    context: Optional[dict] = None          # the page the user is on: {"tab": "area", "area": "vat"}
    files: List[str] = []                   # files attached to the question (uploaded first, up to 5)


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, body: NewMessage, request: Request, db: Session = Depends(get_db)):
    """The answer as Server-Sent Events: status (a step), delta (text), reset, done (the saved message), error."""
    from backend.app.services.assistant import chat_access
    user = current_user(request, db)
    _own_chat(db, user, session_id)
    _within_limit(db, user)
    from backend.app.services.assistant.uploads import MAX_FILES
    text = body.text.strip()
    if chat_access.is_tester(user) and len(text) > TEST_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"Up to {TEST_MAX_CHARS:,} characters a question on the test page")
    if len(body.files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Up to {MAX_FILES} files with a question")
    for fid in body.files:
        u = db.get(ChatUpload, fid)
        if u is None or u.user_id != user.id:
            raise HTTPException(status_code=404, detail="An attached file was not found: add it again")
    if not text and not body.files:
        raise HTTPException(status_code=400, detail="Type a question")
    text = text or "Please read the attached file(s) and tell me what they show."

    def events():
        from backend.app.services.assistant.chat import answer
        # Its own database session: the request's is closed while the answer is still streaming
        own = SessionLocal()
        try:
            chat = own.get(ChatSession, session_id)
            for ev in answer(own, chat, text, body.context or {}, body.files):
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception as e:
            own.rollback()
            yield f"data: {json.dumps({'type': 'error', 'text': f'Something went wrong: {str(e)[:200]}'})}\n\n"
        finally:
            own.close()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ActionDecision(BaseModel):
    decision: str                           # CONFIRM or CANCEL


@router.post("/messages/{message_id}/actions/{action_id}")
def decide_action(message_id: int, action_id: str, body: ActionDecision, request: Request, db: Session = Depends(get_db)):
    """The user's Confirm or Cancel on work the assistant prepared: only now is it done (checked again first)."""
    from backend.app.services.assistant import actions
    from backend.app.services.assistant.chat import message_json
    user = current_user(request, db)
    msg = db.get(ChatMessage, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    chat = _own_chat(db, user, msg.session_id)
    extras = json.loads(msg.suggestions or "{}")
    card = next((c for c in extras.get("actions") or [] if c.get("id") == action_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if card.get("status") != "WAITING":
        raise HTTPException(status_code=400, detail="This has already been decided")
    if body.decision.upper() == "CONFIRM":
        eng = owned_engagement(db, user, chat.engagement_id) if chat.engagement_id else None
        if eng is None:
            raise HTTPException(status_code=400, detail="This chat has no client")
        try:
            card["result"], card["status"] = actions.run(db, eng, card, user), "DONE"
        except ValueError as e:
            db.rollback()
            card["result"], card["status"] = str(e), "FAILED"
    else:
        card["status"] = "CANCELLED"
    card["decided_by"] = getattr(user, "name", "") or getattr(user, "email", "")
    card["decided_at"] = datetime.utcnow().isoformat() + "Z"
    msg = db.get(ChatMessage, message_id)
    msg.suggestions = json.dumps(extras)
    db.commit()
    return message_json(msg)


@router.get("/usage")
def usage(request: Request, db: Session = Depends(get_db)):
    """The user's assistant cost this month and in total (estimated, US$)."""
    user = current_user(request, db)
    start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    mine = select(ChatSession.id).where(ChatSession.user_id == user.id)
    month = db.execute(select(func.coalesce(func.sum(ChatMessage.cost_usd), 0), func.count(ChatMessage.id))
                       .where(ChatMessage.session_id.in_(mine), ChatMessage.role == "assistant",
                              ChatMessage.created_at >= start)).one()
    total = db.execute(select(func.coalesce(func.sum(ChatSession.cost_usd), 0)).where(ChatSession.user_id == user.id)).scalar()
    return {"month_usd": round(float(month[0]), 4), "month_answers": int(month[1]), "total_usd": round(float(total), 4)}


@router.get("/meter")
def meter(request: Request, session_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Tokens and cost (US$, at AWS's London prices) today, this month and ever, and of one chat; the test page's
    daily limit. Answers, voice questions and files read all count."""
    from backend.app.core import ai_usage
    from backend.app.core.config import settings
    from backend.app.services.assistant import chat_access, voice
    user = current_user(request, db)
    today = chat_access.today_start()
    out = {"today": chat_access.spend(db, user, today), "month": chat_access.spend(db, user, today.replace(day=1)),
           "total": chat_access.spend(db, user),
           "limit_usd": settings.CHAT_DAILY_LIMIT_USD if chat_access.is_tester(user) else None,
           "model": settings.ASSISTANT_MODEL,
           "prices": {m: {"in": p[0], "out": p[1]} for m, p in ai_usage.PRICES.items()
                      if m in (settings.ASSISTANT_MODEL, settings.ASSISTANT_BACKUP_MODEL)},
           "voice_per_minute": round(ai_usage.TRANSCRIBE_PER_SECOND * 60 * len(voice.LANGUAGES), 4)}
    if session_id:
        c = _own_chat(db, user, session_id)
        out["chat"] = {"tokens_in": int(c.tokens_in or 0), "tokens_out": int(c.tokens_out or 0),
                       "usd": float(c.cost_usd or 0)}
    return out


def delete_chat_files(db: Session, session_ids) -> None:
    """The files the assistant made in these chats: their rows and the stored files."""
    from backend.app.core.s3 import S3Service
    rows = db.query(ChatFile).filter(ChatFile.session_id.in_(list(session_ids))).all()
    if not rows:
        return
    storage = S3Service()
    for sid in {r.session_id for r in rows}:
        try:
            storage.delete_prefix(f"assistant/{sid}/")
        except Exception:
            logger.warning("The assistant's files of chat %s could not be deleted", sid, exc_info=True)
    db.query(ChatFile).filter(ChatFile.session_id.in_(list(session_ids))).delete(synchronize_session=False)


@router.get("/files/{file_id}")
def download_file(file_id: str, request: Request, db: Session = Depends(get_db)):
    """An Excel or PDF file the assistant made, for its chat's owner only."""
    from urllib.parse import quote
    from backend.app.core.s3 import S3Service
    user = current_user(request, db)
    f = db.get(ChatFile, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    _own_chat(db, user, f.session_id)
    data = S3Service().download_file_bytes(f.storage_path)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found")
    media = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if f.kind == "xlsx" else "application/pdf")
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f.filename)}"})


# ---- Files attached to a question ----

def delete_uploads(db: Session, user: User, session_id: Optional[str] = None, upload_id: Optional[str] = None) -> None:
    from backend.app.core.s3 import S3Service
    q = db.query(ChatUpload).filter(ChatUpload.user_id == user.id)
    q = q.filter(ChatUpload.session_id == session_id) if session_id else q.filter(ChatUpload.id == upload_id)
    storage = S3Service()
    for u in q.all():
        # Each file and its preview are kept in a folder of their own
        try:
            storage.delete_prefix(f"assistant_uploads/{u.user_id}/{u.id}/")
        except Exception:
            logger.warning("An attached file could not be deleted: %s", u.id, exc_info=True)
        db.delete(u)


@router.post("/uploads")
def add_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """A file attached to a question, read now: its text (PDF text layer, or the picture transcribed) and a preview."""
    from backend.app.core.s3 import S3Service
    from backend.app.services.assistant import uploads
    from backend.app.core import ai_usage
    from backend.app.services.assistant import chat_access
    user = current_user(request, db)
    _within_limit(db, user)
    name = (file.filename or "file").replace("\\", "/").split("/")[-1][:200]
    mime = uploads.kind_of(name)
    if mime is None:
        raise HTTPException(status_code=400, detail="Attach a PDF or a picture (PNG, JPG, WEBP)")
    data = file.file.read()
    if len(data) > uploads.MAX_BYTES:
        raise HTTPException(status_code=400, detail="A file can be up to 10 MB")
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty")
    u = ChatUpload(user_id=user.id, filename=name, mime=mime, size_bytes=len(data), storage_path="", status="READ")
    db.add(u)
    db.flush()
    storage = S3Service()
    u.storage_path = storage.upload_file_bytes(data, f"assistant_uploads/{user.id}/{u.id}/{name}")
    thumb = uploads.thumbnail(name, data)
    if thumb:
        u.thumb_path = storage.upload_file_bytes(thumb, f"assistant_uploads/{user.id}/{u.id}/thumb.png")
    with ai_usage.collect() as calls:          # a scan or photo is read by the model that sees pictures
        u.text, u.pages, u.status, u.note, u.read_by = uploads.read(name, data)
    db.commit()
    chat_access.add_spend(db, user, "upload", calls)
    return {**uploads.upload_json(u), "text": (u.text or "")[:4000]}


def _own_upload(db: Session, user: User, upload_id: str) -> ChatUpload:
    u = db.get(ChatUpload, upload_id)
    if u is None or u.user_id != user.id:
        raise HTTPException(status_code=404, detail="File not found")
    return u


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, request: Request, db: Session = Depends(get_db)):
    """The file's details and what was read from it (for the preview)."""
    from backend.app.services.assistant.uploads import upload_json
    u = _own_upload(db, current_user(request, db), upload_id)
    return {**upload_json(u), "text": u.text or ""}


@router.get("/uploads/{upload_id}/thumb")
def get_upload_thumb(upload_id: str, request: Request, db: Session = Depends(get_db)):
    from backend.app.core.s3 import S3Service
    u = _own_upload(db, current_user(request, db), upload_id)
    data = S3Service().download_file_bytes(u.thumb_path) if u.thumb_path else None
    if data is None:
        raise HTTPException(status_code=404, detail="No preview")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/uploads/{upload_id}/file")
def get_upload_file(upload_id: str, request: Request, db: Session = Depends(get_db)):
    """The file itself, shown in the page (not downloaded)."""
    from urllib.parse import quote
    from backend.app.core.s3 import S3Service
    u = _own_upload(db, current_user(request, db), upload_id)
    data = S3Service().download_file_bytes(u.storage_path)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found")
    return Response(content=data, media_type=u.mime,
                    headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(u.filename)}",
                             "Cache-Control": "private, max-age=3600"})


@router.delete("/uploads/{upload_id}")
def remove_upload(upload_id: str, request: Request, db: Session = Depends(get_db)):
    """A file taken off before the question was sent."""
    user = current_user(request, db)
    u = _own_upload(db, user, upload_id)
    if u.session_id:
        raise HTTPException(status_code=400, detail="The file was already sent with a question")
    delete_uploads(db, user, upload_id=u.id)
    db.commit()
    return {"deleted": upload_id}


# ---- Voice: what the user said, written out ----

@router.post("/voice")
async def voice_to_text(request: Request, db: Session = Depends(get_db)):
    """The words in a recording from the mic (16 kHz 16-bit mono PCM in the body), by AWS Transcribe in London."""
    from starlette.concurrency import run_in_threadpool
    from backend.app.core import ai_usage
    from backend.app.services.assistant import chat_access, voice
    user = current_user(request, db)
    _within_limit(db, user)
    pcm = await request.body()
    if len(pcm) < voice.RATE * 2 // 4:
        raise HTTPException(status_code=400, detail="The recording is too short")
    if len(pcm) > voice.RATE * 2 * (voice.MAX_SECONDS + 5):
        raise HTTPException(status_code=400, detail=f"Up to {voice.MAX_SECONDS // 60} minutes a recording")
    try:
        text = await run_in_threadpool(voice.transcribe_pcm, pcm)
    except Exception:
        logger.exception("Voice could not be written out")
        raise HTTPException(status_code=502, detail="The speech service did not answer. Try again, or type the question.")
    seconds = len(pcm) / (voice.RATE * 2)
    chat_access.add_spend(db, user, "voice", seconds=seconds,
                          usd=ai_usage.transcribe_cost(seconds, streams=len(voice.LANGUAGES)))
    return {"text": text}
