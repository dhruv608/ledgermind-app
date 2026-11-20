"""A letting agent's statement read (R-SA105-01 to 11): for each property on it, the rent collected and the costs
the agent paid, each under its SA105 heading (property.py HEADINGS). Money the agent paid over to the landlord, and a
tenant's deposit, are neither income nor a cost and are left out. Mortgage interest is a residential finance cost (the
20% credit, never an expense, R-SA105-05); an improvement is capital (R-SA105-08). Code checks every reading:

  tax year    only lines dated in the return's tax year are kept; a statement wholly in another year is not used
  owner       the person is one of the landlords, when landlords are printed (R-IN-07)
  sense       amounts not negative; a property with no rent and no cost is dropped
  readers     a scan is read by two models; a rent total they do not agree on is a point to check"""

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.interest import _tax_year_of
from backend.app.sa.extract.p60 import owner

HEADS = ("RENT", "RATES_INSURANCE", "REPAIRS", "PROFESSIONAL", "SERVICES", "OTHER", "DOMESTIC_ITEMS", "RES_FINANCE",
         "CAPITAL", "NOT_INCOME")

PROMPT = """This is a UK letting agent's statement (or a landlord's rent statement) sent for a Self Assessment return.
First say whether it is one: "is_rent_statement" is true only for a letting agent's statement, a landlord's rent
statement or a rent schedule of a let property; false for a bank statement, a person's own bookkeeping or accounts
pack, an invoice or a letter (then leave "properties" empty).
Read every property on it and every money line, in the order printed. Reply with one JSON object only:
{"is_rent_statement": true or false, "agent": "agent's name or null", "landlords": ["each landlord's full name as printed"],
 "currency": "GBP, or the currency the amounts are in (NZD, EUR...)",
 "period_from": "YYYY-MM-DD or null", "period_to": "YYYY-MM-DD or null",
 "properties": [{"address": "the let property's address as printed",
                 "country": "GBR for a property in the UK, else the country's 3-letter code (NZL, ESP...)",
                 "lines": [{"date": "YYYY-MM-DD", "description": "as printed", "amount": number,
                            "heading": one of:
                              "RENT" rent collected from the tenant (gross, before the agent's fees),
                              "PROFESSIONAL" the agent's management, letting or renewal fee, inventory, legal fees,
                              "REPAIRS" repairs, maintenance, cleaning, gardening, safety certificates and checks,
                              "RATES_INSURANCE" insurance, ground rent, service charge, council tax, water,
                              "SERVICES" utilities or services the landlord pays for the tenant,
                              "DOMESTIC_ITEMS" a replacement fridge, bed, sofa or carpet,
                              "RES_FINANCE" mortgage interest,
                              "CAPITAL" an improvement (an extension, a new kitchen where there was none, solar panels),
                              "OTHER" any other cost of letting,
                              "NOT_INCOME" money paid to the landlord, a deposit taken or returned, a balance brought
                                           or carried forward, a total line}]}]}
Money as plain numbers with pence (no £ or commas), every amount positive. Where a cost shows NET, VAT and GROSS,
use the GROSS amount (the landlord pays the VAT). Use the year from the statement period.
A profit and loss or statement with several columns (this year and last year; the whole property and one owner's
share): read ONLY the column headed with the LATEST year (often the first column, e.g. '2026' before '2025'), for the
whole property (not a 'per partner' or 'share' column), one line per item. Never last year's column. A dash or a
blank in this year's column means nothing this year: leave that item out (do not take last year's figure)."""

COST_WORDS = (
    (re.compile(r"\b(management|letting|renewal|tenant find|inventory|referenc|legal)\b", re.I), "PROFESSIONAL"),
    (re.compile(r"\b(insurance|ground rent|service charge|council tax|water)\b", re.I), "RATES_INSURANCE"),
    (re.compile(r"\b(repair|plumb|electric|boiler|gas safe|gas safety|eicr|clean|garden|maintenance|locksmith)\b", re.I), "REPAIRS"),
    (re.compile(r"\bmortgage interest\b", re.I), "RES_FINANCE"),
)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(abs(float(str(v).replace(",", "").replace("£", "").strip())), 2)
    except ValueError:
        return None


