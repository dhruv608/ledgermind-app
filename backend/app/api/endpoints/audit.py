from fastapi import APIRouter, Depends, HTTPException, Request
from backend.app.core.errors import OutOfDate
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from typing import List, Optional

from pydantic import BaseModel
from datetime import datetime
from backend.app.core.database import get_db
from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, JournalLine, MasterCOA
from backend.app.models.schemas import (
    AuditFindingSchema,
    AuditExecutionResponse,
    ProposedJournalSchema,
    JournalActionRequest,
    ManualJournalCreateRequest,
    SequentialReviewResponse,
    ClearFindingRequest,
)
from backend.app.services.shared.activity import mark_changed
from backend.app.services.review.review_engine import SequentialReviewEngine

router = APIRouter()

@router.get("/{engagement_id}", response_model=AuditExecutionResponse)
def get_audit_findings(engagement_id: str, db: Session = Depends(get_db)):
    """All review findings for a client engagement."""
    stmt = select(AuditFinding).where(AuditFinding.engagement_id == engagement_id).order_by(AuditFinding.id.asc())
    findings = db.execute(stmt).scalars().all()
    
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        sev = f.severity.upper() if f.severity else "MEDIUM"
        sev_counts[sev] = sev_counts.get(sev, 0) + 1

    return AuditExecutionResponse(
        engagement_id=engagement_id,
        total_findings=len(findings),
        findings_by_severity=sev_counts,
        findings=[AuditFindingSchema.model_validate(f) for f in findings]
    )

@router.post("/{engagement_id}/run-sequential", response_model=SequentialReviewResponse)
def run_sequential_review(engagement_id: str, force: bool = False, db: Session = Depends(get_db)):
    """
    Executes the 3-stage statutory review pipeline:
    Stage 1: Accounting Lead Schedules & Working Papers
    Stage 2: VAT review (returns against the ledger, VAT guide)
    Stage 3: Corporation Tax CT600 & Locked PBT
    """
    # Engagement Setup: the review cannot start while a blocking gap remains (force is for test scripts only)
    if not force:
        from backend.app.services.setup.engagement_setup import setup_status
        from backend.app.services.setup.profile_service import ProfileService
        eng = db.get(ClientEngagement, engagement_id)
        if eng is None:
            raise HTTPException(status_code=404, detail="Engagement not found")
        gaps = setup_status(eng, ProfileService.get_or_create_profile(db, engagement_id), db)["gaps"]
        if gaps:
            raise HTTPException(status_code=409, detail={"message": "Finish the client setup first", "gaps": gaps})
    try:
        result = SequentialReviewEngine.run_full_sequential_review(engagement_id, db)
        
        # Load fresh findings and journals
        findings = db.execute(
            select(AuditFinding).where(AuditFinding.engagement_id == engagement_id).order_by(AuditFinding.id.asc())
        ).scalars().all()

        journals = db.execute(
            select(ProposedJournal).where(ProposedJournal.engagement_id == engagement_id).order_by(ProposedJournal.id.asc())
        ).scalars().all()

        return SequentialReviewResponse(
            engagement_id=engagement_id,
            total_findings=result["total_findings"],
            total_journals=result["total_journals"],
            stages=result["stages"],
            tax_computation=result.get("tax_computation"),
            findings=[AuditFindingSchema.model_validate(f) for f in findings],
            journals=[ProposedJournalSchema.model_validate(j) for j in journals],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Review engine failed: {str(e)}")

@router.get("/{engagement_id}/journals", response_model=List[ProposedJournalSchema])
def get_proposed_journals(engagement_id: str, db: Session = Depends(get_db)):
    """All proposed and approved journals for this engagement."""
    stmt = select(ProposedJournal).where(ProposedJournal.engagement_id == engagement_id).order_by(ProposedJournal.id.asc())
    journals = db.execute(stmt).scalars().all()
    return [ProposedJournalSchema.model_validate(j) for j in journals]

def _manual_journal_fields(request: ManualJournalCreateRequest, db: Session) -> dict:
    """Check an accountant's journal (description, 2+ lines, debit or credit per line, balanced) and build its fields."""
    description = request.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="A journal needs a description")

    lines = [l for l in request.lines if round(l.debit or 0, 2) or round(l.credit or 0, 2)]
    if len(lines) < 2:
        raise HTTPException(status_code=400, detail="A journal needs at least two lines with an amount")
    for i, l in enumerate(lines, start=1):
        if l.debit < 0 or l.credit < 0 or (round(l.debit, 2) and round(l.credit, 2)):
            raise HTTPException(status_code=400, detail=f"Line {i}: enter either a debit or a credit, as a positive amount")
    total_dr = round(sum(l.debit for l in lines), 2)
    total_cr = round(sum(l.credit for l in lines), 2)
    if total_dr != total_cr:
        raise HTTPException(status_code=400, detail=f"Journal does not balance: debits £{total_dr:,.2f}, credits £{total_cr:,.2f}")

    chart = {c.std_code: c.std_name for c in db.execute(select(MasterCOA)).scalars().all()}
    first_dr = next(l for l in lines if l.debit)
    first_cr = next(l for l in lines if l.credit)
    return dict(
        description=description,
        # summary fields kept for screens that show a single debit / credit
        debit_code=first_dr.account_code,
        debit_name=chart.get(first_dr.account_code, "Not in firm chart"),
        credit_code=first_cr.account_code,
        credit_name=chart.get(first_cr.account_code, "Not in firm chart"),
        amount=total_dr,
        lines=[
            JournalLine(
                line_no=i,
                account_code=l.account_code,
                account_name=chart.get(l.account_code, "Not in firm chart"),
                narrative=(l.narrative or "").strip() or None,
                debit=round(l.debit, 2),
                credit=round(l.credit, 2),
            )
            for i, l in enumerate(lines, start=1)
        ],
    )


