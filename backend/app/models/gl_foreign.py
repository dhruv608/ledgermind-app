"""The foreign currency of a general ledger line, when the ledger gives it (QuickBooks 'Exchange Rate', 'Foreign
Amount' and 'Currency' columns: a USD bank account, sales paid in euros). Kept beside the line, not on it: the live
ledger table takes no new columns. Only lines in another currency are kept (a line in pounds has rate 1 and no
foreign amount). Shown on General Ledger Detail."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String

from backend.app.core.database import Base, create_table


class GLForeign(Base):
    __tablename__ = "gl_foreign"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    gl_transaction_id = Column(Integer, ForeignKey("gl_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    currency = Column(String(10), nullable=True)            # 'EUR', 'USD' when the ledger names it
    exchange_rate = Column(Numeric(18, 8), nullable=True)   # pounds per unit of the currency, as the ledger gives it
    foreign_amount = Column(Numeric(16, 2), nullable=True)  # the line in its own currency
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(GLForeign.__table__)
