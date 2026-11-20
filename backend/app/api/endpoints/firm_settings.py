"""Firm settings page: the firm's own defaults for every client without its own (depreciation per asset class and the
charge on this year's additions; the standard accountancy fee accrued). A client's setup still comes first, then last year's rate, then these."""

import json
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.firm_settings import FirmSetting
from backend.app.services.review.accrual_journals import firm_accountancy_fee
from backend.app.services.tax.ct_computation import ct_hold_limit
from backend.app.services.review.setup_checks import ADDITIONS_RULES, ASSET_CLASS_CODES, firm_depreciation_settings

router = APIRouter()
METHODS = ("REDUCING_BALANCE", "STRAIGHT_LINE", "NONE")


class ClassRate(BaseModel):
    method: str
    rate: Optional[float] = None


class DepreciationSettings(BaseModel):
    classes: Dict[str, ClassRate]
    additions_from: str = "FULL_YEAR"


def _out(db: Session) -> dict:
    row = db.get(FirmSetting, "depreciation")
    return {**firm_depreciation_settings(db), "asset_classes": list(ASSET_CLASS_CODES),
            "saved": row is not None, "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.get("/depreciation")
def get_depreciation(db: Session = Depends(get_db)):
    return _out(db)


@router.put("/depreciation")
def save_depreciation(body: DepreciationSettings, request: Request, db: Session = Depends(get_db)):
    if body.additions_from not in ADDITIONS_RULES:
        raise HTTPException(status_code=400, detail="Choose how this year's additions are charged")
    classes = {}
    for cls in ASSET_CLASS_CODES:
        c = body.classes.get(cls)
        if c is None or c.method == "NONE":
            classes[cls] = {"method": "NONE"}
            continue
        if c.method not in METHODS:
            raise HTTPException(status_code=400, detail=f"{cls}: choose a method")
        if c.rate is None or not 0 < c.rate <= 100:
            raise HTTPException(status_code=400, detail=f"{cls}: enter a rate between 0 and 100%")
        classes[cls] = {"method": c.method, "rate": round(float(c.rate), 2)}
    row = db.get(FirmSetting, "depreciation") or FirmSetting(key="depreciation")
    row.value = json.dumps({"classes": classes, "additions_from": body.additions_from})
    row.updated_by = getattr(getattr(request.state, "user", None), "id", None)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return _out(db)


class AccountancyFee(BaseModel):
    amount: Optional[float] = None


def _fee_out(db: Session) -> dict:
    row = db.get(FirmSetting, "accountancy_fee")
    return {"amount": firm_accountancy_fee(db),
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.get("/accountancy-fee")
def get_accountancy_fee(db: Session = Depends(get_db)):
    return _fee_out(db)


@router.put("/accountancy-fee")
def save_accountancy_fee(body: AccountancyFee, request: Request, db: Session = Depends(get_db)):
    if body.amount is not None and not 0 <= body.amount <= 1_000_000:
        raise HTTPException(status_code=400, detail="Enter the fee in pounds")
    row = db.get(FirmSetting, "accountancy_fee") or FirmSetting(key="accountancy_fee")
    row.value = json.dumps({"amount": round(float(body.amount), 2) if body.amount else None})
    row.updated_by = getattr(getattr(request.state, "user", None), "id", None)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return _fee_out(db)


class AmountBody(BaseModel):
    amount: Optional[float] = None


def _new_client_prepayments_out(db: Session) -> dict:
    from backend.app.services.review.adjustments import firm_new_client_prepayments
    row = db.get(FirmSetting, "new_client_prepayments")
    return {"amount": firm_new_client_prepayments(db),
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.get("/new-client-prepayments")
def get_new_client_prepayments(db: Session = Depends(get_db)):
    return _new_client_prepayments_out(db)


@router.put("/new-client-prepayments")
def save_new_client_prepayments(body: AmountBody, request: Request, db: Session = Depends(get_db)):
    """Empty = ask about each one (the default), 0 = post every one, an amount = post those of at least it."""
    if body.amount is not None and not 0 <= body.amount <= 1_000_000:
        raise HTTPException(status_code=400, detail="Enter an amount in pounds, 0 to post every one, or leave it empty")
    row = db.get(FirmSetting, "new_client_prepayments") or FirmSetting(key="new_client_prepayments")
    row.value = json.dumps({"amount": round(float(body.amount), 2) if body.amount is not None else None})
    row.updated_by = getattr(getattr(request.state, "user", None), "id", None)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return _new_client_prepayments_out(db)


class Intangibles(BaseModel):
    policy: str = "ADD_BACK"


def _intangibles_out(db: Session) -> dict:
    from backend.app.services.tax.ct_computation import firm_intangibles_policy
    row = db.get(FirmSetting, "intangibles")
    return {"policy": firm_intangibles_policy(db), "saved": row is not None,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.get("/intangibles")
def get_intangibles(db: Session = Depends(get_db)):
    return _intangibles_out(db)


@router.put("/intangibles")
def save_intangibles(body: Intangibles, request: Request, db: Session = Depends(get_db)):
    """Amortisation of software, patents, trade marks and other non-goodwill intangibles in the tax computation:
    ADD_BACK until the reviewer confirms (the default) or ALLOW with the accounts. Goodwill is always added back
    with a query."""
    from backend.app.services.tax.ct_computation import INTANGIBLES_POLICIES
    if body.policy not in INTANGIBLES_POLICIES:
        raise HTTPException(status_code=400, detail="Choose add back or allow")
    row = db.get(FirmSetting, "intangibles") or FirmSetting(key="intangibles")
    row.value = json.dumps({"policy": body.policy})
    row.updated_by = getattr(getattr(request.state, "user", None), "id", None)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return _intangibles_out(db)


class TaxHoldLimit(BaseModel):
    amount: Optional[float] = None


def _hold_out(db: Session) -> dict:
    row = db.get(FirmSetting, "ct_hold_limit")
    return {"amount": ct_hold_limit(db), "saved": row is not None,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.get("/tax-hold-limit")
def get_tax_hold_limit(db: Session = Depends(get_db)):
    return _hold_out(db)


@router.put("/tax-hold-limit")
def save_tax_hold_limit(body: TaxHoldLimit, request: Request, db: Session = Depends(get_db)):
    """Suspense on a bank job above this holds back its corporation tax and dividend journals (empty: £1,000)."""
    if body.amount is not None and not 0 <= body.amount <= 10_000_000:
        raise HTTPException(status_code=400, detail="Enter the limit in pounds")
    row = db.get(FirmSetting, "ct_hold_limit") or FirmSetting(key="ct_hold_limit")
    row.value = json.dumps({"amount": round(float(body.amount), 2) if body.amount is not None else None})
    row.updated_by = getattr(getattr(request.state, "user", None), "id", None)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return _hold_out(db)


class CapitalLimits(BaseModel):
    general: Optional[float] = None
    equipment: Optional[float] = None


def _limits_out(db: Session) -> dict:
    from backend.app.services.sop.capital import firm_capital_limits
    row = db.get(FirmSetting, "capital_limits")
    general, equipment = firm_capital_limits(db)
    return {"general": general, "equipment": equipment, "saved": row is not None,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.get("/capital-limits")
def get_capital_limits(db: Session = Depends(get_db)):
    return _limits_out(db)


@router.put("/capital-limits")
def save_capital_limits(body: CapitalLimits, request: Request, db: Session = Depends(get_db)):
    """Fixed asset limits: purchases from 'general' are checked as possible assets; equipment from 'equipment'
    (empty: the same as general). A limit only one of the two fields is sent for keeps the other."""
    row = db.get(FirmSetting, "capital_limits") or FirmSetting(key="capital_limits")
    saved = json.loads(row.value) if row.value else {}
    for name in ("general", "equipment"):
        value = getattr(body, name)
        if name in body.model_fields_set:
            if value is not None and not 0 <= value <= 1_000_000:
                raise HTTPException(status_code=400, detail="Enter the limit in pounds")
            saved[name] = round(float(value), 2) if value else None
    row.value = json.dumps(saved)
    row.updated_by = getattr(getattr(request.state, "user", None), "id", None)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return _limits_out(db)


# ---------------------------------------------------------------------------------------------------------------
# Year-on-year questions: the amount a change on last year must pass to be asked about
# ---------------------------------------------------------------------------------------------------------------
def _change_limit_out(db: Session) -> Dict:
    """The amount the firm set (None: not set, the default applies), as the other amount settings."""
    from backend.app.services.review.last_year_compare import CHANGE_AMOUNT
    row = db.get(FirmSetting, "change_question_limit")
    try:
        amount = json.loads(row.value).get("amount") if row is not None else None
    except ValueError:
        amount = None
    return {"amount": amount, "default": CHANGE_AMOUNT,
            "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None}


@router.get("/change-question-limit")
def get_change_question_limit(db: Session = Depends(get_db)):
    return _change_limit_out(db)


@router.put("/change-question-limit")
def save_change_question_limit(body: AmountBody, request: Request, db: Session = Depends(get_db)):
    """A change on last year of more than 50% and this amount is a client question; empty = the default (£1,000)."""
    if body.amount is not None and not 0 <= body.amount <= 10_000_000:
        raise HTTPException(status_code=400, detail="Enter an amount in pounds, or leave it empty for the default")
    row = db.get(FirmSetting, "change_question_limit") or FirmSetting(key="change_question_limit")
    row.value = json.dumps({"amount": round(float(body.amount), 2) if body.amount is not None else None})
    row.updated_by = getattr(getattr(request.state, "user", None), "id", None)
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    return _change_limit_out(db)
