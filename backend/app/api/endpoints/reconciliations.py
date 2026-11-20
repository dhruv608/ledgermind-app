"""The control accounts screen: each control account against what it is agreed to, and the statement balances typed
on it (under /engagements/{id})."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement
from backend.app.services.shared.activity import mark_changed

router = APIRouter()

@router.get("/{engagement_id}/reconciliations")
def control_accounts(engagement_id: str, db: Session = Depends(get_db)):
    """Each control account in the books against what it is agreed to (statement, returns, aged lists, payroll
    report, tax computation) and the difference: the control accounts screen, before the workbook is built."""
    from backend.app.services.reconciliation.control_accounts import reconciliations, summary
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    try:
        return summary(reconciliations(eng, db))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"The control accounts could not be worked out: {str(e)[:200]}")


@router.get("/{engagement_id}/etb")
def extended_trial_balance(engagement_id: str, db: Session = Depends(get_db)):
    """The extended trial balance per firm code: the TB, the approved journals, the final balance and last year's."""
    from backend.app.services.papers.etb import etb
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return etb(eng, db)


@router.get("/{engagement_id}/rollforward")
def account_rollforward(engagement_id: str, codes: str, db: Session = Depends(get_db)):
    """One balance sheet account's year: opening + this year's lines by type + approved journals = closing
    (codes: "4400" or "4400,4401")."""
    from backend.app.services.papers.rollforward import rollforward
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    wanted = [int(c) for c in codes.split(",") if c.strip().isdigit()]
    if not wanted:
        raise HTTPException(status_code=400, detail="No account code given")
    return rollforward(eng, db, wanted)


@router.get("/{engagement_id}/fixed-asset-schedule")
def fixed_asset_schedule(engagement_id: str, db: Session = Depends(get_db)):
    """The fixed assets by class: cost b/f, additions, disposals, depreciation, NBV (the Schedule of Data)."""
    from backend.app.services.papers.fixed_asset_schedule import schedule
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return schedule(eng, db)


@router.get("/{engagement_id}/asset-register")
def asset_register(engagement_id: str, db: Session = Depends(get_db)):
    """The asset register asset by asset, with this year's charge (the Asset Register screen)."""
    from backend.app.services.papers.fixed_asset_schedule import register
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return register(eng, db)


@router.get("/{engagement_id}/tax-calculation")
def tax_calculation(engagement_id: str, db: Session = Depends(get_db)):
    """The corporation tax computation line by line (the Tax Calculation screen)."""
    from backend.app.services.papers.capital import tax_calculation as calc
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return calc(eng, db)


@router.get("/{engagement_id}/reserves")
def reserves_movement(engagement_id: str, db: Session = Depends(get_db)):
    """Retained earnings: brought forward, profit, dividends, carried forward (the Reserves screen)."""
    from backend.app.services.papers.capital import reserves
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return reserves(eng, db)


class AssetDetails(BaseModel):
    residual_value: Optional[float] = None
    useful_life_years: Optional[float] = None


@router.put("/{engagement_id}/asset-register/{asset_id}")
def save_asset_details(engagement_id: str, asset_id: int, body: AssetDetails, db: Session = Depends(get_db)):
    """An asset's residual value and useful life (the Asset Register screen); no figure changes with them."""
    from backend.app.models.database import FixedAssetRecord
    a = db.get(FixedAssetRecord, asset_id)
    if a is None or a.engagement_id != engagement_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    a.residual_value, a.useful_life_years = body.residual_value, body.useful_life_years
    db.commit()
    return {"id": a.id, "residual_value": body.residual_value, "useful_life_years": body.useful_life_years}


@router.get("/{engagement_id}/trade-adjustments")
def trade_adjustments(engagement_id: str, side: str, db: Session = Depends(get_db)):
    """The Adjustments block under the trade debtors (side=customer) or creditors (side=supplier) T."""
    from backend.app.services.reconciliation.trade_adjustments import trade_adjustments as adjustments
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    if side not in ("customer", "supplier"):
        raise HTTPException(status_code=400, detail="side is customer or supplier")
    return adjustments(eng, db, side)


@router.get("/{engagement_id}/sales-reconciliation")
def sales_reconciliation(engagement_id: str, db: Session = Depends(get_db)):
    """Sales per the VAT returns (Box 6) to sales in the profit and loss account (the Sales Reconciliation)."""
    from backend.app.services.reconciliation.sales import sales_reconciliation as reconcile
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return reconcile(eng, db)


@router.get("/{engagement_id}/debtor-ageing")
def debtor_ageing(engagement_id: str, db: Session = Depends(get_db)):
    """Debtors by age (not due, 1-30, 31-60, 61-90, 91+ days) per customer, from the client's aged receivables report."""
    from backend.app.services.reconciliation.debtor_ageing import debtor_ageing as ageing
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return ageing(eng, db)


