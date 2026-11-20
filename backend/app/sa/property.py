"""UK property (SA105), property by property as the firm's working paper sets it out, then pooled: a person's UK
lettings are one property business (PIM4210), so profits and losses of all properties are added together.

  headings    rent received, and the costs under the SA105 boxes: rent, rates, insurance, ground rents (24),
              repairs and maintenance (25), non-residential finance costs (26), legal, management and other
              professional fees (27), costs of services provided (28), other allowable expenses (29), replacement of
              domestic items (PIM3210); residential finance costs are never an expense (R-SA105-05, ITTOIA s272A):
              box 44, for the 20% credit; capital spending (an improvement) is kept on the page, out of the figures
              (R-SA105-08)
  share       the person's share of each property's income and costs (spouses 50/50 unless Form 17)
  allowance   the £1,000 property allowance for the whole property business instead of every expense: taxable
              = the person's rents less £1,000, no finance cost credit (ITTOIA s783A-s783AR); ticked on any property,
              it applies to them all
  rent dates  each rent as received, never the latest rent times twelve (R-SA105-11)
  losses      a loss is carried forward against later UK property profits; last year's loss is set off first
  finance     unused residential finance costs from last year are added to this year's for the credit; what the
              credit cannot use carries forward (worked out with the tax, engine/calc.py)"""

from typing import Dict, List

from sqlalchemy.orm import Session

HEADINGS = {
    "RENT": ("Rents received", None),
    "RATES_INSURANCE": ("Rent, rates, insurance, ground rents", 24),
    "REPAIRS": ("Repairs and maintenance", 25),
    "NONRES_FINANCE": ("Loan interest (non-residential)", 26),
    "PROFESSIONAL": ("Legal, management and professional fees", 27),
    "SERVICES": ("Costs of services provided", 28),
    "OTHER": ("Other allowable expenses", 29),
    "DOMESTIC_ITEMS": ("Replacement of domestic items", 36),
    "RES_FINANCE": ("Residential finance costs (mortgage interest)", 44),
    "CAPITAL": ("Capital (improvement): not allowed", None),
}
EXPENSES = ("RATES_INSURANCE", "REPAIRS", "NONRES_FINANCE", "PROFESSIONAL", "SERVICES", "OTHER", "DOMESTIC_ITEMS")
ALLOWANCE = 1000.0


