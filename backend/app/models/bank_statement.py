"""A bank statement's lines, read from a file uploaded on the bank area's Evidence (for the bank reconciliation:
Recorded / Unrecorded / Unmatched / Matched). One row per statement line, kept against the bank account's firm code."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, Integer, String

from backend.app.core.database import Base, create_table


class BankStatementLine(Base):
    __tablename__ = "bank_statement_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    code = Column(Integer, nullable=False)              # the bank account's firm code (4800 ...)
    evidence_id = Column(Integer, nullable=False)       # the uploaded statement it was read from
    line_date = Column(Date, nullable=True)
    description = Column(String(500), nullable=False, default="")
    money_in = Column(Float, default=0.0)
    money_out = Column(Float, default=0.0)
    balance = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


create_table(BankStatementLine.__table__)
