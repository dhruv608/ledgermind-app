"""The firm's own defaults, set on the Firm settings page (each firm sets its own rates,
such as depreciation). One row per setting, its value as JSON; a client's own setup still comes first.

  depreciation: {"classes": {asset class: {"method", "rate"}}, "additions_from": FULL_YEAR / PURCHASE_MONTH /
                 NEXT_MONTH}. Starts from rules/firm_policies.json until the firm saves its own.
  accountancy_fee: {"amount"}: the standard fee accrued for a year's accounts when last year's is not known.
  ct_hold_limit: {"amount"}: suspense on a bank job above this holds back its tax and dividend journals (£1,000).
(Use of home is not a firm setting: the accountant adds it on each job from its point.)"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from backend.app.core.database import Base, create_table


class FirmSetting(Base):
    __tablename__ = "firm_settings"

    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=False)                    # JSON
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(FirmSetting.__table__)
