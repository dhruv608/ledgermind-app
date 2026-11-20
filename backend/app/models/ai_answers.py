"""What the AI answered about one thing on a client (a ledger line, ...), kept so a review run that sees the same thing
again does not ask again (and pay again). One row per (client, kind of question, key)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from backend.app.core.database import Base, create_table


class AIAnswer(Base):
    __tablename__ = "ai_answers"
    __table_args__ = (UniqueConstraint("engagement_id", "kind", "key", name="uq_ai_answer"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    kind = Column(String(30), nullable=False)            # what was asked, e.g. "capital"
    key = Column(String(300), nullable=False)            # what it was asked about (the ledger line)
    answer = Column(Text, nullable=False)                # JSON
    model = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only, made on first use; the worker that loses the start-up race finds it made and carries on
create_table(AIAnswer.__table__)
