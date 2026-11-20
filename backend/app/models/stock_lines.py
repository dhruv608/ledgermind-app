"""The closing stock line by line (per line the account, stock type, description, amount,
impairment, last year; who verified the count, us or the client). One row per line; the count's verification is kept
on each job's lines (verified_by on every row of the job, the same value)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from backend.app.core.database import Base, create_table


class StockLine(Base):
    __tablename__ = "stock_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    code = Column(Integer, nullable=True)                   # the stock account (4300 ...)
    stock_type = Column(String(40), nullable=False, default="")   # materials, finished goods, work in progress
    description = Column(String(255), nullable=False, default="")
    amount = Column(Float, nullable=False, default=0.0)
    impairment = Column(Float, nullable=False, default=0.0)
    last_year = Column(Float, nullable=True)
    verified_by = Column(String(20), nullable=False, default="")  # US / CLIENT
    note = Column(String(500), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


create_table(StockLine.__table__)
