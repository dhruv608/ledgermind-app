"""Capital allowances of a business, line by line (HS252; CAA 2001), so the return gets them under the right boxes.

  AIA        Annual Investment Allowance: 100% of plant and machinery bought (not cars), up to £1m a year
  MAIN       main pool: 18% writing down allowance on the pool value (brought forward plus additions less disposals)
  SPECIAL    special rate pool (cars over 50g/km, integral features): 6%
  SMALL      a main or special pool of £1,000 or less: written off in full (CA23225)
  ZEC        a new zero-emission car: 100% first-year allowance
  FYA        other 100% and enhanced allowances (electric charge points...)
  SBA        structures and buildings: 3% a year of the qualifying cost
  BALANCING  balancing allowance on a sale or when the business stops (the amount worked out)

Private use cuts the allowance, not the pool: the pool still goes down by the full writing down allowance.
Cash basis: equipment is an expense when paid; only cars get capital allowances (BIM72067).
A period other than 12 months scales the writing down allowances: noted, not worked out."""

from typing import Dict, List

from backend.app.sa.engine.calc import _p, rates_for

KINDS = {"AIA": "Annual Investment Allowance", "MAIN": "Main pool (18%)", "SPECIAL": "Special rate pool (6%)",
         "SMALL": "Small pool written off (£1,000 or less)", "ZEC": "Zero-emission car (100%)",
         "FYA": "Other 100% and enhanced allowances", "SBA": "Structures and buildings (3%)",
         "BALANCING": "Balancing allowance"}
# SA103S box, SA103F box
BOXES = {"AIA": ("23", "49"), "MAIN": ("25", "50"), "SPECIAL": ("25", "51"), "SMALL": ("24", "50"), "ZEC": ("24.1", "52.1"),
         "FYA": ("25", "55"), "SBA": ("25.1", "53"), "BALANCING": ("25", "56")}
CARS_ONLY = ("MAIN", "SPECIAL", "ZEC", "BALANCING")


def one(a, tax_year: str) -> Dict:
    r = rates_for(tax_year)["capital_allowances"]
    amount = float(a.amount or 0)
    private = float(a.private_use or 0)
    if a.kind == "AIA":
        full = min(amount, r["aia_limit"])
    elif a.kind == "MAIN":
        full = amount if amount <= r["small_pool"] else amount * r["main"]
    elif a.kind == "SPECIAL":
        full = amount if amount <= r["small_pool"] else amount * r["special"]
    elif a.kind == "SBA":
        full = amount * r["sba"]
    else:                                      # SMALL, ZEC, FYA, BALANCING: the amount itself
        full = amount
    kind = a.kind
    if kind in ("MAIN", "SPECIAL") and amount <= r["small_pool"]:
        kind = "SMALL"
    allowance = _p(full * (1 - private))
    carried = _p(amount - full) if a.kind in ("MAIN", "SPECIAL") else 0.0
    return {"id": a.id, "kind": kind, "entered_kind": a.kind, "label": KINDS[kind], "description": a.description,
            "amount": amount, "private_use": private, "allowance": allowance, "pool_cf": carried,
            "boxes": ("24", "51") if kind == "SMALL" and a.kind == "SPECIAL" else BOXES[kind]}


def for_business(rows: List, tax_year: str, cash_basis: bool) -> Dict:
    lines = [one(a, tax_year) for a in rows]
    issues = []
    if cash_basis and any(l["entered_kind"] not in CARS_ONLY for l in lines):
        issues.append("Cash basis: equipment is an expense when paid, not a capital allowance; only cars get capital "
                      "allowances (BIM72067). Move the equipment to the costs, or the business to traditional accounting.")
    aia = sum(l["amount"] for l in lines if l["entered_kind"] == "AIA")
    if aia > rates_for(tax_year)["capital_allowances"]["aia_limit"]:
        issues.append("More than £1m of Annual Investment Allowance: the rest goes into the pools.")
    return {"lines": lines, "total": round(sum(l["allowance"] for l in lines), 2), "issues": issues}


def boxes(lines: List[Dict], page: str) -> List[Dict]:
    """The allowances added up by box on the business's page (SA103S or SA103F)."""
    col = 0 if page == "SA103S" else 1
    by: Dict[str, float] = {}
    for l in lines:
        b = l["boxes"][col]
        by[b] = round(by.get(b, 0.0) + l["allowance"], 2)
    return [{"box": b, "value": v} for b, v in sorted(by.items(), key=lambda x: float(x[0]))]
