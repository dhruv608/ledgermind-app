"""Pensions, State Pension, state benefits and pension contributions read (R-SAV-06, R-SAV-07, R-SP-02): a pension
provider's annual statement gives the pension paid and the tax taken off; a DWP letter gives the State Pension or a
taxable benefit (JSA, ESA, Carer's Allowance) for the tax year, at the DWP's figure; a pension contribution statement
gives what the person paid in. Only relief at source contributions go on the return (paid net: grossed up by the
engine); net pay and salary sacrifice have no entry. Code checks every reading:

  tax year    the figures are for the return's tax year; a weekly State Pension rate with no yearly figure is turned
              into a year (x 52) and left to check against the DWP's figure
  owner       the person is the one named, when a name is printed (R-IN-07)
  sense       amounts not negative; tax not more than the pension
  readers     a scan is read by two models; a total they do not agree on is a point to check"""

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.interest import _tax_year_of
from backend.app.sa.extract.p60 import owner

KINDS = ("STATE_PENSION", "PENSION", "BENEFIT", "CONTRIBUTION", "LUMP_SUM")
# Lump sums from a pension (PTM061200, PTM063000): a pension commencement lump sum is
# tax-free; an uncrystallised funds lump sum, a small pot or a trivial commutation is 25% tax-free and 75% taxable when
# nothing was taken before; drawdown income is all taxable. Taking an uncrystallised lump sum or drawdown income
# starts the money purchase annual allowance (£10,000); a small pot or a trivial commutation does not
LUMP_TYPES = ("PCLS", "UFPLS", "SMALL_POT", "TRIVIAL", "DRAWDOWN", "OTHER")
MPAA_TYPES = ("UFPLS", "DRAWDOWN")
EMERGENCY_RATE = 0.25        # tax over a quarter of the taxable part: likely an emergency code (Month 1)
WEEKS = 52
def annual_allowance(tax_year: str) -> float:
    """The pension annual allowance (P-PEN-01 in the rates table)."""
    from backend.app.sa.engine.calc import rates_for
    return float(rates_for(tax_year).get("pension_annual_allowance", 60000))

PROMPT = """This is a UK document about pensions or state benefits sent for a Self Assessment tax return: a pension
provider's annual statement or payment advice, a DWP letter (State Pension, Jobseeker's Allowance, Employment and Support
Allowance, Carer's Allowance, Bereavement), or a pension contribution statement.
Reply with one JSON object only:
{"person": "the person's full name as printed or null", "period_from": "YYYY-MM-DD or null", "period_to": "YYYY-MM-DD or null",
 "items": [{"kind": "STATE_PENSION" | "PENSION" (a private, workplace or annuity pension paid to the person) |
                    "BENEFIT" (JSA, ESA, Carer's Allowance, Bereavement or another taxable state benefit) |
                    "CONTRIBUTION" (money the person paid into a pension) |
                    "LUMP_SUM" (a lump sum or cash taken from a pension pot, or flexi-access drawdown paid out),
            "payer": "the provider, scheme or DWP",
            "name": "the pension's or benefit's name as printed",
            "year_amount": number or null (the amount paid in the period, or for the tax year, before tax),
            "weekly_amount": number or null (a weekly rate, when only that is given),
            "rate_from": "YYYY-MM-DD or null" (the date a weekly rate starts),
            "tax_deducted": number or 0,
            "contribution_basis": "RELIEF_AT_SOURCE" | "NET_PAY" | "SALARY_SACRIFICE" | null (for a CONTRIBUTION: how it
                                   is paid; relief at source when the provider claims basic-rate tax relief on it),
            "net_amount": number or null (for a CONTRIBUTION: what the person paid, before the provider's tax relief
                          is added), "gross_amount": number or null (for a CONTRIBUTION: with the tax relief added),
            "employer_amount": number or null (for a CONTRIBUTION: what the employer paid in, when shown),
            "lump_type": for a LUMP_SUM: "PCLS" (pension commencement lump sum, tax-free cash) | "UFPLS" (uncrystallised
                         funds pension lump sum) | "SMALL_POT" | "TRIVIAL" (trivial commutation) | "DRAWDOWN"
                         (flexi-access drawdown income) | "OTHER" | null,
            "paid_on": "YYYY-MM-DD or null" (for a LUMP_SUM: the payment date),
            "tax_free_amount": number or null, "taxable_amount": number or null (for a LUMP_SUM, as printed)}]}
Money as plain numbers with pence (no £ or commas). For a LUMP_SUM give year_amount as the whole payment before tax.
Leave out transfer values and fund values."""


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(str(v).replace(",", "").replace("£", "").strip()), 2)
    except ValueError:
        return None


