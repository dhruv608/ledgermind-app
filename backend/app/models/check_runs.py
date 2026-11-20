"""A client's checks running in the background: one row per
run, with the step it is on, so any server worker can tell the screen how far it has got."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from backend.app.core.database import Base, engine


class CheckRun(Base):
    __tablename__ = "check_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    status = Column(String(12), nullable=False)          # RUNNING, DONE, FAILED
    trigger = Column(String(20), nullable=True)          # setup, upload, accountant
    step = Column(String(30), nullable=True)             # the step it is on (services/checks/runner.STEPS)
    steps_done = Column(Integer, default=0)
    rerun = Column(Boolean, default=False)               # the books or setup changed while it ran: run again after
    summary = Column(Text, nullable=True)                # JSON: points, journals, seconds
    error = Column(Text, nullable=True)
    started_by = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


# A new table only, made on first use; the worker that loses the start-up race finds it made and carries on
try:
    CheckRun.__table__.create(bind=engine, checkfirst=True)
except Exception:
    CheckRun.__table__.create(bind=engine, checkfirst=True)
