"""Sign-off on a review point by the preparer, the reviewer and the partner, with initials and date.
Points are rebuilt every time the checks run, so a sign-off is kept against the point's content
(its reference, title and row, as cleared points are), not its row id: it stays on the same point after a re-run."""

import hashlib
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from backend.app.core.database import Base, create_table

ROLES = ("PREPARER", "REVIEWER", "PARTNER")


class PointSignoff(Base):
    __tablename__ = "point_signoffs"
    __table_args__ = (UniqueConstraint("engagement_id", "point_key", "role", name="uq_point_signoff"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    point_key = Column(String(40), nullable=False)      # sha1 of the point's reference, title and row (point_key below)
    role = Column(String(10), nullable=False)           # PREPARER | REVIEWER | PARTNER
    user_id = Column(Integer, nullable=True)
    initials = Column(String(4), nullable=True)
    signed_at = Column(DateTime, default=datetime.utcnow)


def point_key(procedure_ref: str, finding_title: str, source_row_ref: str) -> str:
    return hashlib.sha1(f"{procedure_ref}|{finding_title}|{source_row_ref or ''}".encode("utf-8")).hexdigest()


def initials_of(name: str, email: str) -> str:
    """'Jane Smith' -> 'JS'; with no name, the start of the email ('uitest@...' -> 'UI')."""
    words = [w for w in (name or "").replace(".", " ").split() if w[:1].isalpha()]
    if words:
        return "".join(w[0] for w in words[:3]).upper()
    return (email or "?").split("@")[0][:2].upper()


# A new table only: created on first use, leaving every existing table as it is
create_table(PointSignoff.__table__)


class AreaSignoff(Base):
    """Sign-off on a whole area (VAT, bank ...) by the preparer, then the reviewer, then the partner, with
    initials and date (areas Completed / Not started). The area's points when it was signed
    (a fingerprint of their references and titles) tell the page when they changed since."""
    __tablename__ = "area_signoffs"
    __table_args__ = (UniqueConstraint("engagement_id", "area", "role", name="uq_area_signoff"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    area = Column(String(20), nullable=False)
    role = Column(String(10), nullable=False)           # PREPARER | REVIEWER | PARTNER
    user_id = Column(Integer, nullable=True)
    initials = Column(String(4), nullable=True)
    fingerprint = Column(String(40), nullable=True)     # the area's points when signed
    signed_at = Column(DateTime, default=datetime.utcnow)


create_table(AreaSignoff.__table__)
