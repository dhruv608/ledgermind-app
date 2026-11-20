"""Foster, kinship and shared-lives care: qualifying care relief (R-SP-01; ITTOIA s803-828, HS236). The care
receipts for the year (the council's or agency's letter) are set against a limit: the household's fixed amount (shared
between the carers in the household) plus a weekly amount for each person cared for, by age band, a part week counting
as a full week. Receipts at or under the limit are not taxed; over it, the simplified method taxes receipts less the
limit, or the normal method taxes receipts less the actual costs: an accountant's decision. The weeks come from the
placement dates: never assumed (a client query until they are given)."""

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.interest import _tax_year_of
from backend.app.sa.extract.p60 import owner

BANDS = {"UNDER_11": "under_11", "ELEVEN_PLUS": "eleven_plus", "ADULT": "adult"}
BAND_LABELS = {"UNDER_11": "Child under 11", "ELEVEN_PLUS": "Child 11 or over", "ADULT": "Adult"}

PROMPT = """This is a UK letter about foster care, kinship care or shared lives care payments (from a council or a
fostering agency), sent for a Self Assessment return. Reply with one JSON object only:
{"carer": "the carer's full name as printed or null", "payer": "the council or agency",
 "period_from": "YYYY-MM-DD or null", "period_to": "YYYY-MM-DD or null",
 "receipts": number (the total allowances or payments made to the carer for the period, before anything is taken off)}
Money as a plain number with pence (no £ or commas)."""

FOSTER_WORDS = re.compile(r"foster(ing)? (care )?allowance|fostering allowances|qualifying care|kinship care|shared lives", re.I)


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    try:
        receipts = round(abs(float(str(a.get("receipts")).replace(",", "").replace("£", ""))), 2) if a.get("receipts") not in (None, "") else None
    except ValueError:
        receipts = None
    return {"carer": (a.get("carer") or "").strip() or None, "payer": (a.get("payer") or "").strip() or None,
            "period_from": a.get("period_from"), "period_to": a.get("period_to"), "receipts": receipts}


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    if f.get("receipts") is None:
        return "CHECK", ["The care payments for the year could not be read: enter them on Self-employment by hand."]
    notes: List[str] = []
    # A council's year to 31 March is the tax year for the trade (ITTOIA 2005 s7B, BIM81210: no apportioning)
    from backend.app.sa.extract.letting import _march_year, march_basis
    march = march_basis(f)
    year_of = _march_year if march else _tax_year_of
    years = {year_of(f.get("period_from")), year_of(f.get("period_to"))} - {None}
    if years and tax_year not in years:
        return "OTHER_YEAR", [f"This letter is for {', '.join(sorted(years))}, not {tax_year}: not used."]
    if not march and (len(years) > 1 or (f.get("period_to") and not str(f["period_to"]).endswith("-04-05"))):
        notes.append(f"The letter covers {f.get('period_from')} to {f.get('period_to')}, not the tax year (6 April to "
                     f"5 April): check the payments for {tax_year} (a council's year often ends 31 March).")
    if person and f.get("carer") and owner(f["carer"], person) == "OTHER":
        f["other_person"] = True
        return "CHECK", [f"This letter is for {f['carer']}, not {person}: not used. If it is theirs, confirm it."]
    if second is not None:
        s = clean(second)
        if s.get("receipts") is not None and abs(s["receipts"] - f["receipts"]) > 0.005:
            notes.append(f"The two readers disagree on the payments (£{f['receipts']:,.2f} or £{s['receipts']:,.2f}).")
    return ("CHECK" if notes else "READ"), notes


def care_amounts(tax_year: str) -> Tuple[Dict, str]:
    """The fixed and weekly amounts for the year, and the year they are from: HMRC publishes them late (BIM52765), so
    until a year's are out the latest earlier year's are used (and the work-out says so)."""
    from backend.app.sa.engine.calc import RATES
    for year in sorted((y for y in RATES if not y.startswith("_") and y <= tax_year), reverse=True):
        if "qualifying_care" in RATES[year]:
            return RATES[year]["qualifying_care"], year
    raise ValueError(f"No qualifying care amounts held for {tax_year}")


