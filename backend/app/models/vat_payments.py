"""What the client's VAT summary says was paid on each return: amount, date, what is still outstanding, and the VAT
basis it was prepared on. Read from the uploaded VAT summary (one row per return), next to the return's boxes in
vat_100_records. Used to match each return to its HMRC payment and to show the client's real VAT basis."""

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from backend.app.core.database import Base, create_table


class VatReturnPayment(Base):
    __tablename__ = "vat_return_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=False, index=True)
    period_label = Column(String(100), nullable=False)       # as on the summary ('Q.E. 30.06.2025', 'Opening balance')
    period_end = Column(Date, nullable=True)
    paid = Column(Numeric(14, 2), nullable=True)             # paid to HMRC (a refund received is negative)
    paid_date = Column(Date, nullable=True)                  # the first payment date when the summary gives one
    paid_date_text = Column(String(100), nullable=True)      # as written ('09.12.2024 , 18.12 2024', 'Paid in next year')
    outstanding = Column(Numeric(14, 2), nullable=True)      # still owed (refund due: negative) per the summary
    interest = Column(Numeric(14, 2), nullable=True)         # interest received / paid, kept apart from the payment
    basis = Column(String(50), nullable=True)                # STANDARD (accrual), CASH or FLAT_RATE, from the summary
    created_at = Column(DateTime, default=datetime.utcnow)


# A new table only: created on first use, leaving every existing table as it is
create_table(VatReturnPayment.__table__)
