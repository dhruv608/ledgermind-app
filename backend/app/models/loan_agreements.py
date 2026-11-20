"""The client's loan and hire purchase agreements, from the client's loans register (one row per agreement): the terms the
schedule needs (services/loans/schedule.py). Uploading the register again replaces them."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from backend.app.core.database import Base, create_table


class LoanAgreement(Base):
    __tablename__ = "loan_agreements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    lender = Column(String(255), nullable=False)
    kind = Column(String(50), nullable=True)               # Loan / HP / BBL / Lease
    drawdown = Column(Date, nullable=True)
    first_payment = Column(Date, nullable=True)
    amount = Column(Numeric(16, 2), nullable=False)        # amount financed (cash price or loan)
    deposit = Column(Numeric(16, 2), nullable=True)
    payments = Column(Integer, nullable=False)             # number of payments
    per_year = Column(Integer, nullable=False, default=12)
    rate = Column(Numeric(10, 6), nullable=True)           # a year: 0.025 = 2.5%
    charge = Column(Numeric(16, 2), nullable=True)         # total finance charge
    payment = Column(Numeric(16, 2), nullable=True)        # regular payment
    balloon = Column(Numeric(16, 2), nullable=True)
    method = Column(String(30), nullable=True)             # Actuarial / Rule of 78 / Flat
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(LoanAgreement.__table__)
