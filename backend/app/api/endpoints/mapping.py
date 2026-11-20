import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from backend.app.api.deps import owned_engagement
from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import Session
from typing import List
from backend.app.services.shared.activity import mark_changed
from backend.app.core.database import get_db
from backend.app.models.database import MasterCOA, MappingMemory, TBRecord
from backend.app.models.schemas import (
    MasterCOASchema,
    MappingUpdateRequest,
    MappingResetRequest,
    MappingConfirmRequest,
)
from backend.app.services.mapping.mapping_service import mapping_service, SUSPENSE_CODE

router = APIRouter()


def teaches_memory(record: TBRecord | None, coa: MasterCOA | None, new_code: bool = False) -> bool:
    """A code the app flagged on this account, or one its balance contradicts (e.g. a cost code well in credit: a sales
    account coded as a cost), is kept for this client only: the firm's memory does not give it to other clients."""
    if record is None or coa is None:
        return True
    if not new_code and (record.mapping_reason or "").startswith("Check:"):
        return False
    name = re.sub(r"^\d+[\s\-_:]+", "", record.raw_account_name or "").lower()
    return mapping_service._nature_problem(name, float(record.net_amount or 0.0), coa) is None

@router.get("/master-coa", response_model=List[MasterCOASchema])
def get_master_chart_of_accounts(db: Session = Depends(get_db)):
    """Firm chart of accounts: the standard list plus the extended TaxCalc codes (is_extended)"""
    stmt = select(MasterCOA).order_by(MasterCOA.std_code.asc())
    return db.execute(stmt).scalars().all()

@router.post("/update")
def update_single_mapping(payload: MappingUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """Change one account of one of the user's clients, and remember the choice for the user's next uploads."""
    owned_engagement(db, request.state.user, payload.engagement_id)
    stmt_coa = select(MasterCOA).where(MasterCOA.std_code == payload.std_code)
    coa = db.execute(stmt_coa).scalar_one_or_none()
    if not coa:
        raise HTTPException(status_code=404, detail="Standard TaxCalc Code not found")

    record = db.execute(select(TBRecord).where(TBRecord.engagement_id == payload.engagement_id,
                                               TBRecord.raw_account_name == payload.raw_account_name)).scalars().first()
    if teaches_memory(record, coa, new_code=True):     # the old flag was about the old code
        mapping_service.confirm_and_save_mapping(payload.raw_account_name, payload.std_code, db, request.state.user.id)

    # This client's account only: another client's account with the same name keeps its own mapping
    where = [TBRecord.raw_account_name == payload.raw_account_name, TBRecord.engagement_id == payload.engagement_id]
    stmt_tb_update = (
        update(TBRecord)
        .where(*where)
        .values(
            std_code=payload.std_code,
            std_name=coa.std_name,
            mapping_status="MATCHED",
            confidence_score=1.0,
            match_source="MANUAL",
            mapping_reason="Set by an accountant."
        )
    )
    db.execute(stmt_tb_update)
    db.commit()
    records = db.execute(select(TBRecord).where(TBRecord.engagement_id == payload.engagement_id)).scalars().all()
    mapping_service.close_pl_openings(payload.engagement_id, list(records), db)
    db.commit()
    mark_changed(db, payload.engagement_id)

    return {"status": "SUCCESS", "message": f"Mapping saved for '{payload.raw_account_name}' -> Code {payload.std_code} ({coa.std_name})"}

@router.post("/options")
def mapping_options(payload: MappingConfirmRequest, request: Request, db: Session = Depends(get_db)):
    """The AI's top 3 codes for one account (the first name in raw_account_names), for a one-click choice."""
    owned_engagement(db, request.state.user, payload.engagement_id)
    if not payload.raw_account_names:
        raise HTTPException(status_code=400, detail="No account given")
    try:
        return mapping_service.suggest_options(payload.engagement_id, payload.raw_account_names[0], db)
    except Exception as e:  # the AI service can be busy; the accountant can still use Change
        raise HTTPException(status_code=502, detail=f"AI options not available: {str(e)[:150]}")


@router.post("/confirm")
def confirm_mappings(payload: MappingConfirmRequest, request: Request, db: Session = Depends(get_db)):
    """The accountant agrees with the code already on these accounts of this client: they no longer need review,
    and the mapping is remembered for future uploads."""
    owned_engagement(db, request.state.user, payload.engagement_id)
    names = set(payload.raw_account_names)
    bulk = len(names) > 1
    records = db.execute(select(TBRecord).where(TBRecord.engagement_id == payload.engagement_id)).scalars().all()
    coa_by_code = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars().all()}
    confirmed, done, in_suspense, to_check = 0, [], [], []
    for r in records:
        if r.raw_account_name not in names:
            continue
        if r.std_code is None or r.std_code == SUSPENSE_CODE:
            in_suspense.append(r.raw_account_name)          # needs a real code first
            continue
        if bulk and r.mapping_status == "NEEDS_REVIEW" and (r.mapping_reason or "").startswith("Check:"):
            to_check.append(r.raw_account_name)             # the code contradicts the account: one at a time
            continue
        # Only an account confirmed on its own teaches the firm's memory: a 'Confirm all' accepts this client's
        # suggestions without each being looked at, and must not carry them to every other client; nor does a code
        # that contradicts the account (this client's choice, not a rule for every client's account of that name)
        teach = not bulk and teaches_memory(r, coa_by_code.get(r.std_code))
        r.mapping_status = "MATCHED"
        r.confidence_score = 1.0
        r.match_source = "CONFIRMED"
        r.mapping_reason = "Confirmed by an accountant." if teach or bulk else \
            "Confirmed by an accountant for this client only (the code does not fit the account's name or balance)."
        if teach:
            mapping_service.confirm_and_save_mapping(r.raw_account_name, r.std_code, db, request.state.user.id)
        confirmed += 1
        done.append(r.raw_account_name)
    db.commit()
    mark_changed(db, payload.engagement_id)
    return {"status": "SUCCESS", "confirmed": confirmed, "confirmed_names": done,
            "skipped_suspense": in_suspense, "skipped_to_check": to_check}

