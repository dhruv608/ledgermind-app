"""Next year's ledger lines, uploaded for a job (the optional post-year-end GL): the months
after the year end, kept apart from the year's own books. Used as evidence only: bills that relate to the year
(accruals), invoices and bills paid after the year end, the April payroll payments."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from backend.app.core.database import Base, create_table


class PostYearEndLine(Base):
    __tablename__ = "post_year_end_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    when = Column(Date, nullable=False)
    account = Column(String(255), nullable=False, default="")
    code = Column(Integer, nullable=True)                   # the firm code of the account, by this year's mapping
    source = Column(String(80), nullable=True)
    description = Column(String(500), nullable=True)
    reference = Column(String(120), nullable=True)
    debit = Column(Numeric(16, 2), nullable=False, default=0)
    credit = Column(Numeric(16, 2), nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(PostYearEndLine.__table__)
