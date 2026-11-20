"""A CIS payment and deduction statement read (R-SA103-10): the contractor, the tax month, the gross paid (excluding
VAT), the materials, the amount deducted. The deductions are tax already paid (SA103 'CIS deductions'); the turnover is
the gross, not the net paid into the bank. Code checks every reading:

  tax year    the tax month (ended the 5th) falls in the return's tax year
  owner       the subcontractor is the person (R-IN-07)
  sums        deduction = rate x (gross - materials), payable = gross - deduction; a rate of 0, 20 or 30%
  readers     a scan is read by two models; a deduction they do not agree on is a point to check"""

from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.interest import _tax_year_of
from backend.app.sa.extract.p60 import owner

RATES = (0, 20, 30)

PROMPT = """This is a UK Construction Industry Scheme (CIS) payment and deduction statement given by a contractor to a
subcontractor, sent for a Self Assessment return. Reply with one JSON object only (money as numbers with pence, no £):
{"contractor": "...", "contractor_ref": "employer's tax reference or null", "subcontractor": "full name as printed",
 "utr": "...", "month_end": "YYYY-MM-DD (the tax month ended on the 5th: '05 05 2024' is 2024-05-05)",
 "gross": number (gross amount paid excluding VAT), "materials": number or 0, "rate": number (20, 30 or 0),
 "deducted": number (amount deducted), "payable": number or null}"""


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(abs(float(str(v).replace(",", "").replace("£", "").replace("%", "").strip())), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    return {"contractor": (a.get("contractor") or "").strip() or None, "contractor_ref": a.get("contractor_ref"),
            "subcontractor": (a.get("subcontractor") or "").strip() or None, "month_end": a.get("month_end"),
            "gross": _num(a.get("gross")), "materials": _num(a.get("materials")) or 0.0, "rate": _num(a.get("rate")),
            "deducted": _num(a.get("deducted")), "payable": _num(a.get("payable"))}


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    if f.get("gross") is None or f.get("deducted") is None:
        return "CHECK", ["The gross paid or the deduction could not be read: enter them on Self-employment by hand."]
    year = _tax_year_of(f.get("month_end"))
    if year and year != tax_year:
        return "OTHER_YEAR", [f"This statement is for {year}, not {tax_year}: not used."]
    notes: List[str] = []
    if not year:
        notes.append("The tax month is not clear: check it falls in this tax year.")
    if person and f.get("subcontractor") and owner(f["subcontractor"], person) == "OTHER":
        f["other_person"] = True
        return "CHECK", [f"This statement is for {f['subcontractor']}, not {person}: not used. If it is theirs, confirm it."]
    liable = round(f["gross"] - f["materials"], 2)
    rate = f.get("rate")
    if rate is not None and rate not in RATES:
        notes.append(f"A deduction rate of {rate:g}% is not a CIS rate (0, 20 or 30%): look at the statement.")
    elif rate is not None and abs(round(liable * rate / 100, 2) - f["deducted"]) > 1:
        notes.append(f"The deduction £{f['deducted']:,.2f} is not {rate:g}% of the amount liable £{liable:,.2f}: look at "
                     f"the statement.")
    if f.get("payable") is not None and abs(f["gross"] - f["deducted"] - f["payable"]) > 1:
        notes.append("Gross less the deduction is not the amount payable: look at the statement.")
    if second is not None:
        s = clean(second)
        if s.get("deducted") is not None and abs(s["deducted"] - f["deducted"]) > 0.005:
            notes.append(f"The two readers disagree on the deduction (£{f['deducted']:,.2f} or £{s['deducted']:,.2f}).")
    return ("CHECK" if notes else "READ"), notes
