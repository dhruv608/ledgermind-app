"""A client (engagement): the clients list, the client's details and status, its ledger lines, deleting clients. The
client's other screens have their own files under the same /engagements address: profile_setup, capital_allowances,
reconciliations, cis, supplementary."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import bindparam, select, func, delete, or_, and_, case
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from backend.app.core.database import get_db
from backend.app.core.s3 import s3_service
from backend.app.models.database import ClientEngagement, TBRecord, AuditFinding, GeneratedWorkpaper, GLTransaction, VAT100Record
import calendar
from datetime import date, datetime, timedelta
import json
import re
from types import SimpleNamespace
from backend.app.models.schemas import IngestionResponse, TBRecordSchema, ClientProfileSchema
from backend.app.services.setup.profile_service import ProfileService
from backend.app.services.shared.activity import freshness

router = APIRouter()

class ClientListItem(BaseModel):
    engagement_id: str
    client_name: str
    period_end_date: str
    source_system: str
    is_vat_registered: Optional[bool] = False
    total_tb_rows: int
    mappings_to_review: int = 0
    open_audit_findings: int
    created_at: str
    latest_workpaper_id: Optional[int] = None
    workbook_state: str = "none"  # none, draft, final
    setup_confirmed: bool = False
    review_stale: bool = True
    workbook_stale: bool = False
    last_activity_at: Optional[str] = None
    company_key: str = ""         # the same company's years share it: its Companies House number, else its name
    company_number: str = ""      # from Companies House, when known
    accounts_due: Optional[str] = None  # yyyy-mm-dd: the accounts filing deadline at Companies House
    vat_period_end: Optional[str] = None  # yyyy-mm-dd: the next VAT return's period end (from the returns entered)
    vat_due: Optional[str] = None         # yyyy-mm-dd: when that return and its payment are due at HMRC
    checking: Optional[str] = None        # the checks running in the background: "6 of 13" (None when not running)


def _company_keys(engagements: List[ClientEngagement]) -> Dict[str, str]:
    """Each job's company: the Companies House number when the job or another job of the same name has one, else
    the name without Ltd / Limited ('AcmeLtd' and 'Acme LTD' are one company)."""
    from backend.app.services.ingestion.client_identity import company_key

    def name_key(name: str) -> str:
        return re.sub(r"(limited|ltd|plc|llp)$", "", company_key(name).replace(" ", "")) or company_key(name)

    def number(eng: ClientEngagement) -> str:
        try:
            found = json.loads(eng.profile.companies_house or "{}") if eng.profile else {}
        except ValueError:
            found = {}
        return str(found.get("company_number") or "").strip().upper()

    by_name = {name_key(e.client_name): number(e) for e in engagements if number(e)}
    return {e.id: f"ch:{number(e) or by_name.get(name_key(e.client_name), '')}"
            if (number(e) or by_name.get(name_key(e.client_name))) else f"name:{name_key(e.client_name)}"
            for e in engagements}

def _add_months(d: date, months: int) -> date:
    """The same day so many months on; a month end stays a month end (31 Dec + 9 months = 30 Sep)."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    last = calendar.monthrange(y, m)[1]
    month_end = d.day == calendar.monthrange(d.year, d.month)[1]
    return date(y, m, last if month_end else min(d.day, last))


def accounts_due(eng: ClientEngagement) -> Optional[date]:
    """Companies House filing deadline for a private company (CA 2006 s442): 9 months after the year end. A first
    period longer than 12 months: 9 months from the first anniversary of incorporation (21 months) or 3 months after
    the year end, whichever is later (s442(3))."""
    ped = eng.period_end_date
    if ped is None:
        return None
    try:
        register = json.loads(eng.profile.companies_house or "{}") if eng.profile is not None else {}
        formed = date.fromisoformat(str(register.get("incorporated"))[:10]) if register.get("incorporated") else None
    except (ValueError, TypeError, AttributeError):
        formed = None
    # The first period: formed after the last year end (or, with none, within the longest first period, 18 months,
    # s392(5)), and it runs past its first anniversary
    first = formed is not None and formed > (eng.prior_period_end_date or _add_months(ped, -18))
    if first and ped >= _add_months(formed, 12):
        return max(_add_months(formed, 21), _add_months(ped, 3))
    return _add_months(ped, 9)


