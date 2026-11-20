"""Routes for the figures by SA box and the working paper pack."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.models import SAJob
from backend.app.sa.api.common import _owned


router = APIRouter()


@router.get("/jobs/{job_id}/boxes")
def get_boxes(job_id: str, request: Request, db: Session = Depends(get_db)):
    """The figures by form and box, to enter in the tax software."""
    from backend.app.sa.boxes import boxes
    return boxes(db, _owned(db, request, job_id))


class PackIn(BaseModel):
    final: bool = False
    note: Optional[str] = Field(None, max_length=500)


def _packs(db: Session, job: SAJob) -> dict:
    from backend.app.sa import pack
    from backend.app.sa.models import SAPack
    from backend.app.sa.queries import queries
    rows = db.query(SAPack).filter(SAPack.job_id == job.id).order_by(SAPack.version.desc()).all()
    return {"versions": [pack.out(r) for r in rows], "counts": queries(db, job)["counts"]}


@router.get("/jobs/{job_id}/pack")
def get_packs(job_id: str, request: Request, db: Session = Depends(get_db)):
    """The pack's versions, newest first, and the Blocks that stop a final one."""
    return _packs(db, _owned(db, request, job_id))


@router.post("/jobs/{job_id}/pack")
def make_pack(job_id: str, body: PackIn, request: Request, db: Session = Depends(get_db)):
    """A new version of the working paper pack (R-OUT-01: no final pack while a Block is open)."""
    from backend.app.sa import pack
    job = _owned(db, request, job_id)
    user = request.state.user
    try:
        pack.make(db, job, body.final, (body.note or "").strip() or None, user.name or user.email)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _packs(db, job)


@router.get("/jobs/{job_id}/pack/{pack_id}/file")
def get_pack_file(job_id: str, pack_id: int, request: Request, db: Session = Depends(get_db)):
    """A version of the pack as it was made."""
    from fastapi.responses import Response
    from backend.app.core.s3 import s3_service
    from backend.app.sa import pack
    from backend.app.sa.models import SAPack
    job = _owned(db, request, job_id)
    row = db.get(SAPack, pack_id)
    if row is None or row.job_id != job.id or not row.storage_key:
        raise HTTPException(status_code=404, detail="Pack not found")
    data = s3_service.download_file_bytes(row.storage_key)
    if data is None:
        raise HTTPException(status_code=404, detail="The file is not kept")
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{pack.file_name(job, row)}"'})
