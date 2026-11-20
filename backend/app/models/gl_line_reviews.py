"""GL scrutiny: what the accountant decided about each ledger line, read one account at a time: OK (fine where it is)
or MOVED (to another code, by a proposed journal), and a question to the client about it (shown on the Queries tab).
A line is known by a key worked out from its own content (account, date, text, reference, amounts), not its row id,
so the decisions survive the books being uploaded again."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, UniqueConstraint

from backend.app.core.database import Base, create_table


class GLLineReview(Base):
    __tablename__ = "gl_line_reviews"
    __table_args__ = (UniqueConstraint("engagement_id", "line_key", name="uq_gl_line_review"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    line_key = Column(String(40), nullable=False)       # sha1 of the line's content (services/scrutiny.line_keys)
    status = Column(String(10), nullable=True)           # OK | MOVED, or null: only asked about
    to_code = Column(Integer, nullable=True)             # MOVED: the code it was moved to
    journal_id = Column(Integer, nullable=True)          # MOVED: the journal that moves it
    question = Column(Text, nullable=True)               # asked of the client (a query on the Queries tab)
    line_label = Column(String(300), nullable=True)      # the line as the query shows it: date, text, code
    amount = Column(Numeric(14, 2), nullable=True)       # the line's amount (debit +), for the query
    asked_at = Column(DateTime, nullable=True)
    user_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(GLLineReview.__table__)