def next_vat_return(last_start: Optional[date], last_end: date, today: date) -> tuple:
    """The company's next VAT return whose deadline has not passed, stepped on from the latest return entered:
    (period end, due date). Monthly and quarterly returns are due 1 month and 7 days after the period; an annual
    return 2 months after. The period length comes from the latest return (a quarter when its start is unknown)."""
    days = (last_end - last_start).days + 1 if last_start else 92
    months = 1 if days <= 40 else 12 if days >= 300 else 3

    def due(end: date) -> date:
        return _add_months(end, 2) if months == 12 else _add_months(end, 1) + timedelta(days=7)

    end = last_end
    while due(end) < today:
        end = _add_months(end, months)
    return end, due(end)


@router.get("", response_model=List[ClientListItem])
def list_client_engagements(request: Request, db: Session = Depends(get_db)):
    """The signed-in user's clients, with where each year-end stands. A few grouped queries, not several per client."""
    engagements = db.execute(
        select(ClientEngagement)
        .where(ClientEngagement.owner_user_id == request.state.user.id)
        .options(selectinload(ClientEngagement.profile))
        .order_by(ClientEngagement.created_at.desc())
    ).scalars().all()

    # Accounts per client, and the ones still needing a decision (a nil account changes no figure: never counted)
    not_nil = or_(
        func.abs(func.coalesce(TBRecord.net_amount, 0)) >= 0.005,
        func.abs(func.coalesce(TBRecord.debit_amount, 0)) >= 0.005,
        func.abs(func.coalesce(TBRecord.credit_amount, 0)) >= 0.005,
    )
    to_review = case((and_(TBRecord.mapping_status.in_(["NEEDS_REVIEW", "UNMAPPED"]), not_nil), 1), else_=0)
    tb_stats = {
        eid: (total, review or 0)
        for eid, total, review in db.execute(
            select(TBRecord.engagement_id, func.count(TBRecord.id), func.sum(to_review)).group_by(TBRecord.engagement_id)
        )
    }
    open_points = dict(db.execute(
        select(AuditFinding.engagement_id, func.count(AuditFinding.id))
        .where(AuditFinding.status == "OPEN", AuditFinding.procedure_ref != "CT-01")   # the tax computation is not a point
        .group_by(AuditFinding.engagement_id)
    ).all())
    with_tax = set(db.execute(
        select(AuditFinding.engagement_id).where(AuditFinding.procedure_ref.in_(("CT-01", "U-TB-001"))).distinct()
    ).scalars().all())
    # Latest workbook per client: newest first, keep the first seen
    latest_wp: Dict[str, Any] = {}
    for eid, wp_id, filename, generated_at in db.execute(
        select(GeneratedWorkpaper.engagement_id, GeneratedWorkpaper.id, GeneratedWorkpaper.filename, GeneratedWorkpaper.generated_at)
        .order_by(GeneratedWorkpaper.generated_at.desc())
    ):
        latest_wp.setdefault(eid, SimpleNamespace(id=wp_id, filename=filename, generated_at=generated_at))

    keys = _company_keys(engagements)
    # The latest VAT return entered for each company, whichever of its year-ends it was entered on
    latest_vat: Dict[str, tuple] = {}
    ids = {e.id for e in engagements}
    for eid, start, end in db.execute(select(VAT100Record.engagement_id, VAT100Record.period_start,
                                             VAT100Record.period_end).where(VAT100Record.period_end.isnot(None))):
        if eid in ids and (keys[eid] not in latest_vat or end > latest_vat[keys[eid]][1]):
            latest_vat[keys[eid]] = (start, end)
    # Clients whose checks are running in the background now (a run older than the runner's limit stopped with its server)
    from backend.app.models.check_runs import CheckRun
    from backend.app.services.checks.runner import STALE_AFTER, STEPS
    checking: Dict[str, str] = {}
    for eid, done in db.execute(select(CheckRun.engagement_id, CheckRun.steps_done)
                                .where(CheckRun.status == "RUNNING",
                                       CheckRun.started_at > datetime.utcnow() - STALE_AFTER)):
        if eid in ids:
            checking[eid] = f"{(done or 0) + 1} of {len(STEPS)}"
    today = date.today()
    results = []
    for eng in engagements:
        prof = eng.profile
        tb_count, review_count = tb_stats.get(eng.id, (0, 0))
        wp = latest_wp.get(eng.id)
        workbook_state = "none" if wp is None else ("draft" if wp.filename.upper().endswith("_DRAFT.XLSX") else "final")
        fresh = freshness(eng, eng.id in with_tax, wp, int(review_count))
        vat_next = next_vat_return(*latest_vat[keys[eng.id]], today)             if prof and prof.is_vat_registered and keys[eng.id] in latest_vat else None

        results.append(ClientListItem(
            engagement_id=eng.id,
            client_name=eng.client_name,
            period_end_date=eng.period_end_date.strftime("%d/%m/%Y") if eng.period_end_date else "-",
            source_system=eng.source_system or "XERO",
            is_vat_registered=bool(prof.is_vat_registered) if prof else False,
            total_tb_rows=tb_count,
            mappings_to_review=int(review_count),
            open_audit_findings=open_points.get(eng.id, 0),
            created_at=eng.created_at.strftime("%d %b %Y, %H:%M") if eng.created_at else "-",
            latest_workpaper_id=wp.id if wp else None,
            workbook_state=workbook_state,
            setup_confirmed=bool(prof and json.loads(prof.confirmed_fields or "[]")),
            review_stale=fresh["review_stale"],
            workbook_stale=fresh["workbook_stale"],
            last_activity_at=fresh["last_activity_at"],
            company_key=keys[eng.id],
            company_number=keys[eng.id][3:] if keys[eng.id].startswith("ch:") else "",
            accounts_due=(due.isoformat() if (due := accounts_due(eng)) else None),
            vat_period_end=vat_next[0].isoformat() if vat_next else None,
            vat_due=vat_next[1].isoformat() if vat_next else None,
            checking=checking.get(eng.id),
        ))

    return results

