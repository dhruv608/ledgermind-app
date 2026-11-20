"""Self-employment (SA103), as TaxCalc's adjusted profit computation sets it out: turnover and other income, less the
allowable part of each cost under its SA103 heading, simplified expenses and capital allowances, gives the profit for
tax; or the £1,000 trading allowance instead of every cost.

  headings      SA103F boxes 15-16 (income) and 17-30 (costs); each cost keeps the part not allowed (private use,
                entertaining, fines) apart, and depreciation is never allowed (capital allowances instead)
  use of home   the flat rate by hours worked at home in a month: 25-50 £10, 51-100 £18, 101+ £26 (ITTOIA s94H)
  mileage       cars and vans 45p a mile for the first 10,000 business miles, 25p after; motorcycles 24p (s94D);
                the flat rate covers the vehicle's costs, so car costs and the rate are not both taken (BIM75005)
  allowance     the trading allowance takes £1,000 (or the income, if less) instead of every cost and capital
                allowance (ITTOIA s783A, BIM86050); worth it only when costs are under £1,000
  losses        last year's loss of the same trade is set off first; a loss this year carries forward unless the
                accountant claims it against other income this year or last (ITA 2007 s64, capped by
                s24A at the greater of £50,000 or 25% of adjusted total income): sa/income applies the choice
  short page    turnover under £90,000: SA103S (SAM121030), else SA103F"""

from typing import Dict, List, Optional

from backend.app.sa.engine.calc import rates_for

HEADINGS = {
    "TURNOVER": ("Turnover", 15, "income"),
    "OTHER_INCOME": ("Other business income", 16, "income"),
    "COST_OF_SALES": ("Cost of goods bought for resale", 17, "cost"),
    "SUBCONTRACTORS": ("Construction industry subcontractors", 18, "cost"),
    "STAFF": ("Wages, salaries and staff costs", 19, "cost"),
    "TRAVEL": ("Car, van and travel", 20, "cost"),
    "PREMISES": ("Rent, rates, power and insurance", 21, "cost"),
    "REPAIRS": ("Repairs and maintenance", 22, "cost"),
    "OFFICE": ("Phone, stationery and office costs", 23, "cost"),
    "ADVERTISING": ("Advertising and entertainment", 24, "cost"),
    "LOAN_INTEREST": ("Interest on bank and other loans", 25, "cost"),
    "FINANCE": ("Bank, credit card and finance charges", 26, "cost"),
    "BAD_DEBTS": ("Irrecoverable debts written off", 27, "cost"),
    "PROFESSIONAL": ("Accountancy, legal and professional fees", 28, "cost"),
    "DEPRECIATION": ("Depreciation and loss on sale", 29, "cost"),
    "OTHER": ("Other business expenses", 30, "cost"),
}
SHORT_PAGE_LIMIT = 90000                  # the default; each year's figure is in the rates table


def use_of_home(hours: int, months: int, tax_year: str) -> float:
    """The flat rate for months worked at home at least 25 hours."""
    if not hours or not months or hours < 25:
        return 0.0
    bands = sorted(((int(k), v) for k, v in rates_for(tax_year)["use_of_home"].items()), reverse=True)
    rate = next(v for k, v in bands if hours >= k)
    return float(rate * min(months, 12))


def mileage(car: int, motorcycle: int, tax_year: str) -> float:
    m = rates_for(tax_year)["mileage"]
    car = car or 0
    first = min(car, m["first_miles"])
    return round(first * m["car_first"] + (car - first) * m["car_after"] + (motorcycle or 0) * m["motorcycle"], 2)


