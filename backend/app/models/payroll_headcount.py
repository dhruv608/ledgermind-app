"""The number of employees the client's payroll file gives: by month (its 'No of employees' / 'No. of EE' column), or
for the year ('Average employee : 3'). G6.3 (average number of employees, for the accounts' note) uses it; a payroll
summary of monthly totals names nobody, so counting names gives 1."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from backend.app.core.database import Base, create_table


class PayrollHeadcount(Base):
    __tablename__ = "payroll_headcount"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    period_end = Column(Date, nullable=True)                # the payroll month; None for the year's average
    count = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(PayrollHeadcount.__table__)
