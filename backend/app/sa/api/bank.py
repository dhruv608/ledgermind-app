"""Routes for the bank statements: each account put together, and a business's books made from them (books package)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.sa.api.common import _owned
from backend.app.sa.api.trade import _business, _trade_view


router = APIRouter()


@router.get("/jobs/{job_id}/bank")
def get_bank(job_id: str, request: Request, db: Session = Depends(get_db)):
    """Each account's statements from every file: duplicates dropped, in date order, chained, the year covered."""
    from backend.app.sa.books import accounts
    from backend.app.sa.extract.statement import covers
    from backend.app.sa.income import tax_year_dates
    job = _owned(db, request, job_id)
    start, end = (x.isoformat() for x in tax_year_dates(job.tax_year))
    out = []
    for acct, bank, a in accounts(db, job):
        sel = [l for l in a.lines if l.on and start <= l.on <= end]
        out.append({"account": acct, "bank": bank, "opening": a.opening, "closing": a.closing, "first": a.first,
                    "last": a.last, "duplicates": a.duplicates, "checks": a.checks + covers(a, start, end),
                    "money_in": round(sum(l.money_in for l in sel), 2), "money_out": round(sum(l.money_out for l in sel), 2),
                    "lines": [{"on": l.on, "description": l.description, "in": l.money_in, "out": l.money_out,
                               "balance": l.balance, "doc_id": l.doc_id, "page": l.page, "in_year": bool(l.on and start <= l.on <= end)}
                              for l in a.lines]})
    return {"period": {"start": start, "end": end}, "accounts": out}


# ---- A business's books from the bank statements (books package) ----

class BankChoiceIn(BaseModel):
    keys: List[str]
    heading: Optional[str] = None          # None: back to the rules


@router.get("/jobs/{job_id}/trade/{business_id}/bank")
def get_trade_bank(job_id: str, business_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import books
    job = _owned(db, request, job_id)
    return books.view(db, job, _business(db, job, business_id))


@router.patch("/jobs/{job_id}/trade/{business_id}/bank")
def choose_trade_bank(job_id: str, business_id: int, body: BankChoiceIn, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import books
    job = _owned(db, request, job_id)
    biz = _business(db, job, business_id)
    if body.heading is not None and body.heading not in books.HEADINGS and body.heading not in books.OUTSIDE:
        raise HTTPException(status_code=400, detail="Unknown heading")
    books.choose(db, job, body.keys[:2000], body.heading)
    return books.view(db, job, biz)


@router.post("/jobs/{job_id}/trade/{business_id}/bank/suggest")
def suggest_trade_bank(job_id: str, business_id: int, request: Request, db: Session = Depends(get_db)):
    from backend.app.sa import books
    job = _owned(db, request, job_id)
    biz = _business(db, job, business_id)
    books.suggest(db, job, biz)
    return books.view(db, job, biz)


class PrivateUseIn(BaseModel):
    kind: str = Field(..., max_length=20)
    business_pct: Optional[float] = Field(None, ge=0, le=100)     # None: not given (the whole cost stays allowed)


@router.put("/jobs/{job_id}/trade/{business_id}/private-use")
def put_private_use(job_id: str, business_id: int, body: PrivateUseIn, request: Request, db: Session = Depends(get_db)):
    """The business % of a mixed-use cost; the bank figures are posted again when they are in."""
    from backend.app.sa import books, signals
    from backend.app.sa.models import SABusinessItem
    job = _owned(db, request, job_id)
    biz = _business(db, job, business_id)
    if body.kind not in books.MIXED:
        raise HTTPException(status_code=400, detail="Unknown kind")
    signals.answer(db, job, f"pu:{biz.id}:{body.kind}",
                   None if body.business_pct is None else f"{round(body.business_pct, 2):g}")
    if db.query(SABusinessItem).filter(SABusinessItem.business_id == biz.id,
                                       SABusinessItem.description == books.FROM_BANK).count():
        books.post(db, job, biz)
        from backend.app.sa.income import sync_vat_returns
        sync_vat_returns(db, job)
    return books.view(db, job, biz)


@router.post("/jobs/{job_id}/trade/{business_id}/bank/post")
def post_trade_bank(job_id: str, business_id: int, request: Request, db: Session = Depends(get_db)):
    """The totals per heading into the business (in place of the ones put there before)."""
    from backend.app.sa import books
    job = _owned(db, request, job_id)
    books.post(db, job, _business(db, job, business_id))
    from backend.app.sa.income import sync_vat_returns
    sync_vat_returns(db, job)             # a VAT-registered trade: the bank's takings and costs net of VAT
    return _trade_view(db, job)