def with_text(f: Dict[str, Any], text: str) -> Dict[str, Any]:
    """A text page's lines held to its text: an item whose first value after its name is a dash ('Tenant gift  -  -
    52.00': nothing this year, 52.00 is last year's column) is dropped."""
    low = (text or "").lower()
    # Only a statement with columns: this year and last year, or the whole and a partner's share
    if not (re.search(r"per (partner|person|owner)", low) or len(set(re.findall(r"^\s*(20\d\d)\s*$", low, re.M))) >= 2):
        return f
    rows = [r.strip() for r in low.splitlines()]
    for p in f.get("properties") or []:
        keep = []
        for l in p["lines"]:
            name = (l.get("description") or "").lower().strip()
            at = next((i for i, r in enumerate(rows) if r == name), None)
            if at is not None:
                # this year's value: the first row after the name that is a figure or a dash ('$' rows skipped)
                nxt = next((r for r in rows[at + 1:at + 6] if r and r != "$"), "")
                if nxt in ("-", "nil"):
                    continue
            keep.append(l)
        p["lines"] = keep
    return f


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    props = []
    for p in a.get("properties") or []:
        lines = []
        for l in p.get("lines") or []:
            amount = _num(l.get("amount"))
            head = str(l.get("heading") or "").upper()
            if not amount:
                continue
            desc = str(l.get("description") or "").strip()
            if head not in HEADS:
                head = next((h for rx, h in COST_WORDS if rx.search(desc)), "OTHER")
            if re.search(r"depreciat", desc, re.I):
                head = "NOT_INCOME"            # never a cost, UK or foreign (R-SA105-08): left out, noted in the checks
            lines.append({"on": l.get("date"), "description": desc[:255], "heading": head, "amount": amount})
        if lines:
            country = str(p.get("country") or "GBR").upper()[:3]
            props.append({"address": str(p.get("address") or "").strip() or "Let property", "lines": lines,
                          "country": "GBR" if country in ("UK", "GB", "") else country})
    return {"is_rent_statement": a.get("is_rent_statement") is not False,
            "agent": (a.get("agent") or "").strip() or None, "landlords": [x for x in (a.get("landlords") or []) if x],
            "currency": str(a.get("currency") or "GBP").upper()[:3],
            "period_from": a.get("period_from"), "period_to": a.get("period_to"), "properties": props}


def overseas(f: Dict[str, Any]) -> bool:
    """A property abroad or amounts not in pounds: not on the UK Property page (SA106, in £)."""
    return f.get("currency", "GBP") != "GBP" or any(p.get("country", "GBR") != "GBR" for p in f.get("properties") or [])


def march_basis(f: Dict[str, Any]) -> bool:
    """A year's figures drawn up to 31 March: from 1 to 5 April to a day in March or 1 to 4 April a year later."""
    a, b = str(f.get("period_from") or ""), str(f.get("period_to") or "")
    if len(a) < 10 or len(b) < 10 or not (a[5:7] == "04" and a[8:10] <= "05"):
        return False
    return int(b[:4]) == int(a[:4]) + 1 and (b[5:7] == "03" or (b[5:7] == "04" and b[8:10] <= "04"))


