"""Documents behind an area's balance, uploaded on its Evidence tab (an upload box
per balance; a missing document never blocks). The file is kept so the reviewer can open it; when the app has a
reader for it (VAT returns, payroll report, fixed asset register, loans register) it is also read into the checks."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from backend.app.core.database import Base, create_table


class AreaEvidence(Base):
    __tablename__ = "area_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    engagement_id = Column(String(36), nullable=False, index=True)
    area = Column(String(20), nullable=False)
    filename = Column(String(255), nullable=False)
    stored = Column(String(500), nullable=False)        # where the file is (S3 or this computer)
    size = Column(Integer, default=0)
    read_as = Column(String(40), nullable=True)         # what the checks read it as (VAT_100 ...), None: kept only
    records = Column(Integer, default=0)                # rows the checks took from it
    user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


create_table(AreaEvidence.__table__)
