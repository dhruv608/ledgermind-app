"""The admin points of a return (R-ADM-01 to 03): collecting a small balance through the tax code, a person whose
income is all taxed at source (who may leave Self Assessment), and Making Tax Digital for Income Tax by qualifying
income (gross self-employment plus gross property income: P-MTD-01 £50,000 from April 2026, £30,000 from April 2027,
£20,000 from April 2028). Each is a point for the accountant, never a change to the figures."""

from typing import Dict, List

from backend.app.sa.engine.calc import rates_for


def qualifying_income(calc: Dict) -> float:
    trade = sum(b.get("income", 0.0) for b in calc["trade"]["businesses"])
    rents = sum(p.get("rents", 0.0) for p in calc["property"]["properties"]) + \
        sum(p.get("rents", 0.0) for p in calc["foreign_property"]["properties"])
    return round(trade + rents, 2)


# Documents that point to income not taxed at source, entered or not: no 'may leave Self Assessment' with these
UNTAXED_KINDS = {"LETTING_STATEMENT", "FOREIGN_TAX", "CIS_STATEMENT", "CLIENT_ACCOUNTS", "DIVIDEND_VOUCHER",
                 "MORTGAGE_INTEREST", "FOSTER_LETTER"}


def points(calc: Dict, tax_year: str, doc_kinds: set = frozenset()) -> List[Dict]:
    r = rates_for(tax_year)
    c, inc = calc["calculation"], calc["income"]
    out: List[Dict] = []
    # R-ADM-01 coding out: a balance under the limit, with PAYE income to collect it through
    paye = (inc.get("employment") or 0) + (inc.get("pensions") or 0)
    limit = r.get("coding_out_limit", 3000)
    if 0 < c["balance"] < limit and paye > 0:
        from backend.app.sa.pack import deadlines
        by = next(d for label, d in deadlines(tax_year) if label.startswith("Tax code"))
        out.append({"key": "coding_out", "text": f"The balance of £{c['balance']:,.2f} is under £{limit:,.0f}: it can be "
                    f"collected through next year's tax code if the return is filed online by {by:%d %B %Y}. Ask the client "
                    f"whether they want it coded out (R-ADM-01)."})
    # R-ADM-02 all income taxed at source: no trade, property, foreign income or gains
    untaxed = (inc.get("self_employment") or 0) + (inc.get("property") or 0) + (inc.get("foreign") or 0) + \
        (c.get("cgt") or 0) + (c.get("hicbc") or 0)
    if paye > 0 and not untaxed and c["balance"] <= 0 and not (set(doc_kinds) & UNTAXED_KINDS):
        out.append({"key": "leave_sa", "text": "All the income is taxed at source and nothing is owed: if the client "
                    "asks, they may be able to leave Self Assessment. Check there are no gains, rents or foreign income "
                    "to come, then tell HMRC after filing (R-ADM-02)."})
    # R-ADM-03 MTD: qualifying income over a threshold
    q = qualifying_income(calc)
    start = int(tax_year[:4])
    for threshold, begins in r.get("mtd", []):
        # This year's income decides the start two Aprils later (2025-26 over £30,000: from April 2027)
        if int(begins[:4]) == start + 2 and q > threshold:
            out.append({"key": "mtd", "text": f"Qualifying income (self-employment and property, before costs) is "
                        f"£{q:,.0f}, over £{threshold:,.0f}: Making Tax Digital for Income Tax applies from {begins[8:]} "
                        f"April {begins[:4]}. Check the client is signed up with compatible software (R-ADM-03)."})
    if q > 50000:
        out.append({"key": "mtd_now", "text": f"Qualifying income of £{q:,.0f} is over £50,000: if last year's was too, "
                    f"the client is already in Making Tax Digital from 6 April 2026. Check the sign-up and that the "
                    f"quarterly updates already due have been sent (R-ADM-03)."})
    return out