def limit(tax_year: str, placements: List[Dict], carers: int = 1) -> float:
    """The qualifying amount: the fixed amount (shared between the household's carers) plus each placement's weeks at
    its band's weekly amount (weeks already counted as whole weeks)."""
    q = care_amounts(tax_year)[0]
    fixed = q["fixed"] / max(1, carers)
    return round(fixed + sum(int(p["weeks"]) * q[BANDS[p["band"]]] for p in placements), 2)


def work_out(tax_year: str, receipts: Optional[float], placements: List[Dict], carers: int = 1,
             method: Optional[str] = None, actual_costs: Optional[float] = None) -> Dict:
    """The relief: the limit, whether the receipts are all exempt, and the profit to tax under the chosen method."""
    if receipts is None:
        return {"receipts": None, "limit": None, "exempt": None, "profit": 0.0, "issues": []}
    issues = []
    used = care_amounts(tax_year)[1]
    if used != tax_year:
        issues.append({"key": "care_amounts", "kind": "DECISION", "block": False,
                       "text": f"HMRC has not yet published the {tax_year} qualifying care amounts (BIM52765): the "
                               f"{used} amounts are used. Check them when HMRC publishes the new ones."})
    if not placements:
        issues.append({"key": "placements", "kind": "CLIENT", "block": True,
                       "text": "For each child or adult you cared for in the year: their age, and the dates they arrived "
                               "and left (or 'all year'). The tax-free amount depends on them (R-SP-01)."})
        return {"receipts": receipts, "limit": None, "exempt": None, "profit": 0.0, "issues": issues}
    lim = limit(tax_year, placements, carers)
    if receipts <= lim:
        return {"receipts": receipts, "limit": lim, "exempt": True, "profit": 0.0, "issues": issues}
    simplified = round(receipts - lim, 2)
    profit = simplified
    if method == "ACTUAL":
        profit = round(receipts - (actual_costs or 0.0), 2)
    elif method != "SIMPLIFIED":
        issues.append({"key": "method", "kind": "DECISION", "block": True,
                       "text": f"Care payments of £{receipts:,.2f} are over the limit of £{lim:,.2f}: choose the simplified "
                               f"method (taxed on £{simplified:,.2f}) or the normal method (payments less the actual costs) "
                               f"(R-SP-01)."})
    return {"receipts": receipts, "limit": lim, "exempt": False, "profit": profit, "issues": issues}


def for_job(db, job) -> Dict:
    """The job's care relief: receipts typed, else from the letters read; placements; the result."""
    import json
    from backend.app.sa.models import SADocument, SAFosterPlacement, SAFosterYear
    year = db.get(SAFosterYear, job.id)
    rows = db.query(SAFosterPlacement).filter(SAFosterPlacement.job_id == job.id).order_by(SAFosterPlacement.id).all()
    letters = [json.loads(d.fields) for d in db.query(SADocument).filter(
        SADocument.job_id == job.id, SADocument.kind == "FOSTER_LETTER", SADocument.status.in_(("READ", "CHECK"))) if d.fields]
    from_letters = round(sum(f["receipts"] for f in letters if f.get("receipts") and not f.get("other_person")), 2) if letters else None
    receipts = float(year.receipts) if year is not None and year.receipts is not None else from_letters
    placements = [{"id": r.id, "label": r.label, "band": r.band, "weeks": r.weeks} for r in rows]
    out = work_out(job.tax_year, receipts, placements, year.carers if year else 1, year.method if year else None,
                   float(year.actual_costs) if year is not None and year.actual_costs is not None else None)
    out.update({"placements": placements, "carers": year.carers if year else 1, "method": year.method if year else None,
                "actual_costs": float(year.actual_costs) if year is not None and year.actual_costs is not None else None,
                "from_letters": from_letters, "typed": year is not None and year.receipts is not None})
    return out
