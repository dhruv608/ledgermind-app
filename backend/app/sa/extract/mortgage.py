"""A mortgage interest certificate or annual mortgage statement read (R-SA105-05): the interest charged in the
period on a let property's loan is a residential finance cost (the 20% tax reduction, never an expense; a commercial
let's interest is an expense, property.py moves it). A mortgage on the person's own home is not a cost of letting and
is left out. Code checks every reading:

  tax year    a statement for another period (most lenders use the calendar year) is a point: take the interest for
              the tax year (6 April to 5 April)
  owner       the person is one of the borrowers, when borrowers are printed (R-IN-07)
  readers     a scan is read by two models; an interest figure they do not agree on is a point to check"""

from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.interest import _tax_year_of
from backend.app.sa.extract.p60 import owner

PROMPT = """This is a UK mortgage interest certificate or annual mortgage statement sent for a Self Assessment return.
Reply with one JSON object only:
{"lender": "...", "borrowers": ["each borrower's full name as printed"], "property_address": "the mortgaged property's
 address as printed, or null", "account_last4": "last 4 digits of the mortgage account or null",
 "period_from": "YYYY-MM-DD or null", "period_to": "YYYY-MM-DD or null",
 "interest": number (the interest charged or paid in the period, not the total repayments and not the balance),
 "buy_to_let": true, false or null (the statement says buy to let or a let property)}
Money as a plain number with pence (no £ or commas)."""


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(abs(float(str(v).replace(",", "").replace("£", "").strip())), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    return {"lender": (a.get("lender") or "").strip() or None, "borrowers": [b for b in (a.get("borrowers") or []) if b],
            "property_address": (a.get("property_address") or "").strip() or None,
            "account_last4": (str(a.get("account_last4") or "").strip()[-4:] or None),
            "period_from": a.get("period_from"), "period_to": a.get("period_to"), "interest": _num(a.get("interest")),
            "buy_to_let": a.get("buy_to_let")}


def _tax_year_part(start: str, end: str, tax_year: str) -> Optional[float]:
    """The share of the days from start to end (both counted) inside the tax year, or None for dates that do not read."""
    from datetime import date
    try:
        a, b = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    y = int(tax_year[:4])
    lo, hi = max(a, date(y, 4, 6)), min(b, date(y + 1, 4, 5))
    days = (b - a).days + 1
    return max(0, (hi - lo).days + 1) / days if days > 0 else None


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    if f.get("interest") is None:
        return "CHECK", ["The interest could not be read: enter it on the Property page by hand."]
    notes: List[str] = []
    years = {_tax_year_of(f.get("period_from")), _tax_year_of(f.get("period_to"))} - {None}
    if years and tax_year not in years:
        return "OTHER_YEAR", [f"This statement is for {', '.join(sorted(years))}, not {tax_year}: not used."]
    if len(years) > 1:
        # Apportioned to the tax year by days: a calendar-year statement holds part
        # of two tax years; the other statement gives the rest. A lender's tax-year figure replaces it when sent
        part = _tax_year_part(f["period_from"], f["period_to"], tax_year)
        if part is not None:
            f["interest_year"] = round(f["interest"] * part, 2)
            notes.append(f"The statement runs {f['period_from']} to {f['period_to']}, not 6 April to 5 April: "
                         f"£{f['interest_year']:,.2f} of its £{f['interest']:,.2f} interest is taken for {tax_year} "
                         f"(by days). Send a statement to 5 April to confirm (R16).")
        else:
            notes.append(f"The statement runs {f['period_from']} to {f['period_to']}, not 6 April to 5 April: take the "
                         f"interest for {tax_year} only (or the lender's tax-year figure).")
    if person and f.get("borrowers") and all(owner(b, person) == "OTHER" for b in f["borrowers"]):
        f["other_person"] = True
        return "CHECK", [f"The borrower is {', '.join(f['borrowers'])}, not {person}: not used. If it is theirs, confirm it."]
    if second is not None:
        s = clean(second)
        if s.get("interest") is not None and abs(s["interest"] - f["interest"]) > 0.005:
            notes.append(f"The two readers disagree on the interest (£{f['interest']:,.2f} or £{s['interest']:,.2f}): "
                         f"look at the statement.")
    return ("CHECK" if notes else "READ"), notes
