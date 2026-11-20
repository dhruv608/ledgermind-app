"""Account rules page: the firm's own account-name rules (list, add, change, delete, reorder, see and apply matches)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import FirmMappingRule, MasterCOA
from backend.app.services.mapping.firm_rules import all_rules, apply_rule, match_counts, rule_matches_in_clients, split_words, touch

router = APIRouter()


class RuleIn(BaseModel):
    words: str
    except_words: Optional[str] = None
    std_code: int
    note: Optional[str] = None
    active: bool = True


def _out(rule: FirmMappingRule, db: Session, count: Optional[int] = None) -> dict:
    coa = db.get(MasterCOA, rule.std_code)
    return {"id": rule.id, "words": rule.words, "except_words": rule.except_words or "", "std_code": rule.std_code,
            "std_name": coa.std_name if coa else "", "note": rule.note or "", "active": bool(rule.active),
            "position": rule.position, "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
            "matches": count}


def _all(db: Session, request: Request) -> List[FirmMappingRule]:
    return all_rules(db, request.state.user.id)     # the starting rules are loaded the first time


def _clean(payload: RuleIn, db: Session) -> RuleIn:
    if not split_words(payload.words):
        raise HTTPException(status_code=400, detail="Give at least one word")
    if db.get(MasterCOA, payload.std_code) is None:
        raise HTTPException(status_code=400, detail=f"Code {payload.std_code} is not in the firm chart")
    payload.words = ", ".join(split_words(payload.words))
    payload.except_words = ", ".join(split_words(payload.except_words)) or None
    return payload


@router.get("")
def list_rules(request: Request, db: Session = Depends(get_db)):
    rules = _all(db, request)
    counts = match_counts(db, request.state.user.id)
    return [_out(r, db, counts.get(r.id, 0)) for r in rules]


@router.post("")
def add_rule(payload: RuleIn, request: Request, db: Session = Depends(get_db)):
    payload = _clean(payload, db)
    last = max((r.position or 0 for r in _all(db, request)), default=-1)
    rule = FirmMappingRule(position=last + 1, owner_user_id=request.state.user.id, **payload.model_dump())
    db.add(rule)
    db.commit()
    return _out(rule, db)


@router.put("/{rule_id}")
def change_rule(rule_id: int, payload: RuleIn, db: Session = Depends(get_db)):
    rule = db.get(FirmMappingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    payload = _clean(payload, db)
    for key, value in payload.model_dump().items():
        setattr(rule, key, value)
    touch(rule)
    db.commit()
    return _out(rule, db)


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(FirmMappingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"status": "SUCCESS"}


@router.get("/{rule_id}/matches")
def rule_matches(rule_id: int, db: Session = Depends(get_db)):
    """The client accounts this rule decides, what they have now, and which would change if applied."""
    rule = db.get(FirmMappingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule_matches_in_clients(rule, db)


@router.post("/{rule_id}/apply")
def apply(rule_id: int, db: Session = Depends(get_db)):
    """Moves the matching accounts to the rule's code, except those an accountant set."""
    rule = db.get(FirmMappingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    if not rule.active:
        raise HTTPException(status_code=400, detail="The rule is switched off")
    return apply_rule(rule, db)
