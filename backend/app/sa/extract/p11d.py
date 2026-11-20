"""A P11D (or P11D(b) copy for the employee) read (R-SA102-03, -07): each benefit's cash equivalent under its SA102
box. A benefit the employer taxed through the payroll is already in the P60's pay and is not added again (PAYE58701).
Code checks every reading:

  tax year    the P11D is for the return's tax year
  owner       the employee is the person (NI number first, then the name: R-IN-07)
  readers     a scan is read by two models; a total they do not agree on is a point to check"""

from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.p60 import _ni, owner

# SA102 (2025-26): benefits from the P11D
BOXES = {"CAR": "9", "FUEL": "10", "MEDICAL": "11", "VOUCHERS": "12", "GOODS": "13", "ACCOMMODATION": "14",
         "OTHER": "15", "EXPENSES": "16"}
LABELS = {"CAR": "Company cars and vans", "FUEL": "Fuel for company cars and vans", "MEDICAL": "Private medical and dental insurance",
          "VOUCHERS": "Vouchers, credit cards and excess mileage allowance", "GOODS": "Goods and other assets provided",
          "ACCOMMODATION": "Accommodation provided", "OTHER": "Other benefits (including interest-free and low interest loans)",
          "EXPENSES": "Expenses payments received"}

# A car's cash equivalent is its list price times at most 37%: one above this is most likely the list price read
CAR_CHECK = 30000.0

PROMPT = """This is a UK P11D (expenses and benefits for an employee) sent for a Self Assessment return.
First say whether it is one: "is_p11d" is true only for an employer's P11D form (or the copy of it given to the
employee); false for a car lease or rental agreement, an invoice or a letter that mentions a P11D value.
Reply with one JSON object only:
{"is_p11d": true or false, "employee": "full name as printed", "ni_number": "...", "employer": "...", "paye_ref": "...",
 "tax_year": "the year as 2025-26 (the year to 5 April 2026 is 2025-26)",
 "benefits": [{"kind": "CAR" | "FUEL" | "MEDICAL" | "VOUCHERS" | "GOODS" | "ACCOMMODATION" | "OTHER" | "EXPENSES",
               "description": "as printed", "amount": number (the cash equivalent or taxable amount: never the car's
               list price, the cost or the amount the employee made good),
               "payrolled": true or false (marked as taxed through the payroll)}]}
Money as plain numbers with pence (no £ or commas). Leave out a benefit with no taxable amount."""


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(abs(float(str(v).replace(",", "").replace("£", "").strip())), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    out = []
    for b in a.get("benefits") or []:
        kind = str(b.get("kind") or "OTHER").upper()
        amount = _num(b.get("amount"))
        if amount:
            out.append({"kind": kind if kind in BOXES else "OTHER", "description": str(b.get("description") or "").strip(),
                        "amount": amount, "payrolled": bool(b.get("payrolled"))})
    return {"is_p11d": a.get("is_p11d") is not False, "employee": (a.get("employee") or "").strip() or None, "ni_number": a.get("ni_number"),
            "employer": (a.get("employer") or "").strip() or None, "paye_ref": a.get("paye_ref"),
            "tax_year": a.get("tax_year"), "benefits": out}


def checks(f: Dict[str, Any], tax_year: str, ni_number: Optional[str] = None, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    if not f.get("is_p11d", True):
        f["benefits"] = []
        return "FILED", ["Not a P11D (a lease, an invoice or a letter): filed, not read as benefits."]
    if not f.get("benefits"):
        return "CHECK", ["No benefit with a taxable amount could be read: enter it on Employment by hand."]
    if f.get("tax_year") and f["tax_year"] != tax_year:
        return "OTHER_YEAR", [f"This P11D is for {f['tax_year']}, not {tax_year}: not used."]
    notes: List[str] = []
    mine, theirs = _ni(ni_number), _ni(f.get("ni_number"))
    if (mine and theirs and mine != theirs) or (not (mine and theirs) and owner(f.get("employee"), person) == "OTHER"):
        f["other_person"] = True
        return "CHECK", [f"This P11D is not {person or 'the person'}'s: not used. If it is theirs, confirm it (R-IN-07)."]
    payrolled = [b for b in f["benefits"] if b["payrolled"]]
    if payrolled:
        notes.append(f"{', '.join(b['description'] or LABELS[b['kind']] for b in payrolled)}: taxed through the payroll, "
                     f"already in the P60's pay: not added again (R-SA102-07).")
    if any(b["kind"] == "CAR" and b["amount"] > CAR_CHECK for b in f["benefits"]):
        notes.append(f"A car benefit over £{CAR_CHECK:,.0f}: check it is the cash equivalent on the P11D, not the car's "
                     f"list price.")
    if any(b["kind"] == "EXPENSES" for b in f["benefits"]):
        notes.append("Expenses payments are on the P11D: claim the business part as employment expenses if the client "
                     "has the receipts (SA102 boxes 17 to 20).")
    if second is not None:
        a = round(sum(b["amount"] for b in f["benefits"]), 2)
        b = round(sum(x["amount"] for x in clean(second)["benefits"]), 2)
        if abs(a - b) > 0.005:
            notes.append(f"The two readers disagree on the benefits (£{a:,.2f} or £{b:,.2f}): look at the P11D.")
    return ("CHECK" if notes else "READ"), notes
