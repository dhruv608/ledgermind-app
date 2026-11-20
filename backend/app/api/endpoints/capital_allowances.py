"""Capital allowances: each addition with the app's suggestion and the accountant's choice (under /engagements/{id})."""

import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.shared.activity import mark_changed
from backend.app.services.setup.profile_service import ProfileService

router = APIRouter()

class CapitalAllowanceChoices(BaseModel):
    choices: Dict[str, str] = {}             # addition key -> AIA / FYA / MAIN / SPECIAL / NONE
    main_rate_rule: Optional[str] = None     # SPLIT (18% / 14% from 1 April 2026) or FULL_18


def _capital_allowances(eng: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.tax.ct_computation import CA_TREATMENTS, ct_computation
    tb_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == eng.id)).scalars().all()
    comp = ct_computation(eng, tb_records, db)
    inputs = json.loads(eng.profile.tax_inputs or "{}") if eng.profile and eng.profile.tax_inputs else {}
    return {
        "assets": comp.ca_assets,
        "treatments": CA_TREATMENTS,
        "allowances": [{"label": a.label, "amount": a.amount} for a in comp.capital_allowances],
        "crosses_april_2026": comp.period_start <= datetime(2026, 3, 31).date() < comp.period_end,
        "main_rate_rule": inputs.get("main_rate_rule") or "SPLIT",
    }


@router.get("/{engagement_id}/capital-allowances")
def capital_allowances(engagement_id: str, db: Session = Depends(get_db)):
    """This year's additions with the app's suggested capital allowance and the accountant's choice (the accountant
    decides; the tax computation uses the choice)."""
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    return _capital_allowances(eng, db)


@router.post("/{engagement_id}/capital-allowances")
def save_capital_allowances(engagement_id: str, body: CapitalAllowanceChoices, db: Session = Depends(get_db)):
    """Saves the accountant's choices in the client's tax inputs (a choice equal to the suggestion is kept too, so it
    stays if the suggestion changes later). Run the review again for the tax computation and journals."""
    from backend.app.services.tax.ct_computation import CA_TREATMENTS
    eng = db.get(ClientEngagement, engagement_id)
    if not eng:
        raise HTTPException(status_code=404, detail="Client engagement not found")
    bad = [v for v in body.choices.values() if v not in CA_TREATMENTS]
    if bad or (body.main_rate_rule not in (None, "SPLIT", "FULL_18")):
        raise HTTPException(status_code=400, detail="Unknown capital allowance choice")
    profile = ProfileService.get_or_create_profile(db, engagement_id)
    inputs = json.loads(profile.tax_inputs or "{}")
    inputs["ca_choices"] = {**(inputs.get("ca_choices") or {}), **body.choices}
    if body.main_rate_rule:
        inputs["main_rate_rule"] = body.main_rate_rule
    profile.tax_inputs = json.dumps(inputs)
    db.commit()
    mark_changed(db, engagement_id)
    return _capital_allowances(eng, db)
