"""Supplementary schedules (VAT 100, fixed asset register, payroll) and the VAT returns screen (under /engagements/{id})."""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import (
    ClientEngagement, FixedAssetRecord, PayrollP32Record, SupplementaryDocument, VAT100Record,
)
from backend.app.models.schemas import (
    FixedAssetRecordSchema, PayrollP32RecordSchema, SupplementaryDocumentSchema, SupplementaryUploadResponse,
    VAT100RecordSchema, VatReturnsSaveRequest,
)
from backend.app.services.shared.activity import mark_changed
from backend.app.services.ingestion.supplementary_parser import SupplementaryParserService

router = APIRouter()

def year_warnings(eng: ClientEngagement, kinds: set, db: Session) -> List[str]:
    """A payroll report or VAT summary for another year than the job's (a January - December payroll
    report against an April - March year): said at once, so the accountant checks the file chosen."""
    from backend.app.services.review.paye_check import _year
    start, end = _year(eng)
    span = lambda ds: f"{min(ds):%b %Y} to {max(ds):%b %Y}"
    out = []
    if any("PAYROLL" in (k or "") for k in kinds):
        dates = [r.period_end for r in db.query(PayrollP32Record).filter(PayrollP32Record.engagement_id == eng.id)
                 if r.period_end]
        outside = [d for d in dates if not start <= d <= end]
        if dates and len(outside) == len(dates):
            out.append(f"The payroll report is for {span(dates)}, not this year ({start:%b %Y} to {end:%b %Y}): "
                       f"check the right file was chosen.")
        elif outside:
            out.append(f"{len(outside)} payroll month(s) outside this year ({span(outside)}) are left out.")
    if any("VAT" in (k or "") for k in kinds):
        ends = [r.period_end for r in db.query(VAT100Record).filter(VAT100Record.engagement_id == eng.id) if r.period_end]
        if ends and not any(start <= d <= end for d in ends):
            out.append(f"The VAT returns end {span(ends)}, none in this year ({start:%b %Y} to {end:%b %Y}): check "
                       f"the right VAT summary was chosen.")
    return out


def slot_warnings(eng: ClientEngagement, doc_type: Optional[str], filename: str, content: bytes,
                  info: dict) -> List[str]:
    """A file put in a named slot that is not what the slot is for: last year's final working paper whose year end is
    not about a year before this one, next year's ledger with no line in the nine months after the year end."""
    end = eng.period_end_date
    if doc_type == "LAST_YEAR_WP" and end is not None:
        from backend.app.services.ingestion.last_year_adjustments import read
        paper_end = read(content).get("year_end")
        if paper_end is None:
            return [f"{filename}: no year end found on it, so it was not read as last year's working paper. Upload "
                    f"the whole final working paper (all its tabs)."]
        if not 300 <= (end - paper_end).days <= 430:
            return [f"{filename} is for the year ended {paper_end:%d/%m/%Y}, not the year before this one "
                    f"({end:%d/%m/%Y}): check the right working paper was chosen."]
    if doc_type == "NEXT_YEAR_LEDGER" and not info.get("parsed_records_count"):
        return [f"{filename}: no ledger lines dated in the nine months after the year end ({end:%d/%m/%Y}) were "
                f"found. Upload next year's general ledger."]
    return []