def one(prop, items: List, tax_year: str = "2025-26") -> Dict:
    """A property's totals (whole property, and the person's share), with the facts that change them:

      owner       a company's property is never on the SA105 (R-SA105-09): left out; spouses are 50/50 unless a Form 17
                  (ITA s836-837): another share between spouses is a decision
      kind        commercial: its loan interest is a normal expense, not the 20% credit (R-SA105-05)
      own home    a lodger in the client's own home: Rent-a-Room, £7,500 (£3,750 when shared) exempt if the rents are no
                  more; above it, the scheme (rents less the limit, no expenses) or actual figures: the accountant's
                  choice (R-SA105-10, ITTOIA s784-802); a former home: private residence relief on a sale
      dates       letting started or ended in the year; sold: to capital gains and the 60-day check"""
    from backend.app.sa.engine.calc import rates_for
    by: Dict[str, float] = {h: 0.0 for h in HEADINGS}
    for it in items:
        by[it.heading] = round(by.get(it.heading, 0.0) + float(it.amount or 0), 2)
    share = float(prop.share if prop.share is not None else 1)
    owner = getattr(prop, "owner", None) or "SOLE"
    notes: List[str] = []
    issues: List[Dict] = []
    if getattr(prop, "kind", None) == "COMMERCIAL" and by["RES_FINANCE"]:
        by["NONRES_FINANCE"] = round(by["NONRES_FINANCE"] + by["RES_FINANCE"], 2)
        by["RES_FINANCE"] = 0.0
        notes.append("Commercial let: its loan interest is a normal expense (box 26), not the 20% credit.")
    rents = by["RENT"]
    expenses = round(sum(by[h] for h in EXPENSES), 2)
    profit_whole = round(rents - expenses, 2)
    profit = round(profit_whole * share, 2)
    finance = round(by["RES_FINANCE"] * share, 2)
    in_pool, exempt = True, 0.0
    if owner == "COMPANY":
        in_pool, profit, finance = False, 0.0, 0.0
        notes.append("Owned by a company: its rent goes on the company's return, never on the SA105 (R-SA105-09).")
    if owner == "SPOUSE" and abs(share - 0.5) > 0.0001:
        issues.append({"key": f"form17:{prop.id}", "kind": "DECISION", "block": False,
                       "text": f"{prop.name}: owned with a spouse but not 50/50. That needs a Form 17 sent to HMRC (ITA s837); "
                               f"without one the income is split 50/50 (s836). Check the Form 17 was sent."})
    home = getattr(prop, "own_home", None)
    if home == "ROOM" and owner != "COMPANY":
        limit = rates_for(tax_year)["rent_a_room"] / (1 if owner == "SOLE" else 2)
        mine = round(rents * share, 2)
        choice = getattr(prop, "rent_a_room", None)
        scheme = round(max(0.0, mine - limit), 2)
        if mine <= limit and choice != "ACTUAL":
            in_pool, profit, finance, exempt = False, 0.0, 0.0, mine
            notes.append(f"Rent-a-Room: £{mine:,.2f} of rent is within the £{limit:,.0f} limit, so it is exempt.")
        elif choice == "RENT_A_ROOM":
            in_pool, profit, finance, exempt = False, scheme, 0.0, limit
            notes.append(f"Rent-a-Room scheme: rents less £{limit:,.0f}, no expenses: £{scheme:,.2f} taxable.")
        elif choice is None and mine > limit:
            issues.append({"key": f"rentaroom:{prop.id}", "kind": "DECISION", "block": False,
                           "text": f"{prop.name}: rooms let in the client's home. Rent-a-Room gives £{scheme:,.2f} taxable "
                                   f"(rents less £{limit:,.0f}); actual figures give £{profit:,.2f}. Choose one (R-SA105-10)."})
    elif home == "FORMER":
        notes.append("Was the client's home: on a sale, private residence relief for the months lived in plus the final 9.")
    start, end = int(tax_year[:4]), int(tax_year[:4]) + 1
    y0, y1 = f"{start}-04-06", f"{end}-04-05"
    lf, lt = getattr(prop, "let_from", None), getattr(prop, "let_to", None)
    if lf and y0 <= lf <= y1:
        notes.append(f"Letting started on {lf}: a new source this year; costs before it count only if they would have been "
                     f"allowed after (pre-letting, up to 7 years: PIM2505).")
    if lt and y0 <= lt <= y1:
        why = getattr(prop, "ended", None)
        notes.append(f"Letting ended on {lt}" + {"SOLD": ": sold", "MOVED_IN": ": the client moved in"}.get(why, "") + ".")
        if why == "SOLD":
            issues.append({"key": f"sold:{prop.id}", "kind": "DECISION", "block": True,
                           "text": f"{prop.name} was sold: enter the sale on Capital gains, and check the 60-day return."})
    dated = [getattr(it, "on", None) for it in items if it.heading == "RENT"]
    outside = [d for d in dated if d and ((lf and d < lf) or (lt and d > lt))]
    if outside:
        notes.append(f"{len(outside)} rent line(s) dated outside the letting dates: check them.")
    return {
        "id": prop.id, "name": prop.name, "share": share, "use_allowance": bool(prop.use_allowance),
        "headings": by, "rents": rents, "expenses": expenses, "profit_whole": profit_whole,
        "profit": profit, "finance_costs": finance, "capital": by["CAPITAL"], "in_pool": in_pool,
        "rent_a_room_exempt": exempt, "owner": owner, "notes": notes, "issues": issues,
    }


