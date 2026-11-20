"""The test chat page's code screen (/chat): is the page on, has this device given the code, give the code, forget
this device. No sign-in needed (services/assistant/chat_access.py says what the code reaches)."""

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.services.assistant import chat_access

router = APIRouter()

WRONG_DELAY = 1.0          # seconds before a wrong code is answered


def _address(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else "unknown")


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)):
    on = chat_access.enabled()
    device = chat_access.user_for_device(db, request.cookies.get(chat_access.CHAT_COOKIE)) if on else None
    return {"enabled": on, "unlocked": device is not None}


class Code(BaseModel):
    code: str


@router.post("/code")
def give_code(body: Code, request: Request, response: Response, db: Session = Depends(get_db)):
    if not chat_access.enabled():
        raise HTTPException(status_code=404, detail="The test chat is switched off.")
    address = _address(request)
    wait = chat_access.wait_seconds(address)
    if wait:
        raise HTTPException(status_code=429, detail=f"Too many wrong codes. Try again in {max(1, wait // 60)} minute(s).")
    if not chat_access.check_code(address, body.code):
        time.sleep(WRONG_DELAY)
        raise HTTPException(status_code=401, detail="Wrong code. Try again.")
    token = chat_access.remember_device(db)
    response.set_cookie(chat_access.CHAT_COOKIE, token, max_age=settings.CHAT_DEVICE_DAYS * 86400, httponly=True,
                        samesite=settings.COOKIE_SAMESITE, secure=settings.COOKIE_SECURE, path="/")
    return {"unlocked": True}


@router.post("/forget")
def forget(request: Request, response: Response, db: Session = Depends(get_db)):
    chat_access.forget_device(db, request.cookies.get(chat_access.CHAT_COOKIE))
    response.delete_cookie(chat_access.CHAT_COOKIE, path="/")
    return {"unlocked": False}
