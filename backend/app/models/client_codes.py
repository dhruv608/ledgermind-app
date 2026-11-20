"""The firm code a client's own trial balance gives each account (a 'Taxcalc Code' / 'Final code' column beside the
client's account code, as in 'Code | Client account name | Debit | Credit | Balance | Final code'). Kept per job so a re-run of the coding still has it."""

from sqlalchemy import Column, Integer, String

from backend.app.core.database import Base, create_table


class TBClientCode(Base):
    __tablename__ = "tb_client_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    raw_account_name = Column(String(255), nullable=False)
    firm_code = Column(Integer, nullable=False)


# A new table only: created on first use, leaving every existing table as it is
create_table(TBClientCode.__table__)
