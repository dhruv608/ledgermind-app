"""Routes for a job's documents: upload (now or in the background), the file itself, a person's review, and the
return at a glance."""

import json
import threading
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.documents import add_documents, doc_out
from backend.app.sa.income import drop_doc_lines, sync_p60_lines
from backend.app.sa.models import SADocument, SAJob, SALine
from backend.app.sa.api.common import _owned


router = APIRouter()


MAX_UPLOAD = 200 * 1024 * 1024


@router.get("/jobs/{job_id}/documents")
def list_documents(job_id: str, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    docs = db.query(SADocument).filter(SADocument.job_id == job.id).order_by(SADocument.id).all()
    return [doc_out(d) for d in docs]


@router.post("/jobs/{job_id}/documents")
def upload_documents(job_id: str, request: Request, files: List[UploadFile] = File(...), background: bool = False,
                     db: Session = Depends(get_db)):
    """Every file (zips unpacked), classified, P60s read and checked; the job's whole list comes back. A plain (not
    async) route: the reading can take minutes, so it runs in its own worker thread and never holds up other users."""
    job = _owned(db, request, job_id)
    blobs = [(f.filename or "file", f.file.read()) for f in files]
    if sum(len(b) for _, b in blobs) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Over 200 MB in one go: send the documents in smaller batches.")
    if background:
        # Read in its own thread: the upload answers at once and the screen asks until it is done, so a slow AI
        # service never runs past the web server's time limit (nginx 300 s) while the reading still goes on
        from backend.app.sa.models import SAReading
        row = SAReading(job_id=job.id, filename=", ".join(n for n, _ in blobs)[:255])
        db.add(row)
        db.commit()
        db.refresh(row)
        threading.Thread(target=_read_in_background, args=(job.id, row.id, blobs), daemon=True).start()
        return {"reading_id": row.id}
    add_documents(db, job, blobs)
    sync_p60_lines(db, job)
    return list_documents(job_id, request, db)


# A reading not finished after this long was stopped (the server restarted): the screen says to send it again
READING_STALE_MIN = 45


def _read_in_background(job_id: str, reading_id: int, blobs) -> None:
    """The documents read and the return synced, in a session of its own; the reading row says when it is done."""
    from backend.app.core.database import SessionLocal
    from backend.app.sa.models import SAReading
    db = SessionLocal()
    try:
        job = db.get(SAJob, job_id)
        add_documents(db, job, blobs)
        sync_p60_lines(db, job)
        error = None
    except Exception as e:                    # the error is shown on the screen; the files can be sent again
        db.rollback()
        error = f"The documents could not be read: {type(e).__name__}. Please send them again."
    try:
        row = db.get(SAReading, reading_id)
        if row is not None:
            row.finished, row.error = 1, error
            db.commit()
    finally:
        db.close()


@router.get("/jobs/{job_id}/reading/{reading_id}")
def reading_status(job_id: str, reading_id: int, request: Request, db: Session = Depends(get_db)):
    """Whether a file sent in the background is read yet: {done, error, documents (when done)}."""
    from datetime import datetime, timedelta
    from backend.app.sa.models import SAReading
    job = _owned(db, request, job_id)
    row = db.get(SAReading, reading_id)
    if row is None or row.job_id != job.id:
        raise HTTPException(status_code=404, detail="Reading not found")
    if not row.finished and row.started_at and datetime.utcnow() - row.started_at > timedelta(minutes=READING_STALE_MIN):
        row.finished, row.error = 1, "The reading stopped before it finished. Please send the file again."
        db.commit()
    if not row.finished:
        return {"done": False, "error": None, "documents": None}
    out = {"done": True, "error": row.error, "documents": list_documents(job_id, request, db)}
    db.delete(row)
    db.commit()
    return out


@router.delete("/jobs/{job_id}/documents/{doc_id}")
def delete_document(job_id: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    job = _owned(db, request, job_id)
    doc = db.get(SADocument, doc_id)
    if doc is None or doc.job_id != job.id:
        raise HTTPException(status_code=404, detail="Document not found")
    drop_doc_lines(db, job, doc.id)
    db.delete(doc)
    db.commit()
    return list_documents(job_id, request, db)


@router.get("/jobs/{job_id}/overview")
def get_overview(job_id: str, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa.overview import overview
    return overview(db, _owned(db, request, job_id))


MEDIA = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif"}


@router.get("/jobs/{job_id}/documents/{doc_id}/file")
def get_document_file(job_id: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    """The document itself, to look at beside what was read (PDFs and pictures shown in the page)."""
    from fastapi.responses import Response
    from backend.app.core.s3 import s3_service
    job = _owned(db, request, job_id)
    doc = db.get(SADocument, doc_id)
    if doc is None or doc.job_id != job.id or not doc.storage_key:
        raise HTTPException(status_code=404, detail="Document not found")
    data = s3_service.download_file_bytes(doc.storage_key)
    if data is None:
        raise HTTPException(status_code=404, detail="The file is not kept")
    ext = "." + doc.filename.rsplit(".", 1)[-1].lower() if "." in doc.filename else ""
    return Response(content=data, media_type=MEDIA.get(ext, "application/octet-stream"),
                    headers={"Cache-Control": "private, max-age=3600"})


class DocReview(BaseModel):
    fields: Optional[dict] = None       # figures corrected by the person (a P60: pay_this, tax_this, employer...)
    confirm: bool = True                # the person has looked: the document is read


@router.patch("/jobs/{job_id}/documents/{doc_id}")
def review_document(job_id: str, doc_id: int, body: DocReview, request: Request, db: Session = Depends(get_db)):
    """A person's check of a document: its figures as corrected, marked read; its income line follows."""
    job = _owned(db, request, job_id)
    doc = db.get(SADocument, doc_id)
    if doc is None or doc.job_id != job.id:
        raise HTTPException(status_code=404, detail="Document not found")
    fields = json.loads(doc.fields) if doc.fields else {}
    for k, v in (body.fields or {}).items():
        if k in ("pay_this", "tax_this", "pay_previous", "tax_previous", "pay_total", "tax_total"):
            v = float(v) if v not in (None, "") else None
        fields[k] = v
    doc.fields = json.dumps(fields)
    if body.confirm:
        doc.status = "READ"
        doc.note = f"Checked by {request.state.user.email.split('@')[0]}" + (" (figures corrected)" if body.fields else "")
        doc.tax_year = fields.get("tax_year") or doc.tax_year
        # A P60 naming someone else, confirmed as the person's own: it goes on the return (R-IN-07); a rent statement
        # with no agent named, confirmed as one: its figures go on the Property page
        if fields.pop("other_person", None) is not None or fields.pop("unconfirmed", None) is not None:
            fields.pop("unconfirmed", None)
            doc.fields = json.dumps(fields)
    for line in db.query(SALine).filter(SALine.job_id == job.id, SALine.doc_id == doc.id, SALine.auto == 1).all():
        if fields.get("pay_this") is not None:
            line.amount = fields["pay_this"]
        if fields.get("tax_this") is not None:
            line.tax_paid = fields["tax_this"]
        if fields.get("employer"):
            line.label = fields["employer"]
    db.commit()
    sync_p60_lines(db, job)
    return doc_out(doc)
