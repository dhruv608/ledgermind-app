"""Routes for last year's checklist, this year's questions, and the queries from every page."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.models import SADocument, SAJob
from backend.app.sa.api.common import _owned


router = APIRouter()


class ExpectIn(BaseModel):
    source: Optional[str] = None
    kind: Optional[str] = None
    name: Optional[str] = Field(None, max_length=255)
    ref: Optional[str] = Field(None, max_length=60)
    last_amount: Optional[float] = None
    last_tax: Optional[float] = None
    ended: Optional[str] = Field(None, max_length=40)
    note: Optional[str] = Field(None, max_length=2000)
    answer: Optional[str] = Field(None, max_length=2000)
    status: Optional[str] = None            # set by the accountant (CONTINUED / CHANGED / UNKNOWN / ENDED); None: by the figures


def _expect(db: Session, job: SAJob, line_id: int):
    from backend.app.sa.models import SAExpect
    r = db.get(SAExpect, line_id)
    if r is None or r.job_id != job.id:
        raise HTTPException(status_code=404, detail="Line not found")
    return r


@router.get("/jobs/{job_id}/last-year")
def get_last_year(job_id: str, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import lastyear
    return lastyear.view(db, _owned(db, request, job_id))


@router.post("/jobs/{job_id}/last-year/lines")
def add_last_year_line(job_id: str, body: ExpectIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import lastyear
    from backend.app.sa.extract.lastyear import SOURCES
    from backend.app.sa.models import SAExpect
    job = _owned(db, request, job_id)
    if body.source not in SOURCES or body.kind not in SOURCES[body.source]:
        raise HTTPException(status_code=400, detail="Pick what kind of source it is")
    db.add(SAExpect(job_id=job.id, source=body.source, kind=body.kind, name=(body.name or "").strip() or lastyear.LABELS[body.source],
                    ref=body.ref, last_amount=body.last_amount, last_tax=body.last_tax, ended=body.ended, note=body.note, auto=0))
    db.commit()
    return lastyear.view(db, job)


@router.patch("/jobs/{job_id}/last-year/lines/{line_id}")
def edit_last_year_line(job_id: str, line_id: int, body: ExpectIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import lastyear
    job = _owned(db, request, job_id)
    r = _expect(db, job, line_id)
    patch = body.model_dump(exclude_unset=True)
    if "status" in patch:
        if patch["status"] not in (None, *lastyear.STATUS_LABELS):
            raise HTTPException(status_code=400, detail="Unknown status")
        r.status = patch.pop("status")
        r.hand = 1 if r.status else 0
    for k, v in patch.items():
        if k not in ("source", "kind"):
            setattr(r, k, v)
    r.agreed = 1                    # changed or confirmed by the accountant: no longer to check
    db.commit()
    return lastyear.view(db, job)


@router.delete("/jobs/{job_id}/last-year/lines/{line_id}")
def delete_last_year_line(job_id: str, line_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import lastyear
    job = _owned(db, request, job_id)
    db.delete(_expect(db, job, line_id))
    db.commit()
    return lastyear.view(db, job)


@router.post("/jobs/{job_id}/documents/{doc_id}/last-year")
def use_as_last_year(job_id: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
    """A working paper the date was not read from (an accounting year to 31 March): read it as last year's."""
    from backend.app.core.s3 import s3_service
    from backend.app.sa import lastyear
    from backend.app.sa.documents import is_sheet, previous_year, read_last_year
    job = _owned(db, request, job_id)
    doc = db.get(SADocument, doc_id)
    if doc is None or doc.job_id != job.id or not doc.storage_key or not is_sheet(doc.filename):
        raise HTTPException(status_code=404, detail="Spreadsheet not found")
    data = s3_service.download_file_bytes(doc.storage_key)
    if data is None:
        raise HTTPException(status_code=404, detail="The file is not kept")
    fields, doc.status, notes, doc.read_by = read_last_year(data, doc.filename)
    doc.kind, doc.tax_year, doc.fields, doc.note = "WORKING_PAPER", previous_year(job.tax_year), json.dumps(fields), " ".join(notes) or None
    db.commit()
    return lastyear.view(db, job)


# ---- This year's questions and the signs of new income in the bank (signals.py) ----

class AnswerIn(BaseModel):
    key: str = Field(..., max_length=120)              # q:<question> or s:<signal key>
    value: Optional[str] = None                        # YES / NO (questions), ASKED / DISMISSED (signs)
    note: Optional[str] = Field(None, max_length=2000)


def _questions_view(db: Session, job: SAJob) -> dict:
    from backend.app.sa import signals
    return signals.for_job(db, job)


@router.get("/jobs/{job_id}/questions")
def get_questions(job_id: str, request: Request, db: Session = Depends(get_db)):
    return _questions_view(db, _owned(db, request, job_id))


@router.put("/jobs/{job_id}/answers")
def put_answer(job_id: str, body: AnswerIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import signals
    job = _owned(db, request, job_id)
    allowed = {"q": ("YES", "NO"), "s": ("ASKED", "DISMISSED")}.get(body.key[:1])
    if not allowed or body.key[1:2] != ":" or (body.value is not None and body.value not in allowed):
        raise HTTPException(status_code=400, detail="Unknown answer")
    signals.answer(db, job, body.key, body.value, (body.note or "").strip() or None)
    return _questions_view(db, job)


# ---- Queries: client queries and accountant decisions from every page (queries.py) ----

class QueryAnswerIn(BaseModel):
    key: str = Field(..., max_length=130)
    answer: Optional[str] = Field(None, max_length=2000)


@router.get("/jobs/{job_id}/queries")
def get_queries(job_id: str, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import queries
    job = _owned(db, request, job_id)
    out = queries.queries(db, job)
    out["message"] = queries.client_text(out, job.person_name, job.tax_year)
    return out


@router.put("/jobs/{job_id}/queries/answer")
def answer_query(job_id: str, body: QueryAnswerIn, request: Request, db: Session = Depends(get_db)):
    """The client's answer, kept on the line the query comes from."""
    from backend.app.sa import queries, signals
    from backend.app.sa.models import SAAnswer
    job = _owned(db, request, job_id)
    text = (body.answer or "").strip() or None
    head, _, rest = body.key.partition(":")
    if head in ("exp", "exp-q") and rest.isdigit():
        r = _expect(db, job, int(rest))
        r.answer = text
        db.commit()
    elif head in ("q", "s"):
        kept = db.query(SAAnswer).filter(SAAnswer.job_id == job.id, SAAnswer.key == body.key).first()
        signals.answer(db, job, body.key, kept.value if kept else ("YES" if head == "q" else "ASKED"), text)
    else:
        raise HTTPException(status_code=400, detail="This query is answered on its page")
    out = queries.queries(db, job)
    out["message"] = queries.client_text(out, job.person_name, job.tax_year)
    return out
