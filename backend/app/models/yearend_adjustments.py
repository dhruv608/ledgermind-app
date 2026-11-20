"""The client's accruals and prepayments, line by line with the cost each one is for: entered by hand
to record or reverse, several lines each with its code; the next year's reversal comes automatically.

period THIS_YEAR: this year end's accruals / prepayments (journals Dr cost / Cr 5360, Dr 4900 / Cr cost).
period LAST_YEAR: last year's, split by cost, to reverse this year (Dr 5360 / Cr cost, Dr cost / Cr 4900). When last
year's client is in the app its THIS_YEAR lines are used, so from the second year the reversal needs no typing."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from backend.app.core.database import Base, create_table, add_columns


class YearEndAdjustment(Base):
    __tablename__ = "yearend_adjustments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)               # ACCRUAL / PREPAYMENT
    period = Column(String(20), nullable=False)             # THIS_YEAR / LAST_YEAR
    description = Column(String(255), nullable=False, default="")
    cost_code = Column(Integer, nullable=False)             # the P&L account it is for (firm chart)
    amount = Column(Numeric(16, 2), nullable=False)         # positive
    # The invoice behind it (number, date, amount, the period it covers): from these the screen works out
    # the part after the year end
    invoice_number = Column(String(60), nullable=True)
    invoice_date = Column(Date, nullable=True)
    invoice_amount = Column(Numeric(16, 2), nullable=True)
    period_from = Column(Date, nullable=True)
    period_to = Column(Date, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is; the invoice columns added to a
# table made before them (nullable: the lines saved before keep working)
create_table(YearEndAdjustment.__table__)
add_columns("yearend_adjustments", {"invoice_number": "VARCHAR(60)", "invoice_date": "DATE", "invoice_amount": "NUMERIC(16, 2)",
                                    "period_from": "DATE", "period_to": "DATE"})


class LastYearClaim(Base):
    """A director's claim last year's final working paper posted through the director's loan at the year end (its B2
    journals: use of home, director's salary), read when last year's paper is uploaded, so this year's can be
    proposed as last year (only when the client profile records them or last year's paper had them)."""
    __tablename__ = "last_year_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)               # HOME / SALARY / MILEAGE
    description = Column(String(255), nullable=False, default="")
    amount = Column(Numeric(16, 2), nullable=False)         # credited to the director's loan, positive
    created_at = Column(DateTime, default=datetime.utcnow)


create_table(LastYearClaim.__table__)