def _is_nil(r: TBRecord) -> bool:
    return all(abs(float(v or 0)) < 0.005 for v in (r.net_amount, r.debit_amount, r.credit_amount))


def _workbook_and_status(db: Session, eng: ClientEngagement, tb_records) -> tuple:
    """The last workbook built for this client and whether the review / workbook are up to date."""
    wp = db.execute(select(GeneratedWorkpaper).where(GeneratedWorkpaper.engagement_id == eng.id)
                    .order_by(GeneratedWorkpaper.generated_at.desc())).scalars().first()
    latest_workpaper = {
        "id": wp.id, "filename": wp.filename,
        "generated_at": wp.generated_at.strftime("%d %b %Y, %H:%M") if wp.generated_at else None,
        "is_draft": wp.filename.upper().endswith("_DRAFT.XLSX"),
        "download_url": f"/api/workpapers/download/{wp.id}",
    } if wp else None
    is_gate_or_ct = AuditFinding.procedure_ref.in_(("CT-01", "U-TB-001"))
    counts = dict(db.execute(
        select(is_gate_or_ct, func.count(AuditFinding.id))
        .where(AuditFinding.engagement_id == eng.id, or_(AuditFinding.status == "OPEN", is_gate_or_ct))
        .group_by(is_gate_or_ct)
    ).all())
    to_review = sum(1 for r in tb_records if r.mapping_status in ("NEEDS_REVIEW", "UNMAPPED") and not _is_nil(r))
    status = freshness(eng, bool(counts.get(True)), wp, to_review)
    status.update({"mappings_to_review": to_review, "has_tax_computation": bool(counts.get(True))})
    return latest_workpaper, status


def build_blockers(db: Session, eng: ClientEngagement, tb_records=None) -> List[str]:
    """What must be done before the workbook can be built, in the order of the tabs: the setup answered, every
    account checked, and the review run since the last change. Empty when the workbook can be built."""
    from backend.app.services.setup.engagement_setup import setup_status
    from backend.app.services.setup.profile_service import ProfileService
    if tb_records is None:
        tb_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == eng.id)).scalars().all()
    _, status = _workbook_and_status(db, eng, tb_records)
    gaps = setup_status(eng, ProfileService.get_or_create_profile(db, eng.id), db)["gaps"]
    out = []
    # Data check first: a figure that cannot be right (TB out of balance, no opening balances, a file read as nothing)
    from backend.app.services.setup.data_check import hard_stops
    for stop in hard_stops(db, eng, tb_records):
        out.append(f"Files: {stop.label}: {stop.detail}")
    if gaps:
        out.append(f"Setup: {len(gaps)} answer{'' if len(gaps) == 1 else 's'} missing")
    if status["mappings_to_review"]:
        out.append(f"Accounts: {status['mappings_to_review']} to check")
    if status["review_stale"]:
        out.append("Review: run it" + (" again (something changed)" if status["review_run_at"] and status["has_tax_computation"] else ""))
    return out


@router.get("/{engagement_id}/status")
def get_engagement_status(engagement_id: str, db: Session = Depends(get_db)):
    """Light: whether the review and the workbook are up to date, and the latest workbook (the client page asks after changes)."""
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    tb_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement_id)).scalars().all()
    latest_workpaper, status = _workbook_and_status(db, eng, tb_records)
    return {**status, "latest_workpaper": latest_workpaper, "build_blockers": build_blockers(db, eng, tb_records)}