@router.post("/{engagement_id}/journals", response_model=ProposedJournalSchema)
def create_manual_journal(engagement_id: str, request: ManualJournalCreateRequest, db: Session = Depends(get_db)):
    """Create an adjusting journal entered by an accountant (any number of lines, debits must equal credits)."""
    if not db.get(ClientEngagement, engagement_id):
        raise HTTPException(status_code=404, detail="Engagement not found")
    journal = add_manual_journal(db, engagement_id, request)
    mark_changed(db, engagement_id)
    return ProposedJournalSchema.model_validate(journal)


def add_manual_journal(db: Session, engagement_id: str, request: ManualJournalCreateRequest) -> ProposedJournal:
    """Saves an accountant's journal as PROPOSED with the next MJ number (also used by the GL scrutiny screen)."""
    fields = _manual_journal_fields(request, db)
    manual_count = db.execute(
        select(ProposedJournal).where(ProposedJournal.engagement_id == engagement_id, ProposedJournal.source == "MANUAL")
    ).scalars().all()
    journal = ProposedJournal(
        engagement_id=engagement_id,
        stage="MANUAL",
        journal_ref=f"MJ{len(manual_count) + 1:02d}",
        status="PROPOSED",
        source="MANUAL",
        **fields,
    )
    db.add(journal)
    db.commit()
    db.refresh(journal)
    return journal


@router.put("/journals/{journal_id}", response_model=ProposedJournalSchema)
def update_manual_journal(journal_id: int, request: ManualJournalCreateRequest, db: Session = Depends(get_db)):
    """Change an accountant-entered journal that has not been approved (same checks as a new one)."""
    journal = db.get(ProposedJournal, journal_id)
    if not journal:
        raise OutOfDate("LM updated this journal after your last change.", next="Reload to see it as it is now.")
    if journal.source != "MANUAL" or journal.status == "APPROVED":
        raise HTTPException(status_code=400, detail="Only unapproved journals entered by an accountant can be changed")
    fields = _manual_journal_fields(request, db)
    journal.lines.clear()
    db.flush()
    for key, value in fields.items():
        setattr(journal, key, value)
    journal.status = "PROPOSED"
    db.commit()
    db.refresh(journal)
    mark_changed(db, journal.engagement_id)
    return ProposedJournalSchema.model_validate(journal)

@router.delete("/journals/{journal_id}")
def delete_manual_journal(journal_id: int, db: Session = Depends(get_db)):
    """Delete an accountant-entered journal that has not been approved."""
    journal = db.get(ProposedJournal, journal_id)
    if not journal:
        raise OutOfDate("LM updated this journal after your last change.", next="Reload to see it as it is now.")
    if journal.source != "MANUAL" or journal.status == "APPROVED":
        raise HTTPException(status_code=400, detail="Only unapproved journals entered by an accountant can be deleted")
    engagement_id = journal.engagement_id
    db.delete(journal)
    db.commit()
    mark_changed(db, engagement_id)
    return {"status": "SUCCESS", "journal_id": journal_id}