@router.post("/reset-ai-suggestion")
def reset_to_ai_suggestion(payload: MappingResetRequest, request: Request, db: Session = Depends(get_db)):
    """Reset one account of one of the user's clients to the AI's answer, forgetting the user's saved choice."""
    owned_engagement(db, request.state.user, payload.engagement_id)
    clean_raw = payload.raw_account_name.strip().lower()

    # 1. Clear the user's remembered choice and this client's saved AI answer, so the AI is asked again
    db.execute(delete(MappingMemory).where(func.lower(func.trim(MappingMemory.client_account_name)) == clean_raw))
    mapping_service.forget_ai_answer(payload.raw_account_name, db, payload.engagement_id)
    db.commit()

    # 2. Re-resolve using AI mapping engine
    ai_mapping = mapping_service.resolve_account_mapping(payload.raw_account_name, db, payload.engagement_id)

    # 3. Update this client's account
    where = [TBRecord.raw_account_name == payload.raw_account_name, TBRecord.engagement_id == payload.engagement_id]
    stmt_tb_update = (
        update(TBRecord)
        .where(*where)
        .values(
            std_code=ai_mapping["std_code"],
            std_name=ai_mapping["std_name"],
            mapping_status=ai_mapping["mapping_status"],
            confidence_score=ai_mapping["confidence_score"],
            match_source=ai_mapping["match_source"],
            mapping_reason=ai_mapping["mapping_reason"],
        )
    )
    db.execute(stmt_tb_update)
    db.commit()
    mark_changed(db, payload.engagement_id)

    return {
        "status": "SUCCESS",
        "raw_account_name": payload.raw_account_name,
        "std_code": ai_mapping["std_code"],
        "std_name": ai_mapping["std_name"],
        "confidence_score": ai_mapping["confidence_score"],
    }


# ------------------------------------------------------------------------------------------------------------------
# The firm memory (Account rules page): the codes the firm's accountants confirmed, by account name, and removing one
# that is wrong (a test client's choice, a mistake): the next upload then asks the rules and the AI again
# ------------------------------------------------------------------------------------------------------------------
def _memory_key(name: str) -> str:
    """'0 - Savings by FRS' -> 'savings by frs': the name as the memory keeps it (the client's code in front dropped)."""
    return re.sub(r"^\d+[\s\-_:]+", "", name or "").strip().lower()


class MemoryRemove(BaseModel):
    ids: List[int]


@router.get("/memory")
def firm_memory(db: Session = Depends(get_db)):
    """Every remembered code, newest first, with who confirmed it and how many of today's clients use it (an entry no
    client uses any more most likely came from a client that was deleted, often a test)."""
    from collections import defaultdict
    from backend.app.models.database import User
    chart = {c.std_code: c.std_name for c in db.execute(select(MasterCOA)).scalars()}
    users = {u.id: (u.name or u.email) for u in db.execute(select(User)).scalars()}
    used = defaultdict(set)              # (name, code) -> the clients whose account has that name and code now
    for name, code, eid in db.execute(select(TBRecord.raw_account_name, TBRecord.std_code, TBRecord.engagement_id)):
        used[(_memory_key(name), code)].add(eid)
    rows = db.execute(select(MappingMemory).order_by(MappingMemory.confirmed_at.desc())).scalars().all()
    return [{"id": m.id, "name": m.client_account_name, "std_code": m.std_code, "std_name": chart.get(m.std_code, ""),
             "confirmed_by": users.get(m.owner_user_id, ""),
             "confirmed_at": m.confirmed_at.isoformat() if m.confirmed_at else None,
             "clients": len(used.get((_memory_key(m.client_account_name), m.std_code), ()))} for m in rows]


@router.post("/memory/remove")
def remove_firm_memory(payload: MemoryRemove, db: Session = Depends(get_db)):
    """Forget these remembered codes. Clients already coded keep their codes; only the next uploads are affected."""
    n = db.execute(delete(MappingMemory).where(MappingMemory.id.in_(payload.ids or []))).rowcount
    db.commit()
    return {"removed": n}
