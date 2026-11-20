"""Savings interest read (R-SAV-01 to 03, R-SAV-05): an annual interest statement, certificate of interest, ISA
or NS&I statement gives each account's interest for the tax year; a savings account's bank statement gives the interest
credited to it. Each account is tagged ISA (left out of the figures) or not, and sole or joint (half each unless the
statement says otherwise); the tax-year figure is taken from the provider (R-SAV-02). Code checks every reading:

  tax year    the statement's period is the tax year (6 April to 5 April); else a point to check
  owner       the person is one of the holders, when holders are printed (R-IN-07)
  sense       interest not negative; tax deducted not more than the interest
  readers     a scan is read by two models; a figure they do not agree on is a point to check"""

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.sa.extract.p60 import owner

PROMPT = """This is a UK savings document sent for a Self Assessment tax return: an annual interest statement, a
certificate of interest, an ISA statement, an NS&I statement or a savings account statement.
Read every account on it. Reply with one JSON object only:
{"provider": "bank or building society name", "period_from": "YYYY-MM-DD or null", "period_to": "YYYY-MM-DD or null",
 "holders": ["each account holder's full name as printed"],
 "accounts": [{"account_last4": "last 4 digits or null", "account_name": "the account's name as printed",
               "isa": true or false (an ISA, cash ISA, stocks and shares ISA, LISA or Junior ISA),
               "joint": true or false (more than one holder on this account),
               "interest_gross": number (the interest paid or credited in the period, before any tax),
               "tax_deducted": number or 0,
               "paid_on": "YYYY-MM-DD: the date the interest was paid or credited, when one date is printed, else null"}],
 "dividends": [{"payer": "the line's name as printed", "amount": number (gross), "overseas": true or false}]}
Money as plain numbers with pence (no £ or commas). Use the interest for the period printed, not a balance and not a
rate. Leave out an account with no interest. When the file has a month's statement and also a summary of the gross
interest for the whole tax year (6 April to 5 April), give the tax year's figure and dates. A client's own list (a
spreadsheet, one row per account, cells split by |, a bank's name sometimes on the row above its account): every row
with an interest figure is an account; leave out dividends, shares and any total row. A broker's or platform's
consolidated tax certificate (an income schedule of interest and dividends): each interest line with a figure is an
account (its name as the line, for example UK deposit interest), and each dividend line with a figure goes in
dividends; lines shown as - are left out. Any other document: dividends is []."""

ISA_WORDS = re.compile(r"\bISA\b|\bLISA\b|individual savings account", re.I)
JOINT_WORDS = re.compile(r"\bjoint\b|\bjnt\b", re.I)
# A broker certificate's line given as a dividend that is not one: a fund's interest distribution, a loyalty bonus
NOT_DIVIDEND = re.compile(r"\binterest\b|loyalty bonus", re.I)
# A credit that is interest paid on the account (not an overdraft or loan interest charge, not a refund of interest)
INTEREST_IN = re.compile(r"\binterest\b(?!.{0,20}\b(charge|charged|refund)\b)|\bgross int\b|\bint paid\b|\bint pd\b", re.I)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(str(v).replace(",", "").replace("£", "").strip()), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    accounts = []
    for x in a.get("accounts") or []:
        gross = _num(x.get("interest_gross"))
        if gross is None:
            continue
        name = str(x.get("account_name") or "").strip()
        accounts.append({"account_last4": (str(x.get("account_last4") or "").strip()[-4:] or None), "account_name": name,
                         "isa": bool(x.get("isa")) or bool(ISA_WORDS.search(name)), "joint": bool(x.get("joint")),
                         "interest_gross": gross, "tax_deducted": _num(x.get("tax_deducted")) or 0.0,
                         "paid_on": x.get("paid_on") if re.fullmatch(r"20\d\d-\d\d-\d\d", str(x.get("paid_on") or "")) else None})
    dividends = []
    for x in a.get("dividends") or []:
        name, amount = str(x.get("payer") or "Dividends").strip(), _num(x.get("amount"))
        if not amount:
            continue
        # A fund's interest distribution is savings interest, not a dividend (ITTOIA s376), and a platform's loyalty
        # bonus is taxed as interest is: both go with the accounts (a broker's certificate lists them beside dividends)
        if NOT_DIVIDEND.search(name):
            accounts.append({"account_last4": None, "account_name": name, "isa": False, "joint": False,
                             "interest_gross": amount, "tax_deducted": 0.0, "paid_on": None})
            continue
        dividends.append({"company": name, "amount": amount, "overseas": bool(x.get("overseas"))})
    return {"provider": (a.get("provider") or "").strip() or None, "period_from": a.get("period_from"),
            "period_to": a.get("period_to"), "holders": [h for h in (a.get("holders") or []) if h], "accounts": accounts,
            "dividends": dividends}


