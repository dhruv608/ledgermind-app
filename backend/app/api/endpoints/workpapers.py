import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement, TBRecord, GeneratedWorkpaper
from backend.app.models.schemas import WorkpaperGenerationResponse
from backend.app.services.workbook.excel_service import excel_service
from backend.app.core.s3 import s3_service

router = APIRouter()

# Mapping statuses that must be checked by an accountant before the final workpapers
REVIEW_STATUSES = {"NEEDS_REVIEW", "UNMAPPED"}


def is_nil(t) -> bool:
    """An account with no balance and no movement: its mapping changes no figure in the workpapers."""
    return all(abs(float(v or 0)) < 0.005 for v in (t.net_amount, t.debit_amount, t.credit_amount, t.opening_amount))

def draft_reasons(db: Session, engagement: ClientEngagement, tb_records: list) -> str:
    """Why the workbook is only a draft: it is 'final' only when the TB balances, last year's balances are in, no
    critical point is open and every proposed journal is decided. Empty when it can be final."""
    from backend.app.models.database import AuditFinding, ProposedJournal
    from backend.app.services.review.last_year import last_year_job, prior_balances_by_code
    reasons = []
    out_by = round(sum(float(t.net_amount or 0.0) for t in tb_records), 2)
    if abs(out_by) > 0.01:
        reasons.append(f"TB out of balance by £{abs(out_by):,.2f}")
    # The same test as the Data check: openings brought in, or a TB that already holds closing balances, or the first
    # year (a books client's TB is built from last year's closing TB)
    from backend.app.services.bank_only.books import is_books_client
    from backend.app.services.setup.data_check import STOP, _opening_balances
    from backend.app.services.setup.profile_service import ProfileService
    has_opening = (is_books_client(engagement) or last_year_job(engagement, db) is not None
                   or bool(prior_balances_by_code(engagement, db))
                   or _opening_balances(engagement, list(tb_records),
                                        ProfileService.get_or_create_profile(db, engagement.id)).status != STOP)
    if not has_opening:
        reasons.append("no opening balances (upload last year's TB; fine only in the first year)")
    critical = db.query(AuditFinding).filter(AuditFinding.engagement_id == engagement.id, AuditFinding.status == "OPEN",
                                             AuditFinding.severity == "CRITICAL").count()
    if critical:
        reasons.append(f"{critical} critical point{'' if critical == 1 else 's'} open")
    undecided = db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement.id,
                                                 ProposedJournal.status == "PROPOSED").count()
    if undecided:
        reasons.append(f"{undecided} journal{'' if undecided == 1 else 's'} not yet approved or rejected")
    # The Data check's warnings: a report missing or not agreeing to the books (the Data check tab lists them)
    try:
        from backend.app.services.setup.data_check import WARNING, data_check
        warned = sorted({i["label"].split(":")[0] for i in data_check(db, engagement)["items"] if i["status"] == WARNING})
        if warned:
            reasons.append("data check: " + ", ".join(w.lower() for w in warned))
    except Exception:
        pass
    return "; ".join(reasons)


