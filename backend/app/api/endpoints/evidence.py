"""An area page's Evidence tab (under /engagements/{id}): the documents behind the area's balance. Each file is kept
for the reviewer; the ones the app can read (VAT returns, payroll report, fixed asset register, loans register) are
read into the checks as on the VAT & payroll tab."""

import re
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.s3 import s3_service
from backend.app.models.area_evidence import AreaEvidence
from backend.app.models.database import ClientEngagement, SupplementaryDocument

router = APIRouter()

# What the checks read a file on this area as (the supplementary reader's own types); an area not here keeps the file
READ_AS = {"vat": "VAT_100", "payroll": "PAYROLL_P32", "fixed": "FIXED_ASSET_REGISTER", "loans": None}
# Documents read on the VAT & payroll tab before, shown on their area as in
OLD_TYPES = {"VAT_100": "vat", "PAYROLL_P32": "payroll", "FIXED_ASSET_REGISTER": "fixed", "LOANS_REGISTER": "loans"}


def _engagement(db: Session, engagement_id: str) -> ClientEngagement:
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return eng


def _listing(db: Session, engagement_id: str) -> dict:
    """{area: [documents]}: the files uploaded on the Evidence tabs, and those read on the VAT & payroll tab."""
    out: dict = {}
    for e in db.query(AreaEvidence).filter(AreaEvidence.engagement_id == engagement_id).order_by(AreaEvidence.id):
        out.setdefault(e.area, []).append({
            "id": e.id, "filename": e.filename, "size": e.size, "read_as": e.read_as, "records": e.records,
            "at": e.created_at.isoformat() if e.created_at else None, "kept": True})
    named = {(d["filename"]) for docs in out.values() for d in docs}
    for d in db.query(SupplementaryDocument).filter(SupplementaryDocument.engagement_id == engagement_id):
        area = OLD_TYPES.get(d.doc_type)
        if area and d.filename not in named:
            out.setdefault(area, []).append({
                "id": None, "filename": d.filename, "size": d.file_size_bytes, "read_as": d.doc_type,
                "records": d.parsed_records_count, "at": d.created_at.isoformat() if d.created_at else None,
                "kept": False})
    return out


@router.get("/{engagement_id}/evidence")
def get_evidence(engagement_id: str, db: Session = Depends(get_db)):
    _engagement(db, engagement_id)
    return _listing(db, engagement_id)


@router.post("/{engagement_id}/evidence/{area}")
def add_evidence(engagement_id: str, area: str, request: Request, files: List[UploadFile] = File(...),
                 db: Session = Depends(get_db)):
    """Keep each file with the area; read it into the checks when the app has a reader for this area's document."""
    from backend.app.services.shared.activity import mark_changed
    from backend.app.services.ingestion.supplementary_parser import SupplementaryParserService
    _engagement(db, engagement_id)
    if not re.fullmatch(r"[a-z]{2,20}", area):
        raise HTTPException(status_code=400, detail="Unknown area")
    user = getattr(request.state, "user", None)
    read_any = False
    for f in files:
        if not f.filename:
            continue
        content = f.file.read()
        if not content:
            continue
        safe = re.sub(r"[^\w.\- ]", "_", f.filename)[:120]
        row = AreaEvidence(engagement_id=engagement_id, area=area, filename=f.filename[:255], size=len(content),
                           user_id=getattr(user, "id", None), stored="")
        db.add(row)
        db.flush()
        row.stored = s3_service.upload_file_bytes(content, f"engagements/{engagement_id}/evidence/{area}/{row.id}-{safe}")
        if area in READ_AS and f.filename.lower().endswith((".xlsx", ".xls", ".csv")):
            try:
                doc = SupplementaryParserService.parse_and_store(engagement_id=engagement_id, filename=f.filename,
                                                                 content=content, forced_type=READ_AS[area], db=db)
                if doc.get("doc_type") not in (None, "OTHER") and doc.get("parsed_records_count"):
                    row.read_as, row.records = doc["doc_type"], int(doc["parsed_records_count"])
                    read_any = True
            except Exception:
                db.rollback()
                db.add(row)
        db.commit()
    if read_any:
        mark_changed(db, engagement_id)
    return _listing(db, engagement_id)


@router.get("/{engagement_id}/evidence/file/{evidence_id}")
def open_evidence(engagement_id: str, evidence_id: int, db: Session = Depends(get_db)):
    row = db.get(AreaEvidence, evidence_id)
    if not row or row.engagement_id != engagement_id:
        raise HTTPException(status_code=404, detail="Document not found")
    data = s3_service.download_file_bytes(row.stored)
    if data is None:
        raise HTTPException(status_code=404, detail="The file is no longer stored")
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{re.sub(chr(34), "", row.filename)}"'})


@router.delete("/{engagement_id}/evidence/{evidence_id}")
def remove_evidence(engagement_id: str, evidence_id: int, db: Session = Depends(get_db)):
    """The file is removed from the area; what the checks already read from it stays (upload a corrected file to
    replace it)."""
    row = db.get(AreaEvidence, evidence_id)
    if not row or row.engagement_id != engagement_id:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(row)
    db.commit()
    return _listing(db, engagement_id)
