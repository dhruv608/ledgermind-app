"""The client's own income and expenses sheet in their own layout (not the firm's Profit and Loss template, which
client_sheet.py reads by code): read by the model from the sheet's text into the same rows, the trade's only.

Rows that are not the trade's are left out (bank interest, a pension, wages, rent from a property, benefits, personal
spending): those have their own pages. Totals and subtotals are not rows. Two kinds of cost are kept but left to the
accountant (both are simplified expenses the person may or may not use):

  use of home   the flat rate goes by the hours worked at home a month (R-SA103-13, ITTOIA s94H)
  mileage       each journey is business or commuting, and the flat rate per mile is a choice (R-SA103-12, s94D)"""

import re
from typing import Any, Dict, List, Optional

from backend.app.sa.extract.client_sheet import _day, _num

PROMPT = """This is a spreadsheet a self-employed person (or their bookkeeper) keeps of their own income and expenses,
sent for their UK tax return. Read the rows of their BUSINESS: the money the business earned and what it spent.
Reply with one JSON object only:
{"is_business_sheet": true or false (false when it has no business income or costs at all, e.g. a summary of pensions,
 interest and a property),
 "rows": [{"date": "YYYY-MM-DD or null", "detail": "what it is, as written", "party": "the customer or supplier, or null",
           "kind": "INCOME" (money the business earned: fees, sales, invoices paid) or "EXPENSE" (a business cost) or
                   "NOT_BUSINESS" (bank interest, a pension, wages or salary, rent from a property, a benefit, a
                   bank's member reward, a personal cost or pension contribution, a transfer),
           "amount": number (the row's business amount in pounds: where the sheet applies a business-use percentage or
                     multiplies a monthly figure, the result it shows), "miles": number or null,
           "use_of_home": true or false (a cost of working at home: heating, electricity, broadband for home office),
           "mileage": true or false (a claim per mile for a car or van)}]}
A property letting is not the business here: its rent and its costs are NOT_BUSINESS (is_business_sheet is false
when the sheet is only about a let property). Leave out totals, subtotals and headings. Money as plain numbers with pence (no £ or commas). One row per amount."""


def looks_like(text: str, leaf: str) -> bool:
    """A spreadsheet with both income and expenses on it (its sheets or headings name them)."""
    head = (text or "")[:6000]
    return bool(re.search(r"\bincome\b", head, re.I) and re.search(r"\bexpen(ses?|diture)\b", head, re.I))


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The answer as client_sheet rows (on, detail, party, income, expense, miles, decide), the business's only."""
    a = answer or {}
    rows: List[Dict[str, Any]] = []
    for r in a.get("rows") or []:
        kind = str(r.get("kind") or "").upper()
        amount = abs(_num(r.get("amount")))
        if kind not in ("INCOME", "EXPENSE") or not amount:
            continue
        decide = "use of home" if r.get("use_of_home") else "mileage" if r.get("mileage") else None
        rows.append({"on": _day(r.get("date")), "detail": str(r.get("detail") or "").strip()[:200],
                     "party": str(r.get("party") or "").strip()[:120],
                     "income": amount if kind == "INCOME" else 0.0, "expense": amount if kind == "EXPENSE" else 0.0,
                     "miles": _num(r.get("miles")) if decide == "mileage" else 0.0, "decide": decide})
    return {"is_business_sheet": a.get("is_business_sheet") is not False and bool(rows), "rows": rows, "own_layout": True}
