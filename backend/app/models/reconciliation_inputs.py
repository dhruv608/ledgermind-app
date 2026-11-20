"""Figures the accountant types on the control accounts screen that are in no uploaded file: each bank account's
statement balance at the year end (or, for a foreign currency account, the currency balance and the year-end rate),
and the HMRC CIS figures per tax month ("cis_hmrc:..."). The workbook's bank tabs (F3) start from the same figures, so
they are typed once."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from backend.app.core.database import Base, create_table


class ReconciliationInput(Base):
    __tablename__ = "reconciliation_inputs"
    __table_args__ = (UniqueConstraint("engagement_id", "key", name="uq_reconciliation_input"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    key = Column(String(120), nullable=False)          # "bank:4800", "cis_hmrc:2025-07-06"
    value = Column(Text, nullable=False)                # JSON: {"balance": ...} or {"currency_amount": ..., "rate": ...}
    user_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(ReconciliationInput.__table__)
