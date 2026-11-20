"""Receipts, bills and invoices of a sole trader's business (sales and purchase invoices; receipts by customer
and costs by SA103 heading). A cost counts only when it is wholly and exclusively for
the trade (ITTOIA 2005 s34): the reader marks food shopping, clothes and the like as personal, and a vehicle, machine
or computer kept for the trade as capital (capital allowances, not a cost). Code checks every reading:

  sums        VAT not more than the total; a bill with no total or no date is a point to check
  year        bills all more than a year outside the tax year: another year's, not used
  readers     a scan is read by two models; totals they do not agree on are a point to check
  not a bill  a quote, an order confirmation, a statement of account or a delivery note gives no bills: filed"""

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

PROMPT = """This is a receipt, bill or invoice sent for a UK sole trader's Self Assessment return: a sale (an invoice
the person issued to a customer) or a purchase (a bill or till receipt the person paid). A page may hold several
receipts: give each one. Reply with one JSON object only:
{"bills": [{"kind": "SALE" or "PURCHASE", "issuer": "the business or person that issued it, as printed",
            "customer": "who it is addressed to, as printed, or null", "date": "YYYY-MM-DD (the invoice or receipt date)",
            "number": "invoice or receipt number, or null", "total": number (the amount paid or due, VAT included),
            "vat": number or 0, "paid_by": "card", "cash", "bank" or null, "what": "a few words: what was bought or sold",
            "self_billed": true or false (a self-billing invoice or pay statement a customer made out for the person:
              the person's income, their name and UTR on it, 'Total Income' or 'Total Paid' to them),
            "heading": one of COST_OF_SALES (goods or materials for resale or used up in the work), SUBCONTRACTORS,
              STAFF, TRAVEL (fuel, parking, trains, taxis, vehicle repairs, servicing, insurance, road tax),
              PREMISES (rent, rates, power, business insurance), REPAIRS (repairs to premises or equipment),
              OFFICE (phone, internet, stationery, postage, software), ADVERTISING, ENTERTAINING (meals or drinks for
              clients), FINANCE (bank or card charges), PROFESSIONAL (accountant, legal), OTHER (other business costs,
              small tools, protective clothing), CAPITAL (a vehicle, machine, computer or equipment kept for the trade),
              PERSONAL (food shopping, ordinary clothes, a meal for the person, anything not for the trade);
              for a SALE: TURNOVER}]}
Money as plain numbers with pence (no £ or commas). The person's own list of jobs or takings (handwritten or typed,
one line per job with its price) is a list of sales: give each line as a SALE, its date and price. A quote, an
estimate, an order confirmation with no payment, a statement of account or a delivery note is not a bill: give
"bills": []."""

WHO = """
The person whose return this is: {name}. A bill the person issued, or one paying the person for their own work (day
rates, labour, services they gave), is a SALE, its issuer the person and its customer who pays; a bill the person paid
is a PURCHASE."""


def prompt_for(person: Optional[str]) -> str:
    """The reader's prompt, told whose return it is (otherwise a client's invoice to a customer can be read as the
    customer's bill when the customer's name heads the page)."""
    name = (person or "").strip()
    return PROMPT + (WHO.format(name=name) if name else "")


HEADINGS = {"COST_OF_SALES", "SUBCONTRACTORS", "STAFF", "TRAVEL", "PREMISES", "REPAIRS", "OFFICE", "ADVERTISING",
            "ENTERTAINING", "FINANCE", "PROFESSIONAL", "OTHER", "CAPITAL", "PERSONAL", "TURNOVER"}


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(str(v).replace(",", "").replace("£", "").strip()), 2)
    except ValueError:
        return None


def _day(v: Any) -> Optional[str]:
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    bills = []
    for b in (answer or {}).get("bills") or []:
        total = _num(b.get("total"))
        if total is None or total == 0:
            continue
        # A self-billing invoice is made out by the customer, to the person: it is the person's sale
        self_billed = b.get("self_billed") is True
        kind = "SALE" if self_billed or str(b.get("kind") or "").upper() == "SALE" else "PURCHASE"
        heading = str(b.get("heading") or "").upper().strip()
        heading = "TURNOVER" if kind == "SALE" else (heading if heading in HEADINGS - {"TURNOVER"} else "OTHER")
        bills.append({"kind": kind, "issuer": (str(b.get("issuer") or "").strip() or None),
                      "customer": (str(b.get("customer") or "").strip() or None), "date": _day(b.get("date")),
                      "number": (str(b.get("number") or "").strip() or None), "total": abs(total),
                      "vat": abs(_num(b.get("vat")) or 0.0), "paid_by": b.get("paid_by"),
                      "what": str(b.get("what") or "").strip()[:120], "heading": heading, "self_billed": self_billed})
    return {"bills": bills}


def _year_bounds(tax_year: str) -> Tuple[str, str]:
    start = int(tax_year[:4])
    return date(start - 1, 4, 6).isoformat(), date(start + 2, 4, 5).isoformat()


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """(status, the reasons a person must look) for a read receipt or invoice."""
    bills = f.get("bills") or []
    if not bills:
        return "FILED", ["Not a bill (a quote, an order, a statement of account or a delivery note), or nothing could be "
                         "read: filed."]
    notes: List[str] = []
    # A sale is the person's own invoice: a bill addressed to the person (not a self-billing one) is a purchase whatever
    # the reader called it (a garage's bill to the client is not their sale)
    if person:
        from backend.app.sa.extract.p60 import owner
        for b in bills:
            if b["kind"] == "SALE" and not b.get("self_billed") and b["customer"] and owner(b["customer"], person) != "OTHER":
                b["kind"] = "PURCHASE"
                b["heading"] = "OTHER" if b["heading"] == "TURNOVER" else b["heading"]
            # A bill the person issued is their sale, never their cost (the reader may call the person's own
            # 'payment for work' invoices purchases)
            elif b["kind"] == "PURCHASE" and b["issuer"] and owner(b["issuer"], person) is None:
                b["kind"], b["heading"] = "SALE", "TURNOVER"
    lo, hi = _year_bounds(tax_year)
    dated = [b["date"] for b in bills if b["date"]]
    if dated and all(not lo <= d <= hi for d in dated):
        return "OTHER_YEAR", [f"Dated {', '.join(sorted(set(dated)))}: more than a year outside {tax_year}, not used."]
    for b in bills:
        who = b["issuer"] or "A bill"
        if b["vat"] > b["total"] + 0.005:
            notes.append(f"{who}: the VAT is more than the total.")
        if not b["date"]:
            notes.append(f"{who}: no date could be read.")
    if second is not None:
        s = clean(second)
        mine, theirs = round(sum(b["total"] for b in bills), 2), round(sum(b["total"] for b in s["bills"]), 2)
        if abs(mine - theirs) > 0.005:
            notes.append(f"The two readers disagree on the total (£{mine:,.2f} or £{theirs:,.2f}): look at the bill.")
    return ("CHECK" if notes else "READ"), notes
