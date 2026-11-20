"""The firm's own coding: client account names with the firm code the accountant gave them in finished working papers
('Telephone & Internet' -> 3290). Shown to the AI as examples, and used directly where the accountant always codes a
name the same way (a firm habit). Loaded from past working papers (backend/scripts/load_firm_examples.py)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from backend.app.core.database import Base, create_table


class FirmExample(Base):
    __tablename__ = "firm_examples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, nullable=True)          # the firm (one sign-in for now)
    account_name = Column(String(255), nullable=False, index=True)   # as in the client's TB
    std_code = Column(Integer, nullable=False)
    client = Column(String(255), nullable=True)              # which client's working papers it came from
    source = Column(String(50), default="WORKING_PAPERS")
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(FirmExample.__table__)
