"""The test chat page (/chat): a 4-digit code (settings.CHAT_PIN) instead of a sign-in, for testing the assistant.

  who        every device that gives the code is the same user, 'Chat test' (made here, never able to sign in: no
             password, and not active, so its token is refused everywhere a normal sign-in is needed)
  remembered the code gives a random token in its own http-only cookie (CHAT_COOKIE), kept CHAT_DEVICE_DAYS; the
             database keeps only its hash (the sign-in's sessions table)
  reaches    the assistant's endpoints only, and only when the page says it is the test page (CHAT_HEADER): the
             user owns no client, so the assistant answers from the law and SOP knowledge only
  tries      4 digits are only 10,000 codes: 5 wrong from one address lock it for 15 minutes, 20 wrong in an hour from
             anywhere lock the code for an hour
  spend      the day's AI spend (answers, voice, files read) stops at CHAT_DAILY_LIMIT_USD
"""

import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.database import User, UserSession

CHAT_COOKIE = "lm_chat"
CHAT_HEADER = "X-LedgerMind-Chat"
TESTER_EMAIL = "chat-test@ledgermind.invalid"
TESTER_NAME = "Chat test"

PER_ADDRESS_TRIES = 5
PER_ADDRESS_LOCK = 15 * 60
ALL_TRIES = 20
ALL_WINDOW = 60 * 60

_lock = threading.Lock()
_wrong: Dict[str, List[float]] = {}        # address -> times of wrong codes
_wrong_all: List[float] = []


def enabled() -> bool:
    pin = (settings.CHAT_PIN or "").strip()
    return len(pin) == 4 and pin.isdigit()


def tester(db: Session) -> User:
    user = db.query(User).filter(User.email == TESTER_EMAIL).first()
    if user is None:
        # 'none' is not a password hash: no password ever matches it
        user = User(email=TESTER_EMAIL, name=TESTER_NAME, password_hash="none", active=False)
        db.add(user)
        db.commit()
    return user


def wait_seconds(address: str, now: Optional[float] = None) -> int:
    """Seconds before this address may try a code again (0: may try)."""
    now = now or time.time()
    with _lock:
        _wrong_all[:] = [t for t in _wrong_all if now - t < ALL_WINDOW]
        if len(_wrong_all) >= ALL_TRIES:
            return int(ALL_WINDOW - (now - _wrong_all[0])) + 1
        mine = [t for t in _wrong.get(address, []) if now - t < PER_ADDRESS_LOCK]
        _wrong[address] = mine
        if len(mine) >= PER_ADDRESS_TRIES:
            return int(PER_ADDRESS_LOCK - (now - mine[0])) + 1
    return 0


def check_code(address: str, code: str) -> bool:
    ok = enabled() and hmac.compare_digest((code or "").strip().encode(), settings.CHAT_PIN.strip().encode())
    with _lock:
        if ok:
            _wrong.pop(address, None)
        else:
            now = time.time()
            _wrong.setdefault(address, []).append(now)
            _wrong_all.append(now)
    return ok


def reset_tries() -> None:
    with _lock:
        _wrong.clear()
        _wrong_all.clear()


def _hash(token: str) -> str:
    from backend.app.services.shared.auth import _token_hash
    return _token_hash(token)


def remember_device(db: Session) -> str:
    """A new token for this device (the cookie's value)."""
    user = tester(db)
    token = secrets.token_urlsafe(32)
    db.add(UserSession(user_id=user.id, token_hash=_hash(token),
                       expires_at=datetime.utcnow() + timedelta(days=settings.CHAT_DEVICE_DAYS)))
    db.commit()
    return token


def forget_device(db: Session, token: Optional[str]) -> None:
    if token:
        db.query(UserSession).filter(UserSession.token_hash == _hash(token)).delete(synchronize_session=False)
        db.commit()


def user_for_device(db: Session, token: Optional[str]) -> Optional[User]:
    """The test user, when the page is on and this device gave the code."""
    if not token or not enabled():
        return None
    s = db.query(UserSession).filter(UserSession.token_hash == _hash(token)).first()
    if s is None or s.expires_at < datetime.utcnow():
        return None
    user = db.get(User, s.user_id)
    return user if user is not None and user.email == TESTER_EMAIL else None


def is_tester(user: Optional[User]) -> bool:
    return user is not None and user.email == TESTER_EMAIL


# ---- What the assistant has cost ----

def spend(db: Session, user: User, since: Optional[datetime] = None) -> Dict[str, Any]:
    """Tokens and US$ of this user's assistant since a time (None: ever): answers, voice and files read."""
    from backend.app.models.chat import AssistantSpend, ChatMessage, ChatSession
    mine = select(ChatSession.id).where(ChatSession.user_id == user.id)
    q = select(func.coalesce(func.sum(ChatMessage.tokens_in), 0), func.coalesce(func.sum(ChatMessage.tokens_out), 0),
               func.coalesce(func.sum(ChatMessage.cost_usd), 0), func.count(ChatMessage.id)) \
        .where(ChatMessage.session_id.in_(mine), ChatMessage.role == "assistant")
    if since is not None:
        q = q.where(ChatMessage.created_at >= since)
    tin, tout, usd, answers = db.execute(q).one()
    out = {"tokens_in": int(tin), "tokens_out": int(tout), "answers": int(answers), "answers_usd": float(usd),
           "voice_seconds": 0.0, "voice_usd": 0.0, "files_usd": 0.0}
    q = select(AssistantSpend.kind, func.coalesce(func.sum(AssistantSpend.tokens_in), 0),
               func.coalesce(func.sum(AssistantSpend.tokens_out), 0), func.coalesce(func.sum(AssistantSpend.seconds), 0),
               func.coalesce(func.sum(AssistantSpend.cost_usd), 0)).where(AssistantSpend.user_id == user.id)
    if since is not None:
        q = q.where(AssistantSpend.created_at >= since)
    for kind, sin, sout, secs, susd in db.execute(q.group_by(AssistantSpend.kind)).all():
        out["tokens_in"] += int(sin)
        out["tokens_out"] += int(sout)
        if kind == "voice":
            out["voice_seconds"] += float(secs)
            out["voice_usd"] += float(susd)
        else:
            out["files_usd"] += float(susd)
    out["usd"] = round(out["answers_usd"] + out["voice_usd"] + out["files_usd"], 6)
    for k in ("answers_usd", "voice_usd", "files_usd"):
        out[k] = round(out[k], 6)
    return out


def today_start() -> datetime:
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def over_limit(db: Session, user: User) -> bool:
    """The test user has spent the day's limit (real users have no limit here)."""
    return is_tester(user) and spend(db, user, today_start())["usd"] >= settings.CHAT_DAILY_LIMIT_USD


def add_spend(db: Session, user: User, kind: str, calls: List[Dict[str, Any]] = (), seconds: float = 0.0,
              usd: float = 0.0) -> None:
    """One voice question or file read: its model calls (from ai_usage.collect) and any other cost."""
    from decimal import Decimal
    from backend.app.models.chat import AssistantSpend
    total = usd + sum(c.get("usd", 0) for c in calls)
    if not calls and not total:
        return
    db.add(AssistantSpend(user_id=user.id, kind=kind, model=(calls[0]["model"] if calls else None),
                          tokens_in=sum(c.get("in", 0) for c in calls), tokens_out=sum(c.get("out", 0) for c in calls),
                          seconds=Decimal(str(round(seconds, 2))), cost_usd=Decimal(str(round(total, 6)))))
    db.commit()