@router.post("/journals/{journal_id}/action")
def act_on_journal(journal_id: int, request: JournalActionRequest, db: Session = Depends(get_db)):
    """Approve or Reject a proposed double-entry journal"""
    stmt = select(ProposedJournal).where(ProposedJournal.id == journal_id)
    journal = db.execute(stmt).scalar_one_or_none()
    if not journal:
        raise OutOfDate("LM updated this journal after your last change.", next="Reload to see it as it is now.")

    new_status = "APPROVED" if request.action.upper() == "APPROVE" else "REJECTED"
    if new_status == "APPROVED":
        from backend.app.services.review.journal_guard import approved_twin
        twin = approved_twin(db, journal)
        if twin is not None:
            # The same codes, amounts and narrative already approved: never posted twice
            raise HTTPException(status_code=409, detail=f"The same journal is already approved as {twin.journal_ref}: "
                                                        f"it is not posted twice.")
    journal.status = new_status
    if new_status == "APPROVED":
        journal.posted_at = datetime.utcnow()
    db.commit()
    mark_changed(db, journal.engagement_id)

    return {
        "status": "SUCCESS",
        "journal_id": journal_id,
        "new_status": new_status,
        "message": f"Journal {journal.journal_ref} ({journal.description}) set to {new_status}."
    }

class JournalEditAsLine(BaseModel):
    amount: float
    description: str = ""
    cost_code: Optional[int] = None


@router.post("/journals/{journal_id}/edit-as-line")
def edit_journal_as_line(journal_id: int, body: JournalEditAsLine, request: Request, db: Session = Depends(get_db)):
    """An accrual or prepayment the app proposed, with the accountant's amount, description and cost: it becomes their
    own line on the accruals and prepayments panel and the app's proposal is replaced (services/review/
    adjustment_edit.py). The checks are run again by the screen, which proposes the journal from the line."""
    from backend.app.services.review.adjustment_edit import edit_into_line
    journal = db.get(ProposedJournal, journal_id)
    if journal is None:
        raise OutOfDate("LM updated this journal after your last change.", next="Reload to see it as it is now.")
    if body.cost_code is not None and db.get(MasterCOA, body.cost_code) is None:
        raise HTTPException(status_code=400, detail=f"Account {body.cost_code} is not in the chart")
    user = getattr(request.state, "user", None)
    try:
        line = edit_into_line(db, journal, body.amount, body.description, body.cost_code, getattr(user, "id", None))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    mark_changed(db, journal.engagement_id)
    return {"status": "SUCCESS", "line": {"id": line.id, "kind": line.kind, "cost_code": line.cost_code,
                                          "amount": float(line.amount), "description": line.description},
            "message": f"{line.kind.title()} of £{float(line.amount):,.2f} saved as your line; the checks propose its "
                       f"journal."}


@router.post("/{finding_id}/clear")
def clear_audit_finding(finding_id: int, payload: ClearFindingRequest | None = None, db: Session = Depends(get_db)):
    """Mark a review finding as cleared."""
    stmt = select(AuditFinding).where(AuditFinding.id == finding_id)
    finding = db.execute(stmt).scalar_one_or_none()
    if not finding:
        # LM's check after a change replaces its points: the screen holds one that is gone
        raise OutOfDate("LM updated this point after your last change.", next="Reload to see it as it is now.")
    
    update_stmt = (
        update(AuditFinding)
        .where(AuditFinding.id == finding_id)
        .values(status="CLEARED", cleared_at=datetime.utcnow(), cleared_note=((payload.note or "").strip() or None) if payload else None)
    )
    db.execute(update_stmt)
    db.commit()
    return {"status": "SUCCESS", "message": f"Finding #{finding_id} cleared."}


@router.get("/{engagement_id}/export")
def export_review(engagement_id: str, request: Request, format: str = "pdf", include: str = "all", stage: str = "",
                  severity: str = "", db: Session = Depends(get_db)):
    """The Review tab's download: the review points as a PDF report or an Excel list (include: all, open, screen
    or screen_open, the last two with the tab's stage and severity)."""
    from backend.app.services.review.review_export import review_export
    eng = db.get(ClientEngagement, engagement_id)
    if eng is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    user = getattr(request.state, "user", None)
    data, filename, media = review_export(db, eng, "xlsx" if format == "xlsx" else "pdf", include, stage, severity,
                                          made_by=(getattr(user, "name", "") or getattr(user, "email", "")) if user else "")
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ------------------------------------------------------------------------------------------------------------------
# Sign-off per point (preparer, reviewer, partner), kept by the point's content so it survives a re-run of the checks
# ------------------------------------------------------------------------------------------------------------------
def _signoffs(db: Session, engagement_id: str) -> dict:
    """{finding id: [{role, initials, signed_at}]} for the job's current points."""
    from backend.app.models.point_signoffs import PointSignoff, point_key
    by_key: dict = {}
    for s in db.query(PointSignoff).filter(PointSignoff.engagement_id == engagement_id).all():
        by_key.setdefault(s.point_key, []).append({"role": s.role, "initials": s.initials,
                                                   "signed_at": s.signed_at.isoformat() if s.signed_at else None})
    out = {}
    for f in db.query(AuditFinding).filter(AuditFinding.engagement_id == engagement_id).all():
        got = by_key.get(point_key(f.procedure_ref, f.finding_title, f.source_row_ref))
        if got:
            out[f.id] = got
    return out