def _tax_year_of(day: Optional[str]) -> Optional[str]:
    m = re.match(r"(20\d\d)-(\d\d)-(\d\d)", day or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    start = y if (mo, d) >= (4, 6) else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """(status, the reasons a person must look) for a read savings document."""
    if not f.get("accounts"):
        return "CHECK", ["No account's interest could be read: enter it by hand."]
    notes: List[str] = []
    years = {_tax_year_of(f.get("period_from")), _tax_year_of(f.get("period_to"))} - {None}
    if years and years != {tax_year}:
        if tax_year not in years:
            return "OTHER_YEAR", [f"This statement is for {', '.join(sorted(years))}, not {tax_year}: not used."]
        if all(a.get("paid_on") for a in f["accounts"]):
            # Interest is taxed when it is credited (R-SAV-02): with each payment's date printed, the interest paid in
            # the tax year is this year's and the rest is another year's, so the statement needs no one to split it
            outside = [a for a in f["accounts"] if _tax_year_of(a["paid_on"]) != tax_year]
            f["accounts"] = [a for a in f["accounts"] if a not in outside]
            if outside:
                f["not_this_year"] = outside
            if not f["accounts"]:
                return "OTHER_YEAR", [f"The interest on this statement was paid on {', '.join(a['paid_on'] for a in outside)}: "
                                      f"not in {tax_year}, so not used (R-SAV-02)."]
        else:
            notes.append(f"The statement runs {f.get('period_from')} to {f.get('period_to')}, not 6 April to 5 April: "
                         f"take the interest for {tax_year} only (R-SAV-02).")
    if person and f.get("holders") and all(owner(h, person) == "OTHER" for h in f["holders"]):
        f["other_person"] = True
        return "CHECK", [f"The account holder is {', '.join(f['holders'])}, not {person}: not used. If it is theirs, confirm it."]
    for a in f["accounts"]:
        if a["interest_gross"] < 0:
            notes.append(f"{a['account_name'] or 'An account'}: the interest is negative.")
        if a["tax_deducted"] > a["interest_gross"] + 0.005:
            notes.append(f"{a['account_name'] or 'An account'}: the tax deducted is more than the interest.")
    read = round(sum(a["interest_gross"] for a in f["accounts"]), 2)
    if f.get("printed_total") and read < f["printed_total"] - 1:
        notes.append(f"The list's total is £{f['printed_total']:,.2f} but the accounts read add to £{read:,.2f} "
                     f"(£{f['printed_total'] - read:,.2f} less): an account missed, or dividends in the total? Check the list.")
    if second is not None:
        s = clean(second)
        if years and years != {tax_year} and s["accounts"] and all(a.get("paid_on") for a in s["accounts"]):
            s["accounts"] = [a for a in s["accounts"] if _tax_year_of(a["paid_on"]) == tax_year]
        mine, theirs = round(sum(a["interest_gross"] for a in f["accounts"]), 2), round(sum(a["interest_gross"] for a in s["accounts"]), 2)
        if abs(mine - theirs) > 0.005:
            notes.append(f"The two readers disagree on the interest (£{mine:,.2f} or £{theirs:,.2f}): look at the statement.")
    return ("CHECK" if notes else "READ"), notes


def whole_year(f: Dict[str, Any], start: str, end: str) -> bool:
    """The statement covers the whole tax year (a certificate of interest to 5 April, an annual statement), within a
    week either side of 6 April and 5 April; a certificate printing only its end ('year to 5 April 2025') counts."""
    from datetime import date, timedelta
    week = timedelta(days=7)
    try:
        b = date.fromisoformat(str(f.get("period_to"))[:10])
        a = date.fromisoformat(str(f["period_from"])[:10]) if f.get("period_from") else None
    except ValueError:
        return False
    return abs(b - date.fromisoformat(end)) <= week and (a is None or abs(a - date.fromisoformat(start)) <= week)


def from_statement(pages: List[Dict[str, Any]], start: str, end: str) -> Tuple[float, int]:
    """The interest credited on a savings account's bank statement in the tax year: (total, lines)."""
    total, n = 0.0, 0
    for p in pages:
        for on, desc, money_in, _out, _bal in p.get("lines") or []:
            if money_in and on and start <= on <= end and INTEREST_IN.search(desc or ""):
                total, n = round(total + float(money_in), 2), n + 1
    return total, n


# A tax-year summary in the file's own text: 'gross interest earned on your account for the tax year 6 Apr 2024 to
# 5 Apr 2025 ... Gross interest earned £2,211.26' (Barclays prints it on page 2 of a month's statement)
# (the end year can be split from it by the page's columns: '6 Apr 2024 to 5 / Gross interest earned / Apr 2025')
YEAR_SUMMARY = re.compile(r"tax year\s+6\s+apr(?:il)?\s+(20\d\d)\s+to\s+5\b", re.I)
YEAR_GROSS = re.compile(r"gross interest earned\s*£\s*([\d,]+\.\d\d)", re.I)
# A broker's consolidated tax certificate, as it certifies itself ('We hereby certify that the dividends or interest
# summarised below ... were received by us'; its heading may be in a font with no readable text)
CERTIFY = re.compile(r"hereby certify that the dividends or interest", re.I)
# A spreadsheet's total row, as the sheet text prints it ('total | 3617.9')
TOTAL_ROW = re.compile(r"^\s*total\b[^\n\d]*?([\d,]+(?:\.\d{1,2})?)\s*$", re.I | re.M)


def with_text(f: Dict[str, Any], text: str) -> Dict[str, Any]:
    """One account read from a file that also prints the tax year's interest summary: the summary's figure and the tax
    year's dates (R-SAV-02: the provider's tax-year figure), not the month's. A client's list with a total row keeps the
    total, so the accounts read can be checked against it."""
    totals = TOTAL_ROW.findall(text or "")
    if totals and _num(totals[-1]):
        f = dict(f, printed_total=_num(totals[-1]))
    years, gross = YEAR_SUMMARY.findall(text or ""), YEAR_GROSS.findall(text or "")
    if len(f.get("accounts") or []) != 1 or len(set(years)) != 1 or len(set(gross)) != 1:
        return f
    y0, amount = years[0], _num(gross[0])
    y1 = int(y0) + 1
    if amount is None:
        return f
    a = dict(f["accounts"][0], interest_gross=amount, paid_on=None)
    return dict(f, accounts=[a], period_from=f"{y0}-04-06", period_to=f"{y1}-04-05")


def certificate_text(pages: List[str]) -> Optional[str]:
    """The pages of a long tax report that are its consolidated tax certificate (the income schedule a broker certifies
    to HMRC), found by the certificate's own words; None when there is none. The report's first pages (contents,
    transactions) are not read in its place."""
    found = [i for i, t in enumerate(pages) if CERTIFY.search(t or "")]
    if not found:
        return None
    return "\n".join(pages[i] for i in range(found[0], min(found[0] + 2, len(pages))))[:16000]