def _lump_fields(x: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(x.get("lump_type") or "").upper()
    return {"lump_type": kind if kind in LUMP_TYPES else "OTHER", "paid_on": x.get("paid_on"),
            "tax_free": _num(x.get("tax_free_amount")), "taxable": _num(x.get("taxable_amount"))}


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    items = []
    for x in a.get("items") or []:
        kind = str(x.get("kind") or "").upper()
        if kind not in KINDS:
            continue
        year_amount = _num(x.get("year_amount"))
        if kind == "CONTRIBUTION":
            # A relief at source contribution is kept as paid (net): the engine grosses it up (net / 0.8)
            net, gross = _num(x.get("net_amount")), _num(x.get("gross_amount"))
            year_amount = net if net is not None else (round(gross * 0.8, 2) if gross is not None else year_amount)
        items.append({"kind": kind, "payer": str(x.get("payer") or "").strip(), "name": str(x.get("name") or "").strip(),
                      "year_amount": year_amount, "weekly_amount": _num(x.get("weekly_amount")),
                      "rate_from": x.get("rate_from"), "tax_deducted": _num(x.get("tax_deducted")) or 0.0,
                      "basis": str(x.get("contribution_basis") or "").upper() or None,
                      "employer": _num(x.get("employer_amount")) if kind == "CONTRIBUTION" else None,
                      **(_lump_fields(x) if kind == "LUMP_SUM" else {})})
    who = (a.get("person") or "").strip() or None
    who = None if who and "person's" in who.lower() else who      # the prompt's own words for a page with no name
    return {"person": who, "period_from": a.get("period_from"),
            "period_to": a.get("period_to"), "items": items}


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """(status, the reasons a person must look); each item gets the amount that goes on the return ('amount')."""
    if not f.get("items"):
        return "CHECK", ["No pension, benefit or contribution figure could be read: enter it by hand."]
    notes: List[str] = []
    years = {_tax_year_of(f.get("period_from")), _tax_year_of(f.get("period_to"))} - {None}
    if years and tax_year not in years:
        return "OTHER_YEAR", [f"This document is for {', '.join(sorted(years))}, not {tax_year}: not used."]
    # A DWP letter with no period printed is for the year its weekly rate starts in (taxable at the DWP's figure for the
    # tax year, R-SP-02): 'from 12 April 2025' is next year's letter, not this year's
    rate_years = {_tax_year_of(it.get("rate_from")) for it in f["items"] if it.get("weekly_amount") and it.get("rate_from")} - {None}
    if not years and rate_years and tax_year not in rate_years:
        return "OTHER_YEAR", [f"The weekly rate on this letter starts in {', '.join(sorted(rate_years))}, not {tax_year}: "
                              f"another year's letter, not used (R-SP-02)."]
    if person and f.get("person") and owner(f["person"], person) == "OTHER":
        f["other_person"] = True
        return "CHECK", [f"This is for {f['person']}, not {person}: not used. If it is theirs, confirm it."]
    for it in f["items"]:
        what = it["name"] or it["payer"] or it["kind"].replace("_", " ").lower()
        if it["kind"] == "LUMP_SUM":
            notes += _lump_sum(it, what)
            continue
        amount = it["year_amount"]
        if amount is None and it["weekly_amount"] is not None and it["kind"] in ("STATE_PENSION", "BENEFIT"):
            amount = round(it["weekly_amount"] * WEEKS, 2)
            notes.append(f"{what}: £{it['weekly_amount']:,.2f} a week, taken as £{amount:,.2f} for the year. Check it "
                         f"against the DWP's figure for {tax_year} (R-SP-02).")
        it["amount"] = amount
        if amount is None:
            notes.append(f"{what}: no figure for the year: enter it by hand.")
            continue
        if amount < 0:
            notes.append(f"{what}: the amount is negative.")
        if it["tax_deducted"] > amount + 0.005:
            notes.append(f"{what}: the tax taken off is more than the amount.")
        if it["kind"] == "CONTRIBUTION":
            if it["basis"] != "RELIEF_AT_SOURCE":
                notes.append(f"{what}: paid by net pay or salary sacrifice (or not said): no entry on the return unless "
                             f"it is relief at source (R-SAV-07).")
    # The annual allowance is tested on the total pension input: the person's contributions gross (relief at source
    # grossed up, net pay and salary sacrifice as paid) and the employer's
    mine_in = sum((it["amount"] / 0.8 if it["basis"] == "RELIEF_AT_SOURCE" else it["amount"])
                  for it in f["items"] if it["kind"] == "CONTRIBUTION" and it.get("amount"))
    employer_in = sum(it.get("employer") or 0 for it in f["items"] if it["kind"] == "CONTRIBUTION")
    limit = annual_allowance(tax_year)
    if mine_in + employer_in > limit:
        notes.append(f"Pension input £{mine_in + employer_in:,.2f} (the person's £{mine_in:,.2f} gross"
                     + (f", the employer's £{employer_in:,.2f}" if employer_in else "") + f") is over the £{limit:,.0f} "
                     f"annual allowance: check unused allowance from the last three years, the taper (threshold income "
                     f"over £200,000) and the money purchase allowance; an annual allowance charge may be due (C18, "
                     f"R-SAV-07).")
    if second is not None:
        s = clean(second)
        mine = round(sum(i.get("year_amount") or 0 for i in f["items"]), 2)
        theirs = round(sum(i.get("year_amount") or 0 for i in s["items"]), 2)
        if abs(mine - theirs) > 0.005:
            notes.append(f"The two readers disagree on the amounts (£{mine:,.2f} or £{theirs:,.2f}): look at the document.")
    return ("CHECK" if notes else "READ"), notes


def _lump_sum(it: Dict[str, Any], what: str) -> List[str]:
    """The taxable part of a pension lump sum ('amount': what goes on the return as pension income) and the points on
    it. Only the provider's own split is used: the 25% tax-free share depends on what was taken
    before, so it is not assumed."""
    notes: List[str] = []
    whole, free, taxable, kind = it["year_amount"], it.get("tax_free"), it.get("taxable"), it.get("lump_type") or "OTHER"
    label = {"PCLS": "tax-free lump sum", "UFPLS": "uncrystallised funds lump sum", "SMALL_POT": "small pot lump sum",
             "TRIVIAL": "trivial commutation lump sum", "DRAWDOWN": "drawdown payment"}.get(kind, "lump sum")
    of = f" of £{whole:,.2f}" if whole is not None else ""
    if kind == "PCLS":
        taxable = 0.0                      # tax-free cash: not income
    elif taxable is None and free is not None and whole is not None:
        taxable = round(whole - free, 2)
    elif taxable is None and kind == "DRAWDOWN" and whole is not None and not free:
        taxable = whole                    # drawdown income is all taxable
    it["amount"] = taxable
    if taxable is None:
        notes.append(f"{what}: {label}{of} with no tax-free and taxable split: ask the provider for the statement "
                     f"showing both parts (O13). Not on the return yet.")
        return notes
    if kind == "PCLS":
        notes.append(f"{what}: tax-free lump sum{of}: not income, left off the return (O14).")
        return notes
    if taxable < 0 or (whole is not None and taxable > whole + 0.005):
        notes.append(f"{what}: the taxable part £{taxable:,.2f} does not fit the payment{of}: look at the statement.")
    if taxable and it["tax_deducted"] > EMERGENCY_RATE * taxable:
        notes.append(f"{what}: tax of £{it['tax_deducted']:,.2f} on £{taxable:,.2f} looks like an emergency code. Has a "
                     f"refund been claimed on form P55, P53Z or P50Z? If so, do not claim it again here; if not, it comes "
                     f"back through this return (O15).")
    if kind in MPAA_TYPES:
        notes.append(f"{what}: taking a {label} starts the money purchase annual allowance: from now on at most £10,000 "
                     f"a year can be paid into money purchase pensions with tax relief (O16).")
    return notes


# A taxable state benefit paid into the bank: Carer's Allowance, contribution-based
# JSA and ESA, Bereavement Allowance. PIP, DLA, Attendance Allowance, Universal Credit and Child Benefit are not taxable
# and never match
BANK_BENEFITS = (
    ("Carer's Allowance", re.compile(r"\bDWP\b.{0,20}\bCA\b|carer'?s allowance", re.I)),
    ("Jobseeker's Allowance", re.compile(r"\bDWP\b.{0,20}\bJSA\b|jobseeker'?s allowance", re.I)),
    ("Employment and Support Allowance", re.compile(r"\bDWP\b.{0,20}\bESA\b|employment and support allowance", re.I)),
    ("Bereavement Allowance", re.compile(r"\bDWP\b.{0,20}\bBB\b|bereavement allowance", re.I)),
)


def bank_benefits(pages: List[Dict[str, Any]], start: str, end: str) -> Dict[str, float]:
    """The taxable benefits credited on a bank statement in the tax year, by benefit."""
    out: Dict[str, float] = {}
    for p in pages:
        for on, desc, money_in, _out, _bal in p.get("lines") or []:
            if not money_in or not on or not (start <= on <= end):
                continue
            name = next((n for n, rx in BANK_BENEFITS if rx.search(desc or "")), None)
            if name:
                out[name] = round(out.get(name, 0.0) + float(money_in), 2)
    return out


# A word of the payer's name: letters, or letters with digits ('G4S'), never a number alone ('2024')
WORD = re.compile(r"\b(?=[a-z0-9]*[a-z])[a-z0-9]{3,}\b")
COMMON = {"pension", "pensions", "scheme", "plan", "limited", "ltd", "the", "and", "trustees", "services", "management"}


def same_payer(a: str, b: str) -> bool:
    """'Acme UK Pension Plan' and 'Acme Uk plan' are one payer: a shared distinctive word ('G4S PENSION SCHEME'
    and 'G4S Pension Scheme (GSL)' too)."""
    wa, wb = set(WORD.findall((a or "").lower())) - COMMON, set(WORD.findall((b or "").lower())) - COMMON
    return bool(wa & wb)
