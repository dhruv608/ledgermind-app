"""Dividend vouchers and broker tax certificates read (R-SAV-04): each dividend with its company and payment date,
taxed when paid (ITTOIA s383-386). A dividend from the person's own company is taken from the company's books by the
director module, not from a voucher; a dividend inside an ISA is left out (R-SAV-05). Code checks every reading:

  tax year    only dividends paid in the return's tax year are kept
  owner       the shareholder is the person, when a name is printed (R-IN-07)
  readers     a scan is read by two models; a total they do not agree on is a point to check"""

from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.interest import _tax_year_of
from backend.app.sa.extract.p60 import owner

PROMPT = """This is a UK dividend voucher, dividend confirmation or broker's consolidated tax certificate sent for a
Self Assessment return. Read every dividend on it. Reply with one JSON object only:
{"shareholder": "the shareholder's full name as printed or null", "isa": true or false (held in an ISA),
 "dividends": [{"company": "the paying company", "pay_date": "YYYY-MM-DD", "amount": number (the dividend paid, not
                the number of shares)}]}
Money as plain numbers with pence (no £ or commas). Leave out interest, fees and the value of holdings."""


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(abs(float(str(v).replace(",", "").replace("£", "").strip())), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    divs = [{"company": str(d.get("company") or "").strip() or "Dividend", "pay_date": d.get("pay_date"),
             "amount": _num(d.get("amount"))} for d in a.get("dividends") or []]
    return {"shareholder": (a.get("shareholder") or "").strip() or None, "isa": bool(a.get("isa")),
            "dividends": [d for d in divs if d["amount"]]}


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    if not f.get("dividends"):
        return "CHECK", ["No dividend could be read: enter it on Dividends by hand."]
    notes: List[str] = []
    dated = [d for d in f["dividends"] if _tax_year_of(d.get("pay_date"))]
    if dated and not any(_tax_year_of(d["pay_date"]) == tax_year for d in dated):
        return "OTHER_YEAR", [f"No dividend on this voucher was paid in {tax_year}: not used."]
    keep = [d for d in f["dividends"] if not _tax_year_of(d.get("pay_date")) or _tax_year_of(d["pay_date"]) == tax_year]
    if len(keep) < len(f["dividends"]):
        notes.append(f"{len(f['dividends']) - len(keep)} dividend(s) paid outside {tax_year} left out.")
    f["dividends"] = keep
    if any(not d.get("pay_date") for d in keep):
        notes.append("A dividend has no payment date: check it was paid in this tax year (taxed when paid).")
    if person and f.get("shareholder") and owner(f["shareholder"], person) == "OTHER":
        f["other_person"] = True
        return "CHECK", [f"The shareholder is {f['shareholder']}, not {person}: not used. If it is theirs, confirm it."]
    if f.get("isa"):
        notes.append("Held in an ISA: the dividends are kept but left out of the figures (R-SAV-05).")
    if second is not None:
        mine = round(sum(d["amount"] for d in f["dividends"]), 2)
        theirs = round(sum(d["amount"] for d in clean(second)["dividends"]
                           if not _tax_year_of(d.get("pay_date")) or _tax_year_of(d["pay_date"]) == tax_year), 2)
        if abs(mine - theirs) > 0.005:
            notes.append(f"The two readers disagree on the dividends (£{mine:,.2f} or £{theirs:,.2f}): look at the voucher.")
    return ("CHECK" if notes else "READ"), notes
