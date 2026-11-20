"""A P45 or a final payslip read (R-SA102-01, -06, -07): only the pay and tax in this employment (a P45's 'this
employment' boxes, else its totals to date with no previous employment; a payslip's taxable pay and tax to date), never
payment or deduction totals. A termination payment is split (ITEPA s401-403, EIM12975): non-contractual compensation up
to £30,000 is exempt, over it an accountant's decision; PILON and holiday pay are taxable pay. Benefits taxed through the
payroll are noted so they are not added again from a P11D. The P60 checks then run on it (tax year, owner, sense).

A P45 or final payslip goes on the return only when no P60 from the same employer does (a P60 covers the whole year)."""

from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract import p60
from backend.app.sa.extract.interest import _tax_year_of

def exempt_limit(tax_year: str) -> float:
    """The termination payment exemption (ITEPA s403; P-TERM-01 in the rates table)."""
    from backend.app.sa.engine.calc import rates_for
    return float(rates_for(tax_year).get("termination_exempt", 30000))

PROMPT = """This is a UK P45 (an employee leaving) or a payslip, sent for a Self Assessment tax return.
Reply with one JSON object only (null when not shown; money as a number with pence, no £ or commas):
{"kind": "P45" or "PAYSLIP", "final": true or false (a payslip that is the last one from this employer, or shows a
 leaving date), "employee": "full name as printed", "ni_number": "...", "employer": "...",
 "paye_ref": "employer PAYE reference like 120/AB12345", "leaving_date": "YYYY-MM-DD or null",
 "pay_date": "YYYY-MM-DD (a payslip's date) or null", "tax_code": "...",
 "pay_this": number (P45: 'pay in this employment'; payslip: leave null and use the two pairs below),
 "tax_this": number (P45: 'tax in this employment'; payslip: leave null),
 "taxable_pay_to_date": number (payslip: Taxable Pay in the TO DATE / year-to-date column), "tax_to_date": number
 (payslip: Income Tax in the TO DATE column), "taxable_pay_period": number (payslip: Taxable Pay THIS PERIOD),
 "tax_period": number (payslip: Income Tax THIS PERIOD),
 "pay_total": number (P45 'total pay to date'), "tax_total": number (P45 'total tax to date'),
 "pay_previous": number or null, "tax_previous": number or null,
 "compensation": number or null (compensation for loss of office, redundancy or an ex gratia payment on leaving),
 "pilon": number or null (pay in lieu of notice), "holiday_pay": number or null (holiday pay on leaving),
 "payrolled_benefits": ["each benefit taxed through the payroll (shown with *, or 'BIK') as printed"]}"""


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    f = p60.clean(a)
    for k in ("compensation", "pilon", "holiday_pay"):
        f[k] = p60._num(a.get(k)) if a.get(k) is not None else None
    f["kind"] = "PAYSLIP" if str(a.get("kind") or "").upper() == "PAYSLIP" else "P45"
    # A payslip: the year to date, never this period (R-SA102-01): asked as two pairs so the right one is taken
    if f["kind"] == "PAYSLIP" and p60._num(a.get("taxable_pay_to_date")) is not None:
        f["pay_this"] = p60._num(a.get("taxable_pay_to_date"))
        f["tax_this"] = p60._num(a.get("tax_to_date")) or 0.0
        f["pay_period"] = p60._num(a.get("taxable_pay_period"))
    f["final"] = bool(a.get("final")) or f["kind"] == "P45"
    f["leaving_date"], f["pay_date"] = a.get("leaving_date"), a.get("pay_date")
    f["payrolled_benefits"] = [b for b in (a.get("payrolled_benefits") or []) if b]
    # A P45's totals to date are this employment's when no previous employment is shown
    if f["pay_this"] is None and f["pay_total"] is not None and not f.get("pay_previous"):
        f["pay_this"], f["tax_this"] = f["pay_total"], f["tax_total"]
    f["tax_year"] = _tax_year_of(f["leaving_date"] or f["pay_date"]) or f.get("tax_year")
    # The tax year's last payslip (month 12, paid 6 March to 5 April, its pay to date twelve months of pay; or a
    # weekly / four-weekly one paid from 29 March): its year to date is the year's pay in this employment (R-SA102-01)
    end = str(f.get("tax_year") or "")[:4]
    paid = str(f.get("pay_date") or "")
    if f["kind"] == "PAYSLIP" and not f["final"] and end.isdigit() and f.get("pay_this"):
        y = int(end) + 1
        month_12 = (f"{y}-03-06" <= paid <= f"{y}-04-05" and f.get("pay_period")
                    and 11.5 * f["pay_period"] <= f["pay_this"] <= 12.5 * f["pay_period"])
        if month_12 or f"{y}-03-29" <= paid <= f"{y}-04-05":
            f["final"], f["year_end"] = True, True
    return f


def checks(f: Dict[str, Any], tax_year: str, ni_number: Optional[str], person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    # The second reading tidied the same way (a payslip's year to date), so the two are compared like for like
    status, notes = p60.checks(f, tax_year, ni_number, clean(second) if second is not None else None, person)
    if status in ("OTHER_YEAR",) or f.get("other_person"):
        return status, notes
    notes = [n.replace("P60", f["kind"].replace("PAYSLIP", "payslip")) for n in notes]
    if f["kind"] == "PAYSLIP" and not f["final"]:
        notes.append("Not the final payslip from this employer: the pay to date may not be the whole year's. Ask for "
                     "the P45 or the last payslip (R-SA102-01).")
    comp = f.get("compensation") or 0.0
    EXEMPT_LIMIT = exempt_limit(tax_year)
    if comp:
        if comp > EXEMPT_LIMIT:
            notes.append(f"Compensation on leaving of £{comp:,.2f}: £{EXEMPT_LIMIT:,.0f} is exempt, the £{comp - EXEMPT_LIMIT:,.2f} "
                         f"over it is taxable (SA101 Ai3). Accountant decision: is all of it non-contractual (R-SA102-06)?")
        else:
            f["exempt_compensation"] = comp
            notes.append(f"Compensation on leaving of £{comp:,.2f}: exempt (under £{EXEMPT_LIMIT:,.0f}, ITEPA s403), not "
                         f"in taxable pay. Confirm it is non-contractual (R-SA102-06).")
    if comp:
        # The £30,000 covers the s401 part only: post-employment notice pay comes off first and is taxed in full, and
        # statutory redundancy and benefits kept after leaving count towards the £30,000 (ITEPA s402A-E,
        # s403)
        notes.append("Ask for the settlement agreement: notice pay for any notice not worked (post-employment notice "
                     "pay) is taxable in full and is not covered by the £30,000; statutory redundancy and benefits "
                     "continued after leaving count towards the £30,000 (ITEPA s402A-E, C14).")
    if f.get("pilon") or f.get("holiday_pay"):
        notes.append("Pay in lieu of notice and holiday pay are taxable pay: check they are in the taxable pay to date "
                     "(R-SA102-06).")
    if f.get("payrolled_benefits"):
        notes.append(f"Benefits taxed through the payroll ({', '.join(f['payrolled_benefits'])}): already in pay; not "
                     f"added again from a P11D (R-SA102-07).")
    return ("CHECK" if notes else "READ"), notes
