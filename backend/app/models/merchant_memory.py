"""What the firm decided about a merchant's code, for the reanalysis engine's memory:
every move the accountant approves or rejects one by one, and the moves seeded from the firm's
final working papers. Who decided and when is kept on each row, so a wrong batch (a test run approving everything)
can be found and removed; a decision approved in bulk is never written here."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, String

from backend.app.core.database import Base, engine


class MerchantMemory(Base):
    __tablename__ = "merchant_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, nullable=True, index=True)     # the firm, until firms are their own table
    client_key = Column(String(160), nullable=False, index=True)   # the company, the same across its years
    engagement_id = Column(String(36), nullable=True)
    period_end = Column(Date, nullable=True)
    industry = Column(String(10), nullable=True)
    merchant_key = Column(String(120), nullable=False, index=True)
    code = Column(Integer, nullable=False)
    outcome = Column(String(12), nullable=False)    # APPROVED, REJECTED, SEED (from a final working paper)
    source = Column(String(60), nullable=True)      # "reanalysis", "bank sorting", "final WP 2025"
    made_by = Column(Integer, nullable=True)
    made_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is. The server's workers start together
# and may both create it: the one that loses
# the race finds the table made and carries on
try:
    MerchantMemory.__table__.create(bind=engine, checkfirst=True)
except Exception:
    MerchantMemory.__table__.create(bind=engine, checkfirst=True)
