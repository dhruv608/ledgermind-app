"""Working papers the accountant adds to an area (Add New Workpaper and Add New
Reconciliation), as many as the area needs.

kind DETAILED        a T for the accounts picked (codes): opening, the year's lines, journals, closing, as any balance
kind SUPPORTING      a note with documents (the area's Evidence holds the files)
kind RECONCILIATION  two sides of lines typed by the accountant (debit and credit details) and the difference
kind LOAN_SCHEDULE   a loan's terms (note: JSON amount, rate, months, start); the screen works out the schedule"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.app.core.database import Base, create_table


class CustomPaper(Base):
    __tablename__ = "custom_papers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    area = Column(String(20), nullable=False)
    kind = Column(String(20), nullable=False)               # DETAILED / SUPPORTING / RECONCILIATION / LOAN_SCHEDULE
    name = Column(String(255), nullable=False)
    codes = Column(Text, nullable=False, default="[]")      # JSON list of firm codes (DETAILED)
    note = Column(Text, nullable=False, default="")
    lines = Column(Text, nullable=False, default="[]")      # JSON [{side: DEBIT|CREDIT, label, amount}] (RECONCILIATION)
    user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


create_table(CustomPaper.__table__)
