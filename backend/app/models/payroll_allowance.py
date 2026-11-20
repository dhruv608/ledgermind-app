"""The employment allowance the client's payroll file shows (its 'Employment Allowance' / 'E Allowance' / "Er' allow"
column), month by month when the file gives months. It says the allowance was claimed through the payroll, and how
much: employer NI per the payroll less this is the employer NI cost in the accounts."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from backend.app.core.database import Base, create_table


class PayrollAllowance(Base):
    __tablename__ = "payroll_allowance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    period_end = Column(Date, nullable=True)                # the payroll month; None for a year's figure
    amount = Column(Numeric(14, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(PayrollAllowance.__table__)
