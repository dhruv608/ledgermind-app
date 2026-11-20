"""The accountant's choices on the Books tab (raw data route): a bank line's or bill's head, a probable match
confirmed, a client question answered. The books are worked out again from the client's files each time, with these
choices on top, so a choice survives every re-run and nothing else needs storing."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from backend.app.core.database import Base, create_table


class RawBooksChoice(Base):
    __tablename__ = "raw_books_choices"
    __table_args__ = (UniqueConstraint("engagement_id", "key", name="uq_raw_books_choice"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    key = Column(String(120), nullable=False)          # "bank:40", "bill:12", "confirm:bank:40", "answer:bank:40"
    value = Column(Text, nullable=False)                # JSON
    user_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(RawBooksChoice.__table__)