def one(biz, items: List, tax_year: str, allowances: Optional[Dict] = None) -> Dict:
    """A business's adjusted profit computation. allowances: its capital allowance lines worked out (allowances.py),
    whose total replaces the single figure."""
    by = {h: {"amount": 0.0, "disallowed": 0.0} for h in HEADINGS}
    for it in items:
        b = by.setdefault(it.heading, {"amount": 0.0, "disallowed": 0.0})
        b["amount"] = round(b["amount"] + float(it.amount or 0), 2)
        # Depreciation is never allowed: all of it is disallowed
        b["disallowed"] = round(b["disallowed"] + (float(it.amount or 0) if it.heading == "DEPRECIATION" else float(it.disallowed or 0)), 2)
    income = round(sum(by[h]["amount"] for h, v in HEADINGS.items() if v[2] == "income"), 2)
    costs = round(sum(by[h]["amount"] for h, v in HEADINGS.items() if v[2] == "cost"), 2)
    disallowed = round(sum(by[h]["disallowed"] for h, v in HEADINGS.items() if v[2] == "cost"), 2)
    accounts_profit = round(income - costs, 2)
    home = use_of_home(biz.home_hours or 0, biz.home_months or 0, tax_year)
    miles = mileage(biz.car_miles or 0, biz.motorcycle_miles or 0, tax_year)
    ca, bc = float(biz.capital_allowances or 0), float(biz.balancing_charges or 0)
    warnings = []
    if allowances and allowances["lines"]:
        ca = allowances["total"]
        warnings.extend(allowances["issues"])
    if miles and by["TRAVEL"]["amount"] - by["TRAVEL"]["disallowed"] > 0:
        warnings.append("Mileage at the flat rate and car, van and travel costs are both claimed: the flat rate covers "
                        "the vehicle's running costs (only parking, tolls and other travel can go with it).")
    allowance = rates_for(tax_year)["trading_allowance"]
    if biz.use_trading_allowance:
        used = min(allowance, income)
        adjusted = round(income - used + bc, 2)
        allowance_used = used
    else:
        adjusted = round(accounts_profit + disallowed - home - miles - ca + bc, 2)
        allowance_used = 0.0
        if income and costs + home + miles + ca < allowance and income > 0:
            warnings.append(f"Costs are under £{allowance:,.0f}: the trading allowance would give a lower profit.")
    losses_bf = float(biz.losses_bf or 0)
    used_bf = min(losses_bf, max(adjusted, 0.0))
    taxable = round(max(adjusted - used_bf, 0.0), 2)
    loss_cf = round(losses_bf - used_bf + max(-adjusted, 0.0), 2)
    turnover = by["TURNOVER"]["amount"]
    return {
        "id": biz.id, "name": biz.name, "headings": by, "income": income, "costs": costs, "disallowed": disallowed,
        "accounts_profit": accounts_profit, "use_of_home": home, "mileage": miles, "capital_allowances": ca,
        "balancing_charges": bc, "trading_allowance": allowance_used, "adjusted_profit": adjusted,
        "losses_used": used_bf, "taxable_profit": taxable, "loss_cf": loss_cf, "cis_deducted": float(biz.cis_deducted or 0),
        "loss_year": round(max(-adjusted, 0.0), 2), "loss_current": 0.0, "loss_back": 0.0,
        "page": "SA103S" if turnover < rates_for(tax_year).get("short_page_limit", SHORT_PAGE_LIMIT) else "SA103F",
        "warnings": warnings,
        "allowances": (allowances or {}).get("lines", []),
    }


def cis_from_documents(db, job) -> Dict:
    """The CIS statements read for the year, added up (another person's left out)."""
    import json
    from backend.app.sa.models import SADocument
    out = {"count": 0, "gross": 0.0, "materials": 0.0, "deducted": 0.0}
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "CIS_STATEMENT",
                                         SADocument.status.in_(("READ", "CHECK"))).all():
        f = json.loads(d.fields) if d.fields else {}
        if f.get("other_person") or f.get("deducted") is None:
            continue
        out["count"] += 1
        for k in ("gross", "materials", "deducted"):
            out[k] = round(out[k] + float(f.get(k) or 0), 2)
    return out


def all_businesses(db, job) -> Dict:
    from backend.app.sa.models import SABusiness, SABusinessItem       # here: one() above needs no database
    bizs = db.query(SABusiness).filter(SABusiness.job_id == job.id).order_by(SABusiness.id).all()
    items = db.query(SABusinessItem).filter(SABusinessItem.job_id == job.id).order_by(SABusinessItem.id).all()
    from backend.app.sa.allowances import for_business
    from backend.app.sa.models import SAAllowance
    alls = db.query(SAAllowance).filter(SAAllowance.job_id == job.id).order_by(SAAllowance.id).all()
    rows = [one(b, [i for i in items if i.business_id == b.id], job.tax_year,
                for_business([a for a in alls if a.business_id == b.id], job.tax_year, bool(b.cash_basis))) for b in bizs]
    # CIS statements read (R-SA103-10): the deductions are tax paid; with one business and none entered by hand, they
    # are that business's. The turnover must be the gross on the statements, not the net paid into the bank
    cis = cis_from_documents(db, job)
    if cis["count"] and len(rows) == 1 and not rows[0]["cis_deducted"]:
        rows[0]["cis_deducted"] = cis["deducted"]
        rows[0]["warnings"].append(f"CIS: {cis['count']} statement(s), gross £{cis['gross']:,.2f}, materials "
                                   f"£{cis['materials']:,.2f}, deducted £{cis['deducted']:,.2f} (tax paid). Turnover "
                                   f"must be the gross, not the net paid into the bank (R-SA103-10).")
    return {"businesses": rows, "taxable_profit": round(sum(r["taxable_profit"] for r in rows), 2),
            "cis_deducted": round(sum(r["cis_deducted"] for r in rows), 2), "cis": cis,
            "loss_cf": round(sum(r["loss_cf"] for r in rows), 2), "loss_year": round(sum(r["loss_year"] for r in rows), 2)}
