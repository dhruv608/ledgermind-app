"""Opening balances in the general ledger ('Beginning Balance' lines) that the trial balance does not hold and the
upload could not use (they do not add up to zero, so adding them would unbalance the TB). Kept so the loans tab (G4)
can still show each loan's balance brought forward, and the review can ask for the missing opening balances."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String

from backend.app.core.database import Base, create_table


class GLOpeningBalance(Base):
    __tablename__ = "gl_opening_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    account_name = Column(String(255), nullable=False)
    amount = Column(Numeric(16, 2), nullable=False)         # debit + (a loan owed is negative)
    in_tb = Column(Integer, nullable=False, default=0)     # 1: the account is in the TB (with this year's movement only)
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(GLOpeningBalance.__table__)
