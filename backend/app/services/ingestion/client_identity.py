"""
Which client an upload belongs to.

A client is recognised by its company name, cleaned so that "Acme Trading Ltd" and "acme trading limited" are the
same client.
"""

import re
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement

COMPANY_SUFFIX = re.compile(r"\b(limited|ltd|plc|llp|llc)\b")


def company_key(name: str) -> str:
    """Company name for matching: lower case, '&' as 'and', no Ltd/Limited/PLC, punctuation or extra spaces."""
    key = (name or "").lower().replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", " ", key)
    key = COMPANY_SUFFIX.sub(" ", key)
    return re.sub(r"\s+", " ", key).strip()


def find_engagement(db: Session, client_name: str, period_end: date, owner_user_id: Optional[int] = None) -> Optional[ClientEngagement]:
    """The owner's engagement for this client and year end (a re-upload of the same year), or None for a new year."""
    key = company_key(client_name)
    candidates = db.execute(
        select(ClientEngagement)
        .where(ClientEngagement.period_end_date == period_end, ClientEngagement.owner_user_id == owner_user_id)
        .order_by(ClientEngagement.created_at.desc())
    ).scalars().all()
    return next((e for e in candidates if company_key(e.client_name) == key), None)
