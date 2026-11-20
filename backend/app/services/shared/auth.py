"""
Sign-in: users are rows in the users table, each password stored only as a scrypt hash (Python's standard library,
no extra package). The sign-in page checks the email and password here.
"""

import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import User

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MAX_FAILURES, LOCK_SECONDS = 5, 60          # a pause after repeated wrong passwords for one email
_failures: Dict[str, Tuple[int, float]] = {}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        kind, salt_b64, digest_b64 = stored.split("$")
        if kind != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64), n=SCRYPT_N, r=SCRYPT_R,
                                p=SCRYPT_P, dklen=32)
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def locked_for(email: str) -> int:
    """Seconds left before this email may try again (0 = may try)."""
    count, since = _failures.get(email, (0, 0.0))
    if count < MAX_FAILURES:
        return 0
    left = int(LOCK_SECONDS - (time.time() - since))
    if left <= 0:
        _failures.pop(email, None)
        return 0
    return left


def authenticate(db: Session, email: str, password: str) -> Optional[User]:
    email = (email or "").strip().lower()
    user = db.query(User).filter(User.email == email, User.active.is_(True)).first()
    if user is None or not check_password(password or "", user.password_hash):
        count, _ = _failures.get(email, (0, 0.0))
        _failures[email] = (count + 1, time.time())
        return None
    _failures.pop(email, None)
    user.last_login_at = datetime.utcnow()
    db.commit()
    return user


def create_or_update_user(db: Session, email: str, password: str, name: Optional[str] = None) -> User:
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, name=name, password_hash=hash_password(password), active=True)
        db.add(user)
    else:
        user.password_hash = hash_password(password)
        user.active = True
        if name:
            user.name = name
    db.commit()
    return user


# ---------------------------------------------------------------------------------------------------------------
# Sessions: a random token in an http-only cookie; the database keeps only its SHA-256
# ---------------------------------------------------------------------------------------------------------------
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, days: int) -> str:
    from datetime import timedelta
    from backend.app.models.database import UserSession
    token = secrets.token_urlsafe(32)
    db.add(UserSession(user_id=user.id, token_hash=_token_hash(token), expires_at=datetime.utcnow() + timedelta(days=days)))
    db.query(UserSession).filter(UserSession.expires_at < datetime.utcnow()).delete(synchronize_session=False)
    db.commit()
    return token


def user_for_token(db: Session, token: Optional[str]) -> Optional[User]:
    from backend.app.models.database import UserSession
    if not token:
        return None
    s = db.query(UserSession).filter(UserSession.token_hash == _token_hash(token)).first()
    if s is None or s.expires_at < datetime.utcnow():
        return None
    user = db.get(User, s.user_id)
    return user if user is not None and user.active else None


def end_session(db: Session, token: Optional[str]) -> None:
    from backend.app.models.database import UserSession
    if token:
        db.query(UserSession).filter(UserSession.token_hash == _token_hash(token)).delete(synchronize_session=False)
        db.commit()