@router.get("/{engagement_id}", response_model=IngestionResponse)
def get_engagement_details(engagement_id: str, db: Session = Depends(get_db)):
    """Full details of one engagement."""
    stmt_eng = select(ClientEngagement).where(ClientEngagement.id == engagement_id)
    eng = db.execute(stmt_eng).scalar_one_or_none()
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")

    stmt_tb = select(TBRecord).where(TBRecord.engagement_id == engagement_id).order_by(TBRecord.id.asc())
    tb_records = db.execute(stmt_tb).scalars().all()

    tb_net = sum(float(r.net_amount or 0.0) for r in tb_records)
    gl_count = db.execute(select(func.count(GLTransaction.id)).where(GLTransaction.engagement_id == engagement_id)).scalar() or 0

    # Profile
    profile = ProfileService.get_or_create_profile(db, engagement_id)
    profile_schema = ClientProfileSchema(
        engagement_id=profile.engagement_id,
        industry_code=profile.industry_code or "UNIV",
        is_vat_registered=bool(profile.is_vat_registered),
        vat_scheme=profile.vat_scheme or "STANDARD",
        has_payroll=bool(profile.has_payroll),
        cis_status=profile.cis_status or "NONE",
        directors=json.loads(profile.directors) if profile.directors else [],
        accounting_framework=profile.accounting_framework or "FRS102_1A",
        materiality_threshold=float(profile.materiality_threshold or 0.0),
        capitalisation_threshold=float(profile.capitalisation_threshold or 500.0),
        auto_detected=bool(profile.auto_detected),
        detection_signals=json.loads(profile.detection_signals) if profile.detection_signals else None,
        confirmed_fields=json.loads(profile.confirmed_fields) if profile.confirmed_fields else [],
        properties=json.loads(profile.properties) if profile.properties else [],
        tax_inputs=json.loads(profile.tax_inputs) if profile.tax_inputs else {},
        companies_house=json.loads(profile.companies_house) if profile.companies_house else {},
        setup=json.loads(profile.setup) if profile.setup else {},
    )

    latest_workpaper, status = _workbook_and_status(db, eng, tb_records)
    status["build_blockers"] = build_blockers(db, eng, tb_records)

    return IngestionResponse(
        engagement_id=eng.id,
        client_name=eng.client_name,
        period_end_date=eng.period_end_date.strftime("%d/%m/%Y") if eng.period_end_date else "-",
        source_system=eng.source_system or "XERO",
        total_tb_rows=len(tb_records),
        total_gl_rows=gl_count,
        tb_net_balance=round(tb_net, 2),
        tb_records=[TBRecordSchema.model_validate(r) for r in tb_records],
        profile=profile_schema,
        latest_workpaper=latest_workpaper,
        status=status,
    )


class GLTransactionSchema(BaseModel):
    id: int
    raw_account_name: str
    transaction_date: Optional[str] = None
    description: Optional[str] = None
    reference: Optional[str] = None
    source: Optional[str] = None
    debit_amount: float
    credit_amount: float
    net_amount: float

