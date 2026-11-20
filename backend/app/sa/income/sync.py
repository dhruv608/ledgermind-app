"""The job's lines brought up to date from its documents: P60s here, then every other reader in turn."""

import json

from sqlalchemy.orm import Session

from backend.app.sa.extract import p60
from backend.app.sa.models import SADocument, SAJob, SALine
from backend.app.sa.income.employment import sync_p11d_lines, sync_p45_lines
from backend.app.sa.income.savings import (sync_dividend_lines, sync_donation_lines, sync_pension_lines,
                                           sync_savings_lines)
from backend.app.sa.income.property import sync_letting_items, sync_mortgage_items
from backend.app.sa.income.trading import (sync_cis_takings, sync_client_sheets, sync_receipt_items, sync_statement_poa,
                                           sync_vat_returns)


def sync_p60_lines(db: Session, job: SAJob) -> None:
    """An employment line for every P60 of the year not yet on the return."""
    have = {d for (d,) in db.query(SALine.doc_id).filter(SALine.job_id == job.id, SALine.doc_id.isnot(None)).all()}
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "P60",
                                           SADocument.status.in_(("READ", "CHECK"))).all():
        if doc.id in have or not doc.fields:
            continue
        f = json.loads(doc.fields)
        if f.get("pay_this") is None or f.get("other_person") or f.get("looks_cis") or f.get("one_reader"):
            continue                       # another person's P60: off the return until confirmed (R-IN-07)
        # A pension paid through PAYE comes with a P60 too: pension income (SA100 box 11), not an employment
        pension = p60.is_pension(f.get("employer"))
        db.add(SALine(job_id=job.id, source="PENSIONS" if pension else "EMPLOYMENT", kind="PENSION" if pension else "P60",
                      label=f.get("employer") or ("Pension" if pension else "Employer"),
                      amount=f["pay_this"], tax_paid=f.get("tax_this") or 0, doc_id=doc.id, auto=1,
                      note=f"PAYE {f['paye_ref']}" if f.get("paye_ref") else None))
    db.commit()
    sync_p45_lines(db, job)
    sync_p11d_lines(db, job)
    sync_savings_lines(db, job)
    sync_letting_items(db, job)
    sync_pension_lines(db, job)
    sync_mortgage_items(db, job)
    sync_dividend_lines(db, job)
    sync_client_sheets(db, job)
    sync_cis_takings(db, job)
    sync_receipt_items(db, job)
    sync_donation_lines(db, job)
    sync_vat_returns(db, job)
    sync_statement_poa(db, job)


def drop_doc_lines(db: Session, job: SAJob, doc_id: int) -> None:
    from backend.app.sa.models import SAPropertyItem
    db.query(SALine).filter(SALine.job_id == job.id, SALine.doc_id == doc_id, SALine.auto == 1).delete()
    # A letting statement's rent and costs go with it (a property the accountant added stays)
    db.query(SAPropertyItem).filter(SAPropertyItem.job_id == job.id, SAPropertyItem.doc_id == doc_id).delete()
    db.commit()