@router.post("/generate/{engagement_id}", response_model=WorkpaperGenerationResponse)
def generate_master_workpapers(engagement_id: str, db: Session = Depends(get_db)):
    """Generate the master workpaper file. Refused (409, with what is left) until the setup is answered, every
    account is checked and the review has run since the last change: a workbook built earlier is of no use."""
    stmt_eng = select(ClientEngagement).where(ClientEngagement.id == engagement_id)
    engagement = db.execute(stmt_eng).scalar_one_or_none()
    if not engagement:
        raise HTTPException(status_code=404, detail="Engagement not found")

    stmt_tb = select(TBRecord).where(TBRecord.engagement_id == engagement_id)
    tb_records = db.execute(stmt_tb).scalars().all()
    if not tb_records:
        raise HTTPException(status_code=400, detail="No TB records found to generate workpapers")

    from backend.app.api.endpoints.engagements import build_blockers
    blockers = build_blockers(db, engagement, tb_records)
    if blockers:
        raise HTTPException(status_code=409, detail={"message": "Not ready to build the workbook", "blockers": blockers})
    draft_note = None

    # A client with no accounting software (bank statement + Dext): the accountant's own working-paper layout
    from backend.app.services.bank_only.books import is_books_client
    if is_books_client(engagement):
        from backend.app.services.bank_only.workbook import BooksChanged, build_books_workbook
        try:
            workpaper = build_books_workbook(engagement, db)
        except BooksChanged as e:
            raise HTTPException(status_code=409, detail={"message": "Not ready to build the workbook", "blockers": [str(e)]})
        return WorkpaperGenerationResponse(
            engagement_id=engagement.id,
            filename=workpaper.filename,
            download_url=f"/api/workpapers/download/{workpaper.id}",
            file_size_bytes=workpaper.file_size_bytes,
            diagnostics_score=workpaper.diagnostics_score
        )

    from backend.app.models.database import ProposedJournal

    # Load approved journals for this engagement
    approved_journals = db.execute(
        select(ProposedJournal).where(
            ProposedJournal.engagement_id == engagement_id,
            ProposedJournal.status == "APPROVED"
        ).order_by(ProposedJournal.id.asc())
    ).scalars().all()
    # Each journal once: an approved twin of an earlier one is left out of the workbook
    from backend.app.services.review.journal_guard import once_each
    approved_journals, _twins = once_each(approved_journals)

    # One record per journal line, with its source and status, as the test runner builds them
    from backend.app.services.workbook.journal_lines import workbook_journals
    formatted_journals = workbook_journals(db, approved_journals) if approved_journals else None

    draft_note = draft_reasons(db, engagement, list(tb_records)) or None

    # Generate master workpaper
    workpaper = excel_service.generate_master_workpapers(
        engagement=engagement,
        tb_records=list(tb_records),
        gl_df=pd.DataFrame(),
        journals=formatted_journals,
        db=db,
        draft_note=draft_note,
    )

    return WorkpaperGenerationResponse(
        engagement_id=engagement.id,
        filename=workpaper.filename,
        download_url=f"/api/workpapers/download/{workpaper.id}",
        file_size_bytes=workpaper.file_size_bytes,
        diagnostics_score=workpaper.diagnostics_score
    )

@router.get("/history/{engagement_id}")
def list_workpapers(engagement_id: str, db: Session = Depends(get_db)):
    """Every workbook built for this client, newest first (the Workbook tab lists earlier versions)."""
    rows = db.execute(
        select(GeneratedWorkpaper).where(GeneratedWorkpaper.engagement_id == engagement_id)
        .order_by(GeneratedWorkpaper.generated_at.desc())
    ).scalars().all()
    return [{
        "id": wp.id,
        "filename": wp.filename,
        "generated_at": wp.generated_at.strftime("%d %b %Y, %H:%M") if wp.generated_at else None,
        "is_draft": wp.filename.upper().endswith("_DRAFT.XLSX"),
        "file_size_bytes": wp.file_size_bytes or 0,
        "download_url": f"/api/workpapers/download/{wp.id}",
    } for wp in rows]


@router.get("/download/{workpaper_id}")
def download_master_workpaper(workpaper_id: int, db: Session = Depends(get_db)):
    """Download the generated Excel file from S3 / local storage."""
    stmt_wp = select(GeneratedWorkpaper).where(GeneratedWorkpaper.id == workpaper_id)
    wp = db.execute(stmt_wp).scalar_one_or_none()
    if not wp:
        raise HTTPException(status_code=404, detail="Workpaper not found")

    file_bytes = s3_service.download_file_bytes(wp.storage_path)
    if file_bytes is None:
        raise HTTPException(status_code=404, detail="The workbook file is no longer available: build it again")

    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{wp.filename}"'}
    )
