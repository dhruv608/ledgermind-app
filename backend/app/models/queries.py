"""The job's queries (the Queries tab): what the accountant did with each one. The queries themselves are worked out
again each time from the Data check, the Books tab's client questions and the review points, so only the person's
part is kept here: answered or cleared, the answer, and who it is for if they moved it. A query is found again
by its key after every re-run (the same problem has the same key)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, UniqueConstraint

from backend.app.core.database import Base, create_table


class JobQuery(Base):
    __tablename__ = "job_queries"
    __table_args__ = (UniqueConstraint("engagement_id", "key", name="uq_job_query"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    key = Column(String(200), nullable=False)          # "data:payroll", "books:money_in", "review:U-LOAN-002:Barclays"
    status = Column(String(20), nullable=False, default="OPEN")   # OPEN, ANSWERED, CLEARED
    audience = Column(String(20), nullable=True)       # CLIENT / ACCOUNTANT / INTERNAL when moved by hand, else null
    answer = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)          # unused (there is no "sent" status); kept in the table
    answered_at = Column(DateTime, nullable=True)
    user_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(JobQuery.__table__)


class RaisedQuery(Base):
    """A query raised by hand on an area page ('Raise query' on a point or an
    account). It joins the job's list as source 'raised', key 'raised:<id>'; what was done to it is kept in
    job_queries like any other. A query raised on a point keeps the point's key (its reference, title and row), so it
    stays on the point after the checks re-run."""
    __tablename__ = "raised_queries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    area = Column(String(20), nullable=True)           # the area page it was raised on ("vat", "bank" ...)
    audience = Column(String(20), nullable=False, default="CLIENT")
    title = Column(String(300), nullable=False)
    detail = Column(Text, nullable=True)
    amount = Column(Numeric(14, 2), nullable=True)
    ref = Column(String(40), nullable=True)            # the point's rule reference, for the Queries tab's topic
    point_key = Column(String(40), nullable=True)      # point_signoffs.point_key of the point it was raised on
    user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


create_table(RaisedQuery.__table__)
