"""
Who is asking: every request outside the sign-in needs a signed-in user (the session cookie), and anything named in
the address (a client, journal, review point, workbook or account rule) must belong to that user. A new sign-in
therefore starts empty and never sees another user's clients.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import (
    AuditFinding, ClientEngagement, FirmMappingRule, GeneratedWorkpaper, ProposedJournal, User,
)
from backend.app.services.shared.auth import user_for_token

SESSION_COOKIE = "ff_session"


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_for_token(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    request.state.user = user
    return user


def assistant_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The assistant's endpoints: the signed-in user, or on the test chat page (it sends CHAT_HEADER) the test user of
    a device that gave the code. The test page never uses the sign-in cookie, so it never reaches a real user's chats.
    A picture or download link cannot send a header: those addresses end in ?chat=1 instead."""
    from backend.app.services.assistant import chat_access
    if request.headers.get(chat_access.CHAT_HEADER) == "1" or request.query_params.get("chat") == "1":
        user = chat_access.user_for_device(db, request.cookies.get(chat_access.CHAT_COOKIE))
        if user is None:
            raise HTTPException(status_code=401, detail="Enter the code to use the chat.")
        request.state.user = user
        return user
    return current_user(request, db)


def owned_engagement(db: Session, user: User, engagement_id: Optional[str]) -> ClientEngagement:
    eng = db.get(ClientEngagement, engagement_id) if engagement_id else None
    if eng is None or eng.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return eng


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Signed in, and the owner of whatever the address names."""
    user = current_user(request, db)
    p = request.path_params
    if "engagement_id" in p:
        owned_engagement(db, user, p["engagement_id"])
    for key, model in (("journal_id", ProposedJournal), ("finding_id", AuditFinding), ("workpaper_id", GeneratedWorkpaper)):
        if key in p:
            try:
                row = db.get(model, int(p[key]))
            except (TypeError, ValueError):
                row = None
            if row is None:
                raise HTTPException(status_code=404, detail="Not found")
            owned_engagement(db, user, row.engagement_id)
    if "rule_id" in p:
        try:
            rule = db.get(FirmMappingRule, int(p["rule_id"]))
        except (TypeError, ValueError):
            rule = None
        if rule is None:
            raise HTTPException(status_code=404, detail="Rule not found")
    return user