@router.post("/{engagement_id}/supplementary-upload", response_model=SupplementaryUploadResponse)
def upload_supplementary_documents(
    engagement_id: str,
    files: List[UploadFile] = File(...),
    doc_type: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Upload one or more supplementary schedules (VAT 100, fixed asset register, payroll P32)."""
    eng = db.query(ClientEngagement).filter(ClientEngagement.id == engagement_id).first()
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")

    docs = []
    named: List[str] = []
    for f in files:
        if not f.filename:
            continue
        content = f.file.read()
        if len(content) == 0:
            continue
        doc_info = SupplementaryParserService.parse_and_store(
            engagement_id=engagement_id,
            filename=f.filename,
            content=content,
            forced_type=doc_type,
            db=db,
        )
        docs.append(doc_info)
        named += slot_warnings(eng, doc_type, f.filename, content, doc_info)

    mark_changed(db, engagement_id)
    vat_count = db.query(VAT100Record).filter(VAT100Record.engagement_id == engagement_id).count()
    far_count = db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement_id).count()
    pay_count = db.query(PayrollP32Record).filter(PayrollP32Record.engagement_id == engagement_id).count()

    return {
        "engagement_id": engagement_id,
        "uploaded_documents": docs,
        "warnings": named + year_warnings(eng, {d.get("doc_type") for d in docs}, db),
        "vat_records_count": vat_count,
        "fixed_asset_records_count": far_count,
        "payroll_records_count": pay_count,
    }

@router.get("/{engagement_id}/supplementary-docs", response_model=List[SupplementaryDocumentSchema])
def list_supplementary_documents(engagement_id: str, db: Session = Depends(get_db)):
    """Lists all supplementary files attached to this engagement"""
    return db.query(SupplementaryDocument).filter(
        SupplementaryDocument.engagement_id == engagement_id
    ).order_by(SupplementaryDocument.created_at.desc()).all()

@router.get("/{engagement_id}/supplementary-data")
def get_supplementary_data(engagement_id: str, db: Session = Depends(get_db)):
    """Retrieves all parsed supplementary schedule records (VAT, FAR, Payroll)"""
    vat_records = db.query(VAT100Record).filter(VAT100Record.engagement_id == engagement_id).all()
    far_records = db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement_id).all()
    payroll_records = db.query(PayrollP32Record).filter(PayrollP32Record.engagement_id == engagement_id).all()

    return {
        "vat_records": [VAT100RecordSchema.model_validate(r) for r in vat_records],
        "fixed_asset_records": [FixedAssetRecordSchema.model_validate(r) for r in far_records],
        "payroll_records": [PayrollP32RecordSchema.model_validate(r) for r in payroll_records],
    }


@router.get("/{engagement_id}/vat-returns", response_model=List[VAT100RecordSchema])
def list_vat_returns(engagement_id: str, db: Session = Depends(get_db)):
    """VAT returns entered for this client, oldest first"""
    return db.query(VAT100Record).filter(VAT100Record.engagement_id == engagement_id).order_by(
        VAT100Record.period_end.asc().nulls_last(), VAT100Record.id.asc()
    ).all()

@router.get("/{engagement_id}/vat-returns/paid")
def vat_returns_paid(engagement_id: str, db: Session = Depends(get_db)):
    """Each return's amount owed, paid against it and still unpaid (as G9 matches the payments)."""
    from backend.app.services.reconciliation.control_accounts import vat_paid_per_return
    eng = db.query(ClientEngagement).filter(ClientEngagement.id == engagement_id).first()
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return vat_paid_per_return(eng, db)

@router.put("/{engagement_id}/vat-returns", response_model=List[VAT100RecordSchema])
def save_vat_returns(engagement_id: str, payload: VatReturnsSaveRequest, db: Session = Depends(get_db)):
    """Replace the client's VAT returns with the list typed on the VAT returns screen (boxes 3 and 5 are worked out)"""
    eng = db.query(ClientEngagement).filter(ClientEngagement.id == engagement_id).first()
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    ends = [r.period_end for r in payload.returns]
    if len(ends) != len(set(ends)):
        raise HTTPException(status_code=400, detail="Two returns have the same period end date")

    db.execute(delete(VAT100Record).where(VAT100Record.engagement_id == engagement_id))
    for r in sorted(payload.returns, key=lambda x: x.period_end):
        box3 = round(r.box1 + r.box2, 2)
        db.add(VAT100Record(
            engagement_id=engagement_id,
            period_label=r.period_end.strftime("%b-%y"),
            period_end=r.period_end,
            box1_vat_due_sales=r.box1,
            box2_vat_due_acquisitions=r.box2,
            box3_total_vat_due=box3,
            box4_vat_reclaimed=r.box4,
            box5_net_vat=round(box3 - r.box4, 2),
            box6_total_sales_ex_vat=r.box6,
            box7_total_purchases_ex_vat=r.box7,
            box8_supplies_to_eu=r.box8,
            box9_acquisitions_from_eu=r.box9,
            bfwd_outstanding=r.bfwd_outstanding,
        ))
    db.commit()
    mark_changed(db, engagement_id)
    return list_vat_returns(engagement_id, db)
