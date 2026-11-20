"""Sign-in: checks the email and password against the users table and keeps the browser signed in with a cookie."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api.deps import SESSION_COOKIE, current_user
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.models.database import User
from backend.app.services.shared.auth import authenticate, create_session, end_session, locked_for

router = APIRouter()


class LoginIn(BaseModel):
    email: str
    password: str


def _who(user: User) -> dict:
    return {"email": user.email, "name": user.name or ""}


@router.post("/login")
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    wait = locked_for(email)
    if wait:
        raise HTTPException(status_code=429, detail=f"Too many tries. Wait {wait} seconds and try again.")
    user = authenticate(db, email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Email or password is not right.")
    token = create_session(db, user, settings.SESSION_DAYS)
    response.set_cookie(SESSION_COOKIE, token, max_age=settings.SESSION_DAYS * 86400, httponly=True,
                        samesite=settings.COOKIE_SAMESITE, secure=settings.COOKIE_SECURE, path="/")
    return _who(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "SUCCESS"}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _who(user)
