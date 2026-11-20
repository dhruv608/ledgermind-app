"""The client's profile and Engagement Setup: profile get / save, the setup status and live preview, Companies
House, auto-detect, property suggestions, last year's balances (all under /engagements/{id})."""

import json
from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.models.schemas import ClientProfileSchema, ClientProfileUpdateRequest
from backend.app.services.shared.activity import mark_changed
from backend.app.services.setup.profile_service import ProfileService

router = APIRouter()

@router.get("/{engagement_id}/profile", response_model=ClientProfileSchema)
def get_engagement_profile(engagement_id: str, db: Session = Depends(get_db)):
    """Retrieve Step 0 Client Profile facts"""
    profile = ProfileService.get_or_create_profile(db, engagement_id)
    return ClientProfileSchema(
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

@router.post("/{engagement_id}/profile", response_model=ClientProfileSchema)
def update_engagement_profile(engagement_id: str, payload: ClientProfileUpdateRequest, db: Session = Depends(get_db)):
    """Update or override Step 0 Client Profile facts"""
    profile = ProfileService.update_profile(db, engagement_id, payload.model_dump(exclude_unset=True))
    mark_changed(db, engagement_id)
    # A saved setup with nothing missing: the checks run by themselves in the background
    from backend.app.services.checks.runner import start_if_ready
    eng = db.get(ClientEngagement, engagement_id)
    if eng is not None:
        start_if_ready(db, eng, "setup")
    return ClientProfileSchema(
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

@router.get("/{engagement_id}/last-year")
def last_year_balances(engagement_id: str, db: Session = Depends(get_db)):
    """Last year's balance beside each account (Accounts tab), where it came from, and last year's balances gone."""
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.review.last_year import asked, compare
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    tb_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement_id)).scalars().all()
    chart = ChartLookup(db)
    cmp = compare(eng, tb_records, chart, db)
    rows = {t.raw_account_name: t for t in tb_records}
    from backend.app.services.review.last_year_compare import firm_change_limit
    limit = firm_change_limit(db)
    return {
        "source": cmp.source,
        "accounts": {name: {"last_year": before, "big": name in rows and asked(
                         chart, rows[name].std_code, float(rows[name].net_amount or 0.0), before, limit)}
                     for name, before in cmp.by_account.items()},
        "gone": [{"name": g.name or chart.name(g.code) or f"Account {g.code}", "amount": g.amount} for g in cmp.gone],
    }


@router.get("/{engagement_id}/profile/property-suggestions")
def property_suggestions(engagement_id: str, db: Session = Depends(get_db)):
    """Properties the ledger seems to have (account headings, property tags), for the accountant to confirm"""
    from backend.app.services.sop.property import suggest_properties
    tb_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement_id)).scalars().all()
    return suggest_properties(engagement_id, tb_records, db)

@router.get("/{engagement_id}/setup-status")
def engagement_setup_status(engagement_id: str, db: Session = Depends(get_db)):
    """The Engagement Setup state: the client context record, the rules it switches on, blocking gaps (the review
    waits for them), warnings, and what the data suggests for open answers."""
    from backend.app.services.setup.engagement_setup import setup_status
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return setup_status(eng, ProfileService.get_or_create_profile(db, engagement_id), db)


@router.get("/{engagement_id}/data-check")
def engagement_data_check(engagement_id: str, db: Session = Depends(get_db)):
    """Is everything the working papers need in the client's files, and was it read: {ready, stops, warnings, items}.
    A STOP item blocks the workbook (the build gives the same reasons); a WARNING leaves it a draft."""
    from backend.app.services.setup.data_check import data_check
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return data_check(db, eng)


@router.post("/{engagement_id}/data-check/first-year")
def set_first_year(engagement_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    """'First year of trading' ticked or cleared ({"first_year": true}): no opening balances to bring in."""
    from backend.app.services.setup.data_check import data_check
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    profile = ProfileService.get_or_create_profile(db, engagement_id)
    setup = json.loads(profile.setup or "{}") if profile.setup else {}
    setup.setdefault("data", {})["first_year"] = bool(payload.get("first_year"))
    profile.setup = json.dumps(setup)
    db.commit()
    mark_changed(db, engagement_id)
    return data_check(db, eng)


@router.post("/{engagement_id}/data-check/last-year-tb")
def upload_last_year_tb(engagement_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Last year's closing TB, added inside the client: the opening balances for a TB of this year's movements.
    Returns the Data check afterwards (with what was added), or 400 with why it was not used."""
    from backend.app.services.review.last_year import add_last_year_tb
    from backend.app.services.setup.data_check import data_check
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty")
    result = add_last_year_tb(eng, file.filename or "last_year_tb.xlsx", data, db)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    mark_changed(db, engagement_id)
    return {**data_check(db, eng), "added": result["added"], "how": result["how"]}


@router.post("/{engagement_id}/setup-status")
def engagement_setup_preview(engagement_id: str, changes: Dict[str, Any], db: Session = Depends(get_db)):
    """The same as GET, for the setup as it is on screen (unsaved edits applied, nothing stored): the live panel."""
    from backend.app.services.setup.engagement_setup import preview_profile, setup_status
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    saved = ProfileService.get_or_create_profile(db, engagement_id)
    return setup_status(eng, preview_profile(saved, changes), db)


@router.get("/{engagement_id}/profile/companies-house")
def companies_house_lookup(engagement_id: str, company_number: Optional[str] = None, db: Session = Depends(get_db)):
    """Directors and shareholders over 25% during the year, from the public register. Without a company number the
    client's name is searched: an exact match is looked up straight away, otherwise the choices come back."""
    from backend.app.services.setup import companies_house as ch
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    try:
        if not company_number:
            found = ch.search(eng.client_name)
            exact = [c for c in found if c["exact"]]
            if len(exact) != 1:
                return {"choices": found}
            company_number = exact[0]["company_number"]
        year_start = eng.prior_period_end_date + timedelta(days=1) if eng.prior_period_end_date else None
        return ch.people(company_number.strip().upper(), eng.period_end_date, year_start)
    except ch.CompaniesHouseError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{engagement_id}/profile/auto-detect", response_model=ClientProfileSchema)
def auto_detect_engagement_profile(engagement_id: str, db: Session = Depends(get_db)):
    """Run auto-detection on uploaded TB and GL datasets against industry signals"""
    profile = ProfileService.auto_detect_profile(db, engagement_id, keep_confirmed=False)
    mark_changed(db, engagement_id)
    return ClientProfileSchema(
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