def pooled(db: Session, job, overseas: bool = False, allowance_left: float = ALLOWANCE) -> Dict:
    """The person's UK property business for the year (or, overseas, their overseas property business: a separate
    business with its own losses, ITTOIA s264-265): every property, the pooled profit after last year's losses, the loss
    to carry forward, and the finance costs for the credit (with last year's unused). The £1,000 property allowance is
    one for UK and overseas lettings together: what the UK business does not use is left for the overseas one."""
    from backend.app.sa.models import SAProperty, SAPropertyItem       # here: the totals above need no database
    props = [p for p in db.query(SAProperty).filter(SAProperty.job_id == job.id).order_by(SAProperty.id).all()
             if bool(p.country and p.country != "GBR") == overseas]
    items = db.query(SAPropertyItem).filter(SAPropertyItem.job_id == job.id).order_by(SAPropertyItem.on, SAPropertyItem.id).all()
    rows = [one(p, [i for i in items if i.property_id == p.id], job.tax_year) for p in props]
    # A sold property: the issue clears once a disposal is entered on Capital gains
    from backend.app.sa.models import SADisposal
    if db.query(SADisposal).filter(SADisposal.job_id == job.id).count():
        for r in rows:
            r["issues"] = [i for i in r["issues"] if not i["key"].startswith("sold:")]
    allowance = any(p.use_allowance for p in props) and allowance_left > 0     # none left: the expenses instead
    rents = round(sum(r["rents"] * r["share"] for r in rows if r["in_pool"]), 2)
    # Expenses under the £1,000 allowance and no finance costs: the allowance gives the lower profit, but it is the
    # client's choice (ITTOIA 2005 Part 3A), so a decision, never applied by itself
    pool = [r for r in rows if r["in_pool"]]
    costs = round(sum(r["expenses"] * r["share"] for r in pool), 2)
    # Expenses and finance costs together against the allowance: the allowance replaces both,
    # so mortgage interest does not rule it out on its own, it counts towards the costs given up
    finance_pool = round(sum(r["finance_costs"] for r in pool), 2)
    if (pool and not allowance and allowance_left > 0 and rents > 0
            and costs + finance_pool < min(allowance_left, rents)):
        pool[0]["issues"].append({"key": "allowance:pool", "kind": "DECISION", "block": False, "text": (
            f"Rents £{rents:,.2f} with £{costs:,.2f} of expenses"
            + (f" and £{finance_pool:,.2f} of finance costs" if finance_pool else "") +
            f": the £{min(allowance_left, rents):,.0f} property allowance instead gives £{max(rents - allowance_left, 0):,.2f} "
            f"taxable (the expenses give £{rents - costs:,.2f}"
            + (", with the 20% credit on the finance costs, which the allowance gives up" if finance_pool else "") +
            "). It is the client's choice (ITTOIA 2005 Part 3A): tick the property allowance on the property if wanted.")})
    allowance_used = round(min(max(allowance_left, 0.0), rents), 2) if allowance else 0.0
    room = round(sum(r["profit"] for r in rows if not r["in_pool"]), 2)        # Rent-a-Room scheme profits
    total = (round(rents - allowance_used, 2) if allowance else round(sum(r["profit"] for r in rows if r["in_pool"]), 2)) + room
    losses_bf = round(sum(float(p.losses_bf or 0) for p in props), 2)
    used = min(losses_bf, max(total, 0.0))
    profit = round(max(total - used, 0.0), 2)
    loss_cf = round(losses_bf - used + max(-total, 0.0), 2)
    finance = 0.0 if allowance else round(sum(r["finance_costs"] for r in rows) + sum(float(p.finance_bf or 0) for p in props), 2)
    boxes = {h: round(sum(r["headings"][h] * r["share"] for r in rows if r["in_pool"]), 2) for h in HEADINGS}
    # Rent-a-Room: the scheme's rents go in box 20 with the exempt amount in box 37; rents within the limit not at all
    scheme = [r for r in rows if not r["in_pool"] and r["profit"] > 0]
    boxes["RENT"] = round(boxes["RENT"] + sum(r["rents"] * r["share"] for r in scheme), 2)
    boxes["RENT_A_ROOM"] = round(sum(r["rent_a_room_exempt"] for r in scheme), 2)
    boxes["RENT_A_ROOM_ONLY"] = any(r["rent_a_room_exempt"] and r["profit"] == 0 for r in rows)
    by_country: Dict[str, Dict] = {}
    for p, r in zip(props, rows):
        c = by_country.setdefault(p.country or "GBR", {"country": p.country or "GBR", "profit": 0.0, "foreign_tax": 0.0})
        c["profit"] = round(c["profit"] + r["profit"], 2)
        c["foreign_tax"] = round(c["foreign_tax"] + float(p.foreign_tax or 0), 2)
    for p, r in zip(props, rows):
        r["country"] = p.country
    return {"properties": rows, "boxes": boxes, "countries": list(by_country.values()), "before_losses": total, "losses_bf": losses_bf, "losses_used": used,
            "profit": profit, "loss_cf": loss_cf, "finance_costs": finance,
            "allowance": allowance, "allowance_used": allowance_used}