def _march_year(on: Optional[str]) -> Optional[str]:
    """The tax year of a date in a year to 31 March: April to March."""
    s = str(on or "")
    if len(s) < 7 or not s[:4].isdigit() or not s[5:7].isdigit():
        return None
    y = int(s[:4]) - (1 if int(s[5:7]) < 4 else 0)
    return f"{y}-{(y + 1) % 100:02d}"


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """(status, the reasons a person must look) for a read letting statement; lines outside the tax year dropped."""
    if not f.get("is_rent_statement", True):
        f["properties"] = []
        return "FILED", ["Not a letting statement (a bank statement or the client's own records): filed, not read as rent."]
    if not f.get("properties"):
        return "CHECK", ["No rent or cost could be read from this statement: enter them on the Property page."]
    notes: List[str] = []
    # A year's figures to 31 March (1 April to 31 March, the client's own sheet): the tax year itself (ITTOIA 2005 s275A,
    # PIM1015), so its 1 to 5 April lines belong to it
    year_of = _march_year if march_basis(f) else _tax_year_of
    years = {year_of(f.get("period_from")), year_of(f.get("period_to"))} - {None}
    dated = [l for p in f["properties"] for l in p["lines"] if year_of(l.get("on"))]
    in_year = [l for l in dated if year_of(l["on"]) == tax_year]
    if (dated and not in_year) or (not dated and years and tax_year not in years):
        return "OTHER_YEAR", [f"This statement is not for {tax_year}: not used."]
    dropped = 0
    for p in f["properties"]:
        keep = [l for l in p["lines"] if not year_of(l.get("on")) or year_of(l["on"]) == tax_year]
        dropped += len(p["lines"]) - len(keep)
        p["lines"] = keep
    if dropped:
        notes.append(f"{dropped} line{'s' if dropped > 1 else ''} dated outside {tax_year} left out.")
    if any(not l.get("on") for p in f["properties"] for l in p["lines"]):
        notes.append("Some lines have no date: check they belong to this tax year.")
    if person and f.get("landlords") and all(owner(x, person) == "OTHER" for x in f["landlords"]):
        f["other_person"] = True
        return "CHECK", [f"The landlord is {', '.join(f['landlords'])}, not {person}: not used. If it is theirs, confirm it."]
    if person and f.get("landlords") and not any(owner(x, person) is None for x in f["landlords"]):
        notes.append(f"The landlord's name is printed {', '.join(f['landlords'])}: counted, check it is {person} (R-IN-07).")
    dep = sum(l["amount"] for p in f["properties"] for l in p["lines"] if re.search(r"depreciat", l["description"], re.I))
    if dep:
        notes.append(f"Depreciation of {dep:,.2f} on the statement is left out: it is never a cost for tax (R-SA105-08).")
    if overseas(f):
        where = ", ".join(sorted({p["country"] for p in f["properties"] if p["country"] != "GBR"})) or "abroad"
        from backend.app.sa.fx import rate
        r = rate(f.get("currency") or "GBP", tax_year)
        return "CHECK", notes + ([f"An overseas property ({where}): put on Property abroad (SA106) in pounds at {r} "
                                  f"{f.get('currency', 'GBP')} to £1, HMRC's average for the year. Confirm the owner's share "
                                  f"and the foreign tax."] if r else
                                 [f"An overseas property ({where}), amounts in {f.get('currency', 'GBP')}: no HMRC rate in "
                                  f"the table; enter it on Property abroad in pounds by hand (SA106)."])
    if not f.get("agent"):
        # No agent named: it may be the client's own records (a monthly pack with bills and fuel in it). Its figures
        # wait for the accountant to confirm it is a rent statement
        f["unconfirmed"] = True
        notes.append("No letting agent is named: confirm this is a rent statement before its figures go on the "
                     "Property page.")
    if any(l["heading"] == "CAPITAL" for p in f["properties"] for l in p["lines"]):
        notes.append("An improvement is on the statement: not an expense; kept as capital for a later sale (R-SA105-08).")
    if second is not None:
        mine, theirs = rent(f), rent(clean(second))
        if abs(mine - theirs) > 0.005:
            notes.append(f"The two readers disagree on the rent (£{mine:,.2f} or £{theirs:,.2f}): look at the statement.")
    return ("CHECK" if notes else "READ"), notes


def rent(f: Dict[str, Any]) -> float:
    return round(sum(l["amount"] for p in f.get("properties") or [] for l in p["lines"] if l["heading"] == "RENT"), 2)


NUMBER_STREET = re.compile(r"\b(\d+[a-z]?)\b[\s,]+([a-z][a-z' ]+?)(?:,|\b(road|rd|street|st|close|lane|ln|avenue|ave|way|drive|dr|court|ct|place|pl|crescent|meadow|gardens|grove|terrace|row|walk)\b)", re.I)
WORD = re.compile(r"[a-z0-9]+")


def address_key(address: str) -> str:
    """'8, High Street, Anytown AB1' and '8 High Street' give the same key: the house number and the street."""
    m = NUMBER_STREET.search(address or "")
    if m:
        return f"{m.group(1).lower()} {' '.join(WORD.findall((m.group(2) + ' ' + (m.group(3) or '')).lower()))}".strip()
    return " ".join(WORD.findall((address or "").lower())[:3])


def same_property(a: str, b: str) -> bool:
    ka, kb = address_key(a), address_key(b)
    return bool(ka) and (ka == kb or ka in kb or kb in ka)
