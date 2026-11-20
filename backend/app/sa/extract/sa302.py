"""HMRC's tax calculation (SA302 / 'Calculation Result') read (R-EX-01, R-FAM-03): the year, the income by kind,
the tax and Class 4 due, the tax deducted, and the amount due. Last year's tells this year's payments on account (half
of last year's tax and Class 4 less the tax taken at source, each, unless under £1,000 or 80% was taken at source:
TMA s59A); this year's, once filed, is checked against the return worked out here."""

from typing import Any, Dict, List, Optional, Tuple

PROMPT = """This is HMRC's tax calculation for a UK Self Assessment return (an SA302 or 'Calculation Result for
YYYY-YY'). Reply with one JSON object only (money as numbers with pence, no £ or commas; null when not shown):
{"tax_year": "2024-25 style", "name": "the person's name as printed, or null", "total_income": number,
 "employment": number, "self_employment": number, "property": number, "savings": number, "dividends": number,
 "pensions": number, "income_tax": number (Income Tax charged after allowances and reliefs),
 "class4": number (Class 4 National Insurance due), "class2": number,
 "tax_deducted": number (total tax deducted at source), "due": number (the final amount due, or minus for a repayment)}"""

FIELDS = ("total_income", "employment", "self_employment", "property", "savings", "dividends", "pensions",
          "income_tax", "class4", "class2", "tax_deducted", "due")


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(str(v).replace(",", "").replace("£", "").strip()), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    out = {k: _num(a.get(k)) for k in FIELDS}
    out["tax_year"] = (str(a.get("tax_year") or "").strip()[:7] or None)
    out["name"] = (a.get("name") or "").strip() or None
    # The prompt's own words given back for a page with no name on it ('the person's name'): no name
    if out["name"] and "person's name" in out["name"].lower():
        out["name"] = None
    return out


def previous(tax_year: str) -> str:
    y = int(tax_year[:4]) - 1
    return f"{y}-{str(y + 1)[2:]}"


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """Last year's or this year's calculation is kept (each has its use); another year is not used."""
    from backend.app.sa.extract.p60 import owner
    if f.get("income_tax") is None and f.get("due") is None:
        return "CHECK", ["The tax calculation's figures could not be read."]
    if f.get("tax_year") not in (tax_year, previous(tax_year)):
        return "OTHER_YEAR", [f"This calculation is for {f.get('tax_year') or 'another year'}: not used."]
    if person and f.get("name") and owner(f["name"], person) == "OTHER":
        f["other_person"] = True
        return "CHECK", [f"This calculation is for {f['name']}, not {person}: not used."]
    if second is not None:
        s = clean(second)
        if s.get("due") is not None and f.get("due") is not None and abs(s["due"] - f["due"]) > 0.005:
            return "CHECK", [f"The two readers disagree on the amount due (£{f['due']:,.2f} or £{s['due']:,.2f})."]
    return "READ", []


def poa_from_last_year(f: Dict[str, Any], min_relevant: float = 1000.0, at_source_share: float = 0.8) -> float:
    """Each payment on account for this year set by last year's calculation (0 when none were due, TMA s59A)."""
    tax = (f.get("income_tax") or 0) + (f.get("class4") or 0)
    deducted = f.get("tax_deducted") or 0
    relevant = round(tax - deducted, 2)
    if relevant < min_relevant or (tax and deducted >= at_source_share * tax):
        return 0.0
    return round(relevant / 2, 2)
