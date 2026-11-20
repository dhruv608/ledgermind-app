"""HMRC's Self Assessment statement (SA300) read: its lines (tax due and credits). The payments on account for the
return's year come from it (R-FAM-03; TMA 1970 s59A): both the
first (31 January) and the second (31 July) are charged for the year and come off the balance due on the return,
paid or not (an unpaid one is still owed to HMRC). A statement for someone else is kept out."""

import re
from typing import Any, Dict, List, Optional, Tuple

PROMPT = """This is an HMRC Self Assessment statement (SA300) for a UK taxpayer. Reply with one JSON object only:
{"name": "the taxpayer's name as printed or null", "statement_date": "YYYY-MM or YYYY-MM-DD or null",
 "amount_due": number or null, "due_by": "YYYY-MM-DD or null",
 "lines": [{"date": "YYYY-MM-DD", "description": "as printed", "tax_due": number or null, "credit": number or null}]}
One entry per line of the statement table, in order. Money as plain numbers (no £ or commas)."""

POA = re.compile(r"\b(1st|2nd|first|second) payment on account\b.*?(\d{2})\s*/\s*(\d{2})", re.I)


def _num(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return round(abs(float(str(v).replace(",", "").replace("£", "").strip())), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    lines = [{"on": l.get("date"), "description": str(l.get("description") or "").strip()[:200],
              "tax_due": _num(l.get("tax_due")), "credit": _num(l.get("credit"))} for l in a.get("lines") or []]
    return {"name": (a.get("name") or "").strip() or None, "statement_date": a.get("statement_date"),
            "amount_due": _num(a.get("amount_due")), "due_by": a.get("due_by"), "lines": [l for l in lines if l["description"]]}


def payments_on_account(f: Dict[str, Any], tax_year: str) -> List[Dict[str, Any]]:
    """The statement's payments on account charged for the tax year ('1st payment on account due for year 24/25')."""
    want = (tax_year[2:4], tax_year[5:7])
    out = []
    for l in f.get("lines") or []:
        m = POA.search(l["description"])
        if m and (m.group(2), m.group(3)) == want and l.get("tax_due"):
            out.append({"which": "first" if m.group(1).lower() in ("1st", "first") else "second", "amount": l["tax_due"],
                        "on": l.get("on")})
    return out


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    from backend.app.sa.extract.p60 import owner
    if not f.get("lines"):
        return "CHECK", ["The statement's lines could not be read: enter the payments on account by hand on Tax calculation."]
    if person and f.get("name") and owner(f["name"], person) == "OTHER":
        f["other_person"] = True
        return "CHECK", [f"This HMRC statement is for {f['name']}, not {person}: not used. If it is theirs, confirm it."]
    poa = payments_on_account(f, tax_year)
    if not poa:
        return "READ", [f"No payment on account for {tax_year} on this statement (none were due, or it is another year's)."]
    total = round(sum(p["amount"] for p in poa), 2)
    f["poa_total"] = total
    which = " and ".join(f"{p['which']} £{p['amount']:,.2f}" for p in poa)
    return "CHECK", [f"Payments on account for {tax_year} on HMRC's statement: {which}, £{total:,.2f} in all. Put on Tax "
                     f"calculation as already paid where nothing was entered (R-FAM-03); check the second is paid by 31 "
                     f"July."]