@router.get("/{engagement_id}/creditor-ageing")
def creditor_ageing(engagement_id: str, db: Session = Depends(get_db)):
    """Creditors by age per supplier, from the client's aged payables report (the same five boxes as debtors)."""
    from backend.app.services.reconciliation.debtor_ageing import debtor_ageing as ageing
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return ageing(eng, db, "AP")


@router.get("/{engagement_id}/payroll-months")
def payroll_months(engagement_id: str, db: Session = Depends(get_db)):
    """Net wages, PAYE / NI and pension month by month, and the payroll cost against what was owed out (the same
    figures as the workbook's G6, G6.2, G7 and G8)."""
    from backend.app.services.papers.payroll_months import payroll_by_month
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return payroll_by_month(eng, db)


@router.get("/{engagement_id}/payroll-summary")
def payroll_summary(engagement_id: str, db: Session = Depends(get_db)):
    """The payroll month by month from the payroll reports: Total, Employees and Directors (the Payroll Summary)."""
    from backend.app.services.papers.payroll_summary import payroll_summary as summary
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return summary(eng, db)


class StatementRead(BaseModel):
    evidence_id: int
    code: int


@router.post("/{engagement_id}/bank-statement/read")
def bank_statement_read(engagement_id: str, body: StatementRead, db: Session = Depends(get_db)):
    """Read an uploaded bank statement into its lines for one bank account (a PDF is read page by page)."""
    from backend.app.services.reconciliation.bank_statement import read_statement
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    try:
        return read_statement(eng, db, body.evidence_id, body.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{engagement_id}/bank-statement/{code}")
def bank_statement_match(engagement_id: str, code: int, db: Session = Depends(get_db)):
    """A bank account's statement lines against its ledger: matched, unmatched and unrecorded."""
    from backend.app.services.reconciliation.bank_statement import statement_match
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return statement_match(eng, db, code)


class ReconciliationEntry(BaseModel):
    key: str                                  # "bank:4800"
    balance: Optional[float] = None           # the statement balance in £
    currency_amount: Optional[float] = None   # or, for a foreign currency account, the balance in that currency
    rate: Optional[float] = None              # and the year-end rate (currency per £1)
    agreed: bool = False                      # a balance sheet account ticked as agreeing to its document
    note: Optional[str] = None                # what it was agreed to ("loan statement 31/03/25")
    # Where a bank balance came from (the workbook's 'Statement date / page' and 'Rate source')
    statement_date: Optional[date] = None
    page: Optional[str] = None
    rate_source: Optional[str] = None         # HMRC monthly rate, Bank of England, the bank's own rate
    clear: bool = False                       # remove what was typed


@router.post("/{engagement_id}/reconciliations")
def save_reconciliation_entry(engagement_id: str, body: ReconciliationEntry, request: Request, db: Session = Depends(get_db)):
    """Saves a figure typed on the control accounts screen (a bank statement balance); the workbook's bank tab
    starts from it too."""
    from backend.app.services.workbook.balance_tabs import BANK_CODES
    from backend.app.services.reconciliation.control_accounts import by_hand_key, reconciliations, save_input, summary
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    kind, _, code = body.key.partition(":")
    bank = kind == "bank" and code.isdigit() and int(code) in BANK_CODES
    if not bank and not by_hand_key(body.key):
        raise HTTPException(status_code=400, detail="Unknown control account")
    if body.clear:
        value = None
    elif body.agreed and not bank:
        value = {"agreed": True, "note": (body.note or "").strip()[:300]}
    elif body.balance is not None and body.key.startswith("vatproof:"):
        value = {"balance": round(body.balance, 2), "note": (body.note or "").strip()[:300]}
    elif body.balance is not None:
        value = {"balance": round(body.balance, 2)}
    elif body.currency_amount is not None and body.rate:
        if body.rate <= 0:
            raise HTTPException(status_code=400, detail="The exchange rate must be above nil")
        value = {"currency_amount": round(body.currency_amount, 2), "rate": body.rate}
    else:
        raise HTTPException(status_code=400, detail="Enter the statement balance, or the currency balance and the rate")
    if value is not None and bank:
        if body.statement_date:
            value["statement_date"] = body.statement_date.isoformat()
        if (body.page or "").strip():
            value["page"] = body.page.strip()[:40]
        if (body.rate_source or "").strip() and "currency_amount" in value:
            value["rate_source"] = body.rate_source.strip()[:80]
    user = getattr(request.state, "user", None)
    save_input(db, engagement_id, body.key, value, getattr(user, "id", None))
    mark_changed(db, engagement_id)
    return summary(reconciliations(eng, db))
