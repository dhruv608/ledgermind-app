"""Directors' pay for the year as the client's payroll file gives it (gross, employer NI and employer pension, and the
directors it names), read at upload. The review compares it with the directors' accounts in the books and proposes
moving what is still in the staff wages."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text

from backend.app.core.database import Base, create_table


class PayrollDirectorPay(Base):
    __tablename__ = "payroll_director_pay"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    gross_pay = Column(Numeric(14, 2), nullable=False)
    employer_nic = Column(Numeric(14, 2), nullable=True)
    pension_employer = Column(Numeric(14, 2), nullable=True)
    people = Column(Text, nullable=True)                   # JSON {director: gross} when the file names them
    how = Column(String(50), nullable=True)                # 'total line', 'director column', 'director blocks'
    filename = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(PayrollDirectorPay.__table__)


class PayrollDirectorMonth(Base):
    """Directors' gross pay month by month, when the payroll file gives it (a 'Director wages' column, a block per
    director): G6.2 shows directors' and staff pay apart per month and checks the directors' accounts against it."""
    __tablename__ = "payroll_director_month"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    period_end = Column(Date, nullable=False)
    gross_pay = Column(Numeric(14, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


create_table(PayrollDirectorMonth.__table__)
