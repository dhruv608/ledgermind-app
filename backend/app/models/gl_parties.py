"""The payee / customer ('Name') and the other side of the entry ('Split') of a general ledger line, when the ledger
gives them (QuickBooks). Kept beside the line, not on it: the live ledger table takes no new columns (as gl_foreign).
Shown on the General Ledger and the K tabs. The line's description keeps 'Name - Memo',
which the review rules read."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from backend.app.core.database import Base, create_table


class GLParty(Base):
    __tablename__ = "gl_parties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    gl_transaction_id = Column(Integer, ForeignKey("gl_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    split = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(GLParty.__table__)
