"""Charity donations the client lists or sends receipts for: Gift Aid (SA100 box 5). The amount entered is what was
paid (net); the engine grosses it up and extends the basic rate band. Only donations made under a Gift Aid declaration count, so the accountant confirms them; donations the
paper says were not Gift Aided are left out.

Read by the model from the text (a monthly list, a CSV export, a charity's letter or receipt): total rows are not
donations, and only the tax year's donations are kept."""

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.interest import _tax_year_of

PROMPT = """This is a list of charity donations, or a charity's receipt or letter, sent for a UK tax return (Gift Aid).
Reply with one JSON object only:
{"donor": "the donor's name as printed or null",
 "donations": [{"date": "YYYY-MM-DD (a month row 'YYYY-MM': the 1st of that month) or null", "charity": "...",
                "amount": number (what was paid, in pounds), "gift_aid": true, false or null (true when the paper says
                Gift Aid was claimed or declared, false when it says not, null when it does not say)}]}
One entry per donation (a list by month and charity: one entry per charity per month with an amount above zero).
Leave out total and subtotal rows and columns. Money as plain numbers (no £ or commas)."""


def _num(v: Any) -> float:
    try:
        return round(abs(float(str(v).replace(",", "").replace("£", "").strip())), 2)
    except (TypeError, ValueError):
        return 0.0


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    rows = [{"on": r.get("date"), "charity": str(r.get("charity") or "").strip()[:120], "amount": _num(r.get("amount")),
             "gift_aid": r.get("gift_aid") if isinstance(r.get("gift_aid"), bool) else None}
            for r in a.get("donations") or [] if not re.search(r"\btotal\b", str(r.get("charity") or ""), re.I)]
    return {"donor": (a.get("donor") or "").strip() or None, "donations": [r for r in rows if r["amount"]]}


JOINT_DONOR = re.compile(r"\s(&|and)\s|\bmr\.? and mrs\b|\bjoint\b", re.I)


def in_year(f: Dict[str, Any], tax_year: str) -> List[Dict[str, Any]]:
    """The tax year's donations that may be Gift Aided (a dated one outside the year, or one marked not Gift Aid, out)."""
    return [r for r in f.get("donations") or []
            if r["gift_aid"] is not False and (not _tax_year_of(r.get("on")) or _tax_year_of(r["on"]) == tax_year)]


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    from backend.app.sa.extract.p60 import owner
    if not f.get("donations"):
        return "CHECK", ["No donation could be read: enter the Gift Aid donations by hand on Reliefs."]
    if person and f.get("donor") and owner(f["donor"], person) == "OTHER":
        f["other_person"] = True
        return "CHECK", [f"These donations are by {f['donor']}, not {person}: not used. If they are theirs, confirm it."]
    # Two donors, or a joint account: Gift Aid is the donor's own, so the declaration must be in this person's name and
    # only their gifts count (R-SAV-08)
    if f.get("donor") and JOINT_DONOR.search(f["donor"]):
        return "CHECK", [f"The donations are by {f['donor']}: Gift Aid is claimed by the person who gave and made the "
                         f"declaration. Check the declaration is in {person or 'this person'}'s name and enter only their "
                         f"gifts (R-SAV-08)."]
    keep = in_year(f, tax_year)
    total = round(sum(r["amount"] for r in keep), 2)
    if not keep:
        return "OTHER_YEAR", [f"No donation in {tax_year} that may be Gift Aided: not used."]
    unsure = sum(1 for r in keep if r["gift_aid"] is None)
    f["total"] = total
    return "CHECK", [f"Donations of £{total:,.2f} in {tax_year} put on Reliefs as Gift Aid (as paid; grossed up in the "
                     f"calculation)." + (f" {unsure} do not say Gift Aid was declared: confirm each charity has a Gift Aid "
                     f"declaration, or take them off." if unsure else "")]