@router.get("/{engagement_id}/transactions", response_model=List[GLTransactionSchema])
def get_engagement_transactions(
    engagement_id: str,
    account_name: Optional[str] = None,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    """General ledger lines for an engagement, or for one account."""
    stmt = select(GLTransaction).where(GLTransaction.engagement_id == engagement_id)
    
    if account_name:
        from backend.app.services.mapping.chart_lookup import account_name_keys
        leaf = account_name.split(":")[-1].strip().lower()

        # 1. The same account by name as the rest of the app matches TB and ledger: the full name, then without the
        #    client's code in front ('5300 - VAT Control' in the TB is 'VAT Control' in a QuickBooks ledger), then
        #    the part after the last ':'
        rows = []
        for key in account_name_keys(account_name):
            match_stmt = stmt.where(func.lower(func.trim(GLTransaction.raw_account_name)) == key)
            rows = db.execute(match_stmt.order_by(GLTransaction.transaction_date.desc(), GLTransaction.id.desc()).limit(limit)).scalars().all()
            if rows:
                break

        # 2. Leaf / normalized whitespace fallback if no direct matches
        if not rows:
            leaf_stmt = stmt.where(
                or_(
                    func.lower(func.trim(GLTransaction.raw_account_name)) == leaf,
                    func.replace(func.lower(func.trim(GLTransaction.raw_account_name)), '  ', ' ') == leaf,
                    func.lower(func.trim(GLTransaction.raw_account_name)).like(f"%{leaf}%")
                )
            )
            rows = db.execute(leaf_stmt.order_by(GLTransaction.transaction_date.desc(), GLTransaction.id.desc()).limit(limit)).scalars().all()
    else:
        rows = db.execute(stmt.order_by(GLTransaction.transaction_date.desc(), GLTransaction.id.desc()).limit(limit)).scalars().all()

    return [
        GLTransactionSchema(
            id=r.id,
            raw_account_name=r.raw_account_name,
            transaction_date=r.transaction_date.strftime("%d/%m/%Y") if r.transaction_date else "-",
            description=r.description or "",
            reference=r.reference or "",
            source=r.source or "",
            debit_amount=float(r.debit_amount or 0.0),
            credit_amount=float(r.credit_amount or 0.0),
            net_amount=float(r.net_amount or 0.0),
        )
        for r in rows
    ]

# Kept when a client is deleted: the firm's memory of approved codes per merchant (it codes the next client too)
KEEP_ON_DELETE = {"merchant_memory"}


def _client_tables():
    """Every table that holds a client's rows, children before parents: found from the models themselves, so a new
    table is never missed. Each comes as (table, how its rows belong to the client)."""
    import importlib
    import pkgutil
    import backend.app.models as models
    from backend.app.core.database import Base
    for m in pkgutil.iter_modules(models.__path__):          # every model, also those only imported on first use
        importlib.import_module(f"backend.app.models.{m.name}")
    tables = Base.metadata.tables
    journals = select(tables["proposed_journals"].c.id).where(tables["proposed_journals"].c.engagement_id.in_(bindparam("ids", expanding=True)))
    chats = select(tables["chat_sessions"].c.id).where(tables["chat_sessions"].c.engagement_id.in_(bindparam("ids", expanding=True)))
    children, parents = [], []
    for t in reversed(Base.metadata.sorted_tables):        # children first, for the foreign keys
        if t.name == "client_engagements" or t.name in KEEP_ON_DELETE:
            continue
        cols = t.c
        if "engagement_id" in cols:
            parents.append((t, cols.engagement_id.in_(bindparam("ids", expanding=True))))
        elif "journal_id" in cols:
            children.append((t, cols.journal_id.in_(journals)))
        elif "session_id" in cols:
            children.append((t, cols.session_id.in_(chats)))
    # Rows found through a journal or a chat go first, while their journal or chat is still there to find them by
    return children + parents


def _delete_engagements(db: Session, ids: List[str]) -> None:
    """Every row of these clients in every table (see _client_tables), the assistant's files of their chats, then
    the clients themselves."""
    from backend.app.models.chat import ChatSession
    from backend.app.api.endpoints.assistant import delete_chat_files
    delete_chat_files(db, db.execute(select(ChatSession.id).where(ChatSession.engagement_id.in_(ids))).scalars().all())
    for table, belongs in _client_tables():
        db.execute(table.delete().where(belongs), {"ids": list(ids)})
    db.execute(delete(ClientEngagement).where(ClientEngagement.id.in_(ids)))
    db.commit()


@router.delete("/{engagement_id}")
def delete_client_engagement(engagement_id: str, db: Session = Depends(get_db)):
    """Delete a client engagement and all its records."""
    stmt_eng = select(ClientEngagement).where(ClientEngagement.id == engagement_id)
    eng = db.execute(stmt_eng).scalar_one_or_none()
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")

    _delete_engagements(db, [engagement_id])

    # Clean up associated files from S3 and local storage
    s3_service.delete_engagement_files(engagement_id)

    return {"status": "success", "message": f"Engagement {engagement_id} and associated files deleted successfully"}

class BulkDeleteRequest(BaseModel):
    engagement_ids: List[str]

@router.post("/bulk-delete")
def bulk_delete_client_engagements(payload: BulkDeleteRequest, request: Request, db: Session = Depends(get_db)):
    """Delete several client engagements and all their records (only the user's own)."""
    ids = [e.id for e in db.execute(select(ClientEngagement).where(
        ClientEngagement.id.in_(payload.engagement_ids or []),
        ClientEngagement.owner_user_id == request.state.user.id)).scalars()]
    if not ids:
        return {"status": "success", "deleted_count": 0}

    _delete_engagements(db, ids)

    for eid in ids:
        s3_service.delete_engagement_files(eid)          # logs a failure itself

    return {"status": "success", "deleted_count": len(ids)}
