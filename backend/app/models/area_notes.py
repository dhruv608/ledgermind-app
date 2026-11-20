"""Notes on an area page: threaded comments, who and when, separate from the points. A note can answer another (parent_id) and can be about one point, kept by the point's key
(its reference, title and row, as sign-offs are) so it stays on the point after the checks re-run."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.app.core.database import Base, create_table


class AreaNote(Base):
    __tablename__ = "area_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    area = Column(String(20), nullable=False)
    parent_id = Column(Integer, nullable=True)          # the note this one answers
    point_key = Column(String(40), nullable=True)       # point_signoffs.point_key of the point it is about
    point_title = Column(String(300), nullable=True)    # the point's title when written (shown if the point is gone)
    text = Column(Text, nullable=False)
    user_id = Column(Integer, nullable=True)
    author = Column(String(120), nullable=True)
    initials = Column(String(4), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(AreaNote.__table__)