@router.get("/{engagement_id}/signoffs")
def get_signoffs(engagement_id: str, db: Session = Depends(get_db)):
    return _signoffs(db, engagement_id)


@router.post("/{engagement_id}/signoffs")
def sign_off_point(engagement_id: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    """{finding_id, role, clear}: signs the point off in that role with the signed-in user's initials, or clears it."""
    from backend.app.models.point_signoffs import ROLES, PointSignoff, initials_of, point_key
    role = str(payload.get("role") or "").upper()
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Role must be preparer, reviewer or partner")
    finding = db.get(AuditFinding, int(payload.get("finding_id") or 0))
    if not finding or finding.engagement_id != engagement_id:
        raise HTTPException(status_code=404, detail="Point not found")
    key = point_key(finding.procedure_ref, finding.finding_title, finding.source_row_ref)
    row = db.query(PointSignoff).filter(PointSignoff.engagement_id == engagement_id, PointSignoff.point_key == key,
                                        PointSignoff.role == role).first()
    if payload.get("clear"):
        if row:
            db.delete(row)
    else:
        user = getattr(request.state, "user", None)
        initials = initials_of(getattr(user, "name", "") or "", getattr(user, "email", "") or "")
        if row:
            row.user_id, row.initials, row.signed_at = getattr(user, "id", None), initials, datetime.utcnow()
        else:
            db.add(PointSignoff(engagement_id=engagement_id, point_key=key, role=role, user_id=getattr(user, "id", None),
                                initials=initials, signed_at=datetime.utcnow()))
    db.commit()      # nothing the checks read: no re-run
    return _signoffs(db, engagement_id)


def _area_signoffs(db: Session, engagement_id: str) -> dict:
    """{area: [{role, initials, signed_at, fingerprint}]}"""
    from backend.app.models.point_signoffs import AreaSignoff
    out: dict = {}
    for s in db.query(AreaSignoff).filter(AreaSignoff.engagement_id == engagement_id).all():
        out.setdefault(s.area, []).append({"role": s.role, "initials": s.initials, "fingerprint": s.fingerprint,
                                           "signed_at": s.signed_at.isoformat() if s.signed_at else None})
    return out


@router.get("/{engagement_id}/area-signoffs")
def get_area_signoffs(engagement_id: str, db: Session = Depends(get_db)):
    return _area_signoffs(db, engagement_id)


@router.post("/{engagement_id}/area-signoffs")
def sign_off_area(engagement_id: str, payload: dict, request: Request, db: Session = Depends(get_db)):
    """{area, role, clear, fingerprint}: signs the whole area off in that role, in order (the reviewer after the
    preparer, the partner after the reviewer), or takes a sign-off off (the later ones first)."""
    from backend.app.models.point_signoffs import ROLES, AreaSignoff, initials_of
    role = str(payload.get("role") or "").upper()
    area = str(payload.get("area") or "")[:20]
    if role not in ROLES or not area:
        raise HTTPException(status_code=400, detail="Area and role (preparer, reviewer or partner) needed")
    rows = {s.role: s for s in db.query(AreaSignoff).filter(AreaSignoff.engagement_id == engagement_id,
                                                            AreaSignoff.area == area).all()}
    at = ROLES.index(role)
    if payload.get("clear"):
        later = [r for r in ROLES[at + 1:] if r in rows]
        if later:
            raise HTTPException(status_code=409, detail=f"Take the {later[-1].lower()}'s sign-off off first")
        if role in rows:
            db.delete(rows[role])
    else:
        missing = [r for r in ROLES[:at] if r not in rows]
        if missing:
            raise HTTPException(status_code=409, detail=f"The {missing[0].lower()} signs off first")
        user = getattr(request.state, "user", None)
        initials = initials_of(getattr(user, "name", "") or "", getattr(user, "email", "") or "")
        row = rows.get(role) or AreaSignoff(engagement_id=engagement_id, area=area, role=role)
        row.user_id, row.initials, row.signed_at = getattr(user, "id", None), initials, datetime.utcnow()
        row.fingerprint = str(payload.get("fingerprint") or "")[:40] or None
        db.add(row)
    db.commit()      # nothing the checks read: no re-run
    return _area_signoffs(db, engagement_id)
