"""A P60 read (R-SA102-01): only 'pay in this employment' and 'tax deducted' in this employment go to the
return, never other totals; the PAYE reference, final tax code, student and postgraduate loan deductions are kept
for the checks. Payroll software P60s with a text layer are read by code; a scan, a photo, or an HMRC eP60 printout
whose numbers come out of order is read by two AI models (vision.py).

Code checks every P60 however it was read:
  tax year    the return's year, else OTHER_YEAR (R-IN-05)
  owner       the NI number on the P60 is the person's, when both are known (R-IN-07)
  sums        previous + this employment = total for the year (when all three are shown)
  sense       pay not negative; tax not more than half the pay; a PAYE reference like '120/BE47415'
  readers     the two models agree on pay and tax (a scan); else a person checks"""

import re
from typing import Any, Dict, List, Optional, Tuple

MONEY = r"£?\s*(-?[\d,]+\.\d{2})"
FIELDS = ("tax_year", "employer", "paye_ref", "pay_this", "tax_this", "pay_previous", "tax_previous", "pay_total",
          "tax_total", "tax_code", "student_loan", "postgraduate_loan", "ni_number", "employee", "ni_letter",
          "earnings_at_lel")

PROMPT = """You are reading a document sent for a UK Self Assessment tax return.
Say what it is, as "kind", one of: P60, P45, PAYSLIP, P11D, BANK_STATEMENT, MORTGAGE_INTEREST, LETTING_STATEMENT,
INTEREST_STATEMENT, DIVIDEND_VOUCHER, PENSION_STATEMENT, DWP_LETTER (State Pension or a state benefit), CIS_STATEMENT, FOSTER_LETTER, FOREIGN_TAX (a
foreign country's tax assessment or return), TAX_CODE_NOTICE,
TAX_CALCULATION (an SA302 or tax calculation), HMRC_STATEMENT (HMRC's Self Assessment statement, SA300: payments due
and made), VAT_RETURN (a VAT return or its VAT 100 boxes), DONATIONS (a charity's receipt or a list of donations),
INVOICE, OTHER.
If it is a P60 (End of Year Certificate), also read exactly what is printed (null when not shown; money as a number
with its pence, no £ or commas):
  year_to: the year printed after "Tax year to 5 April" (a number: "Tax year to 5 April 2025" is 2025)
  tax_year: the tax year as printed, when it is printed as a range ("2024-25"), else null
  employee: the employee's full name as printed (forenames then surname)
  employer, paye_ref (the employer PAYE reference as printed: three digits, a slash, then letters and digits), ni_number,
  (only what this page prints: a page that is not a P60 gives null for all of these, never a made-up example)
  pay_this, tax_this: Pay and Tax deducted "In this employment" (the pay for tax: where a "Gross Pay" before
    pension is printed beside it, the "Pay" figure),
  pay_previous, tax_previous: "In previous employment(s)",
  pay_total, tax_total: "Total for year",
  tax_code: final tax code, student_loan, postgraduate_loan: the deductions shown,
  ni_letter: the National Insurance category letter, earnings_at_lel: "Earnings at the LEL" in the NI table.
Reply with one JSON object only, for example {"kind": "INVOICE"} or {"kind": "P60", "year_to": ..., ...}."""


def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").replace("£", "").strip())
    except ValueError:
        return None


def from_text(text: str) -> Optional[Dict[str, Any]]:
    """A payroll-software P60 with a text layer in its usual order; None when the layout is not that."""
    t = re.sub(r"\s+", " ", text or "")
    this = re.search(r"In this employment\s*" + MONEY + r"\s*" + MONEY, t, re.I)
    if not this:
        return None
    prev = re.search(r"In previous employment\(?s?\)?\s*" + MONEY + r"\s*" + MONEY, t, re.I)
    total = re.search(r"Total for (the )?year\s*" + MONEY + r"\s*" + MONEY, t, re.I)
    code = re.search(r"Final tax code\s*([0-9]{0,5}[A-Z]{1,2}[0-9]{0,4}|BR|D0|D1|NT|0T)\b", t, re.I)
    ref = re.search(r"PAYE reference\s*(\d{3}\s*/\s*[A-Z0-9]+)", t, re.I)
    employer = re.search(r"EMPLOYER DETAILS\s*Name\s*(.+?)\s*PAYE reference", t, re.I)
    year = re.search(r"(?:Certificate|tax year)\s*(20\d\d)\s*[/-]\s*(\d\d)", t, re.I)
    ni = re.search(r"National Insurance number\s*([A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D])", t, re.I)
    who = re.search(r"Surname\s*(.+?)\s*Forename\(?s?\)?\s*(.+?)\s*(?:Works|National Insurance|Payroll|Address)", t, re.I)
    sl = re.search(r"Student Loan deductions\s*" + MONEY, t, re.I)
    pgl = re.search(r"Postgraduate Loan deductions\s*" + MONEY, t, re.I)
    return {
        "tax_year": f"{year.group(1)}-{year.group(2)}" if year else None,
        "employer": employer.group(1).strip() if employer else None,
        "paye_ref": re.sub(r"\s", "", ref.group(1)) if ref else None,
        "ni_number": re.sub(r"\s", "", ni.group(1)).upper() if ni else None,
        "employee": f"{who.group(2).strip()} {who.group(1).strip()}" if who else None,
        "pay_this": _num(this.group(1)), "tax_this": _num(this.group(2)),
        "pay_previous": _num(prev.group(1)) if prev else None, "tax_previous": _num(prev.group(2)) if prev else None,
        "pay_total": _num(total.group(2)) if total else None, "tax_total": _num(total.group(3)) if total else None,
        "tax_code": code.group(1).upper() if code else None,
        "student_loan": _num(sl.group(1)) if sl else None, "postgraduate_loan": _num(pgl.group(1)) if pgl else None,
    }


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """An AI answer as P60 fields (numbers as numbers)."""
    a = answer or {}
    out = {k: a.get(k) for k in FIELDS}
    # The tax year from the year printed after 'Tax year to 5 April', worked out here: a model asked for the tax year
    # can turn 'year to 5 April 2025' into 2025-26
    try:
        year_to = int(str(a.get("year_to") or "").strip()[:4])
    except ValueError:
        year_to = None
    if year_to and 2000 < year_to < 2100:
        out["tax_year"] = f"{year_to - 1}-{str(year_to)[2:]}"
    for k in ("pay_this", "tax_this", "pay_previous", "tax_previous", "pay_total", "tax_total", "student_loan",
              "postgraduate_loan", "earnings_at_lel"):
        out[k] = _num(out[k]) if out[k] is not None else None
    if out["paye_ref"]:
        ref = re.sub(r"\s", "", str(out["paye_ref"])).upper()
        # The office number is always 3 digits: '120AB12345' read without its slash is '120/AB12345'
        out["paye_ref"] = f"{ref[:3]}/{ref[3:]}" if re.fullmatch(r"\d{3}[A-Z][A-Z0-9]*", ref) else ref
    if out["ni_number"]:
        out["ni_number"] = re.sub(r"\s", "", str(out["ni_number"])).upper()
    # A P60 with one employment shows its pay only as the total: that is this employment's pay
    if out["pay_this"] is None and out["pay_total"] is not None and not out["pay_previous"]:
        out["pay_this"], out["tax_this"] = out["pay_total"], out["tax_total"]
    # A P60 printing 'Gross Pay' before the pension (superannuation) and then 'Pay' for tax (as civil service P60s
    # do): with no previous employment, the year's total is this job's taxable pay, which is what the return takes
    # (SA102 box 1)
    if (None not in (out["pay_this"], out["pay_total"]) and not out["pay_previous"] and out["pay_this"] > out["pay_total"] + 0.01
            and out["tax_this"] is not None and out["tax_total"] is not None and abs(out["tax_this"] - out["tax_total"]) <= 0.01):
        out["gross_before_pension"], out["pay_this"] = out["pay_this"], out["pay_total"]
    return out


YEAR_TO = re.compile(r"year\s+to\s+5\s*(?:th)?\s+april\s*(20\d\d)", re.I)
YEAR_RANGE = re.compile(r"(?:certificate|tax year)\s*(20\d\d)\s*[/-]\s*(\d\d)\b", re.I)


def printed_year(text: Optional[str]) -> Optional[str]:
    """The tax year a P60's own text layer prints ('Tax year to 5 April 2025' is 2024-25), when it prints one year
    only; None otherwise. A model reading the picture may give 2025-26 for that P60, so the printed year wins."""
    t = text or ""
    years = {f"{int(y) - 1}-{y[2:]}" for y in YEAR_TO.findall(t)}
    years |= {f"{a}-{b}" for a, b in YEAR_RANGE.findall(t) if int(b) == (int(a) + 1) % 100}
    return years.pop() if len(years) == 1 else None


# A P60 from a pension scheme, annuity provider or scheme trustees: pension income, not an employment (pension P60s
# belong to Pensions, SA100 box 11). Also an 'employee benefits scheme' and the firms that only pay pensions and
# annuities; insurers that are also big employers (Aviva, Prudential, Legal & General) are left to the words above.
PENSION_PAYER = re.compile(
    r"\bpensions?\b|annuit|superannuation|\bretirement\b|\btrustees?\b|\bbenefits? scheme\b"
    r"|\bstandard life\b|\bscottish widows\b|\broyal london\b|\bphoenix life\b|\bcanada life\b|\brothesay\b"
    r"|\bscottish equitable\b|\bjust group\b", re.I)


def is_pension(payer: Optional[str]) -> bool:
    return bool(PENSION_PAYER.search(payer or ""))


NAME_WORDS = re.compile(r"[a-z]+")
TITLES = {"mr", "mrs", "ms", "miss", "dr", "e2e"}


def _names(name: str) -> List[str]:
    """The name's words, titles left out; initials kept ('Mr P N Smith' is p, n, smith). Surname first with a
    comma ('Smith, Philip', as tax offices print it) is turned round."""
    s = (name or "").lower()
    if s.count(",") == 1:
        last, first = s.split(",")
        s = f"{first} {last}"
    return [w for w in NAME_WORDS.findall(s) if w not in TITLES]


# The usual short forms of a forename ('Andy Smith' on an agent's statement is Andrew): each short form to its full names
SHORT_FORMS = {
    "andy": {"andrew"}, "drew": {"andrew"}, "tony": {"anthony", "antony"}, "bob": {"robert"}, "rob": {"robert"},
    "robbie": {"robert"}, "bill": {"william"}, "will": {"william"}, "billy": {"william"}, "liam": {"william"},
    "jim": {"james"}, "jimmy": {"james"}, "jamie": {"james"}, "mike": {"michael"}, "mick": {"michael"},
    "dave": {"david"}, "steve": {"stephen", "steven"}, "chris": {"christopher", "christine", "christina"},
    "nick": {"nicholas"}, "matt": {"matthew"}, "tom": {"thomas"}, "tommy": {"thomas"}, "dan": {"daniel"},
    "danny": {"daniel"}, "joe": {"joseph"}, "pete": {"peter"}, "phil": {"philip", "phillip"}, "rich": {"richard"},
    "rick": {"richard"}, "dick": {"richard"}, "ben": {"benjamin"}, "sam": {"samuel", "samantha"}, "alex": {"alexander", "alexandra"},
    "ed": {"edward"}, "eddie": {"edward"}, "ted": {"edward"}, "greg": {"gregory"}, "ken": {"kenneth"}, "len": {"leonard"},
    "ron": {"ronald"}, "don": {"donald"}, "fred": {"frederick"}, "harry": {"henry", "harold"}, "jack": {"john"},
    "johnny": {"john"}, "jon": {"jonathan"}, "charlie": {"charles"}, "gerry": {"gerald", "gerard"}, "tim": {"timothy"},
    "kate": {"katherine", "catherine", "kathryn"}, "kath": {"katherine", "kathryn"}, "cathy": {"catherine"},
    "liz": {"elizabeth"}, "beth": {"elizabeth"}, "lizzie": {"elizabeth"}, "sue": {"susan", "suzanne"},
    "jen": {"jennifer"}, "jenny": {"jennifer"}, "maggie": {"margaret"}, "meg": {"margaret"}, "peggy": {"margaret"},
    "pat": {"patrick", "patricia"}, "vicky": {"victoria"}, "debbie": {"deborah"}, "becky": {"rebecca"},
    "dee": {"delicia", "deirdre", "denise", "deborah", "diane", "dionne"}, "deb": {"deborah"},
    "mandy": {"amanda"}, "jo": {"joanne", "joanna", "josephine"}, "di": {"diane", "diana"}, "barney": {"barnaby"},
}


def _same_forename(g: str, m: str) -> bool:
    """The same forename, a short form of it, a spelling with a letter doubled ('Karren' for Karen, 'Phillip' for
    Philip: 'Sean' and 'Sian' stay apart), or the Gujarati honorific added ('Amitbhai' for Amit, 'Hetalben' for Hetal)."""
    if g == m or m in SHORT_FORMS.get(g, ()) or g in SHORT_FORMS.get(m, ()):
        return True
    single = lambda w: re.sub(r"(.)\1", r"\1", w)
    if len(g) >= 4 and len(m) >= 4 and single(g) == single(m):
        return True
    return any(len(a) >= 3 and b in (a + "bhai", a + "ben", a + "behn") for a, b in ((g, m), (m, g)))


def _forename_match(got: List[str], mine: List[str]) -> bool:
    """A forename in common, an initial counting for any forename it begins ('P' is Paul), a short form for its full
    name ('Andy' is Andrew). Initials run together ('CJ Smith') are each an initial."""
    split = lambda ws: [c for w in ws for c in (list(w) if 2 <= len(w) <= 3 and not set(w) & set("aeiouy") else [w])]
    got, mine = split(got), split(mine)
    return any(_same_forename(g, m) or (len(g) == 1 and m.startswith(g)) or (len(m) == 1 and g.startswith(m))
               for g in got for m in mine)


def _ni(v: Optional[str]) -> Optional[str]:
    """An NI number as letters and digits only ('QQ 12 34 56 C' is 'QQ123456C'); None when it is not a whole one (a
    masked copy, a blank)."""
    s = re.sub(r"[^A-Z0-9]", "", (v or "").upper())
    return s if re.fullmatch(r"[A-Z]{2}\d{6}[A-D]", s) else None


def owner(employee: Optional[str], person: Optional[str]) -> Optional[str]:
    """Whose P60 it is against the person on the return (R-IN-07): None when it is theirs (or no name is printed),
    'OTHER' when no forename matches (a spouse's P60 in the same folder), 'NAME' when a forename matches but the
    surname does not (a maiden name, a typing slip: counted, but to check)."""
    got, mine = _names(employee or ""), _names(person or "")
    if not got or not mine:
        return None
    # A bank's way, surname first then initials with no comma ('SMITH JE' for Jane E Smith): turned round
    if len(got) == 2 and got[0] == mine[-1] and len(got[1]) <= 3 and got[1] != mine[-1]:
        got = list(got[1]) + [got[0]]
    # Surname first, then a forename, with no comma (a French attestation's 'MR SMITH JOHN' for John Smith): turned round
    elif len(got) >= 2 and got[0] == mine[-1] and got[-1] != mine[-1] and got[-1] in mine[:-1]:
        got = got[1:] + [got[0]]
    if len(got) == 1:                              # only a surname printed: it decides
        return None if got[0] in mine else "NAME"
    if not _forename_match(got[:-1], mine[:-1] or mine):
        return "OTHER"
    if got[-1] != mine[-1] and got[-1] not in mine:
        # A double-barrelled surname with the person's surname as one half ('John Smith-Jones' for John
        # Smith), the forename matching: the same person, not a maiden name to ask about
        printed = NAME_WORDS.findall((employee or "").lower().split()[-1])
        if len(printed) > 1 and any(p in mine for p in printed):
            return None
        return "NAME"
    return None


def checks(f: Dict[str, Any], tax_year: str, ni_number: Optional[str],
           second: Optional[Dict[str, Any]] = None, person: Optional[str] = None) -> Tuple[str, List[str]]:
    """(status, the reasons a person must look) for a read P60."""
    notes: List[str] = []
    nil_tax(f)
    if f.get("pay_this") is None or f.get("tax_this") is None:
        return "CHECK", ["Pay or tax in this employment could not be read."]
    if f.get("tax_year") and f["tax_year"] != tax_year:
        return "OTHER_YEAR", [f"This P60 is for {f['tax_year']}, not {tax_year}: not used."]
    # No employer, no PAYE reference and the tax exactly 20% of the pay: the CIS rate, a subcontractor's list of payments
    # (self-employed income, SA103 with the CIS deducted), not an employer's P60. Not entered as employment until checked
    pay, tax = f["pay_this"], f["tax_this"]
    if not f.get("employer") and not f.get("paye_ref") and pay > 0 and abs(tax - 0.2 * pay) <= 0.005 * pay + 1:
        f["looks_cis"] = True
        return "CHECK", [f"No employer or PAYE reference, and the tax (£{tax:,.2f}) is exactly 20% of the pay (£{pay:,.2f}): "
                         f"a CIS subcontractor's payments (self-employment, R-SA103-10), not a P60? Not entered as "
                         f"employment until checked."]
    # Whose P60 it is: the NI number decides when both are known, the name only when not ('match on NINO, not name',
    # R-IN-07). Kept off the return until a person says it is theirs (a spouse's P60 in the wrong folder)
    mine, theirs = _ni(ni_number), _ni(f.get("ni_number"))
    if mine and theirs:
        if mine != theirs:
            f["other_person"] = True
            return "CHECK", [f"The NI number on this P60 is not {person or 'the person'}'s: not used. If it is theirs, confirm it (R-IN-07)."]
    else:
        who = owner(f.get("employee"), person)
        if who == "OTHER":
            f["other_person"] = True
            return "CHECK", [f"This P60 is for {f['employee']}, not {person}: not used. If it is theirs, confirm it."]
        if who == "NAME":
            # A name that differs is an error until a person confirms it: its pay stays on the return (most are the person's own: a typo, a job named for a couple), but
            # the return cannot be finished until the P60 is confirmed (queries.py)
            f["name_check"] = True
            notes.append(f"The P60 names {f['employee']}: check it is {person}'s (a maiden name?) and confirm it before "
                         f"the return is finished (R-IN-07).")
    if not f.get("tax_year"):
        notes.append("The P60 does not show its tax year: confirm it is for this return.")
    pay, tax = f["pay_this"], f["tax_this"]
    if pay < 0:
        notes.append("Pay in this employment is negative.")
    if tax > 0.5 * max(pay, 0) + 1:
        notes.append("Tax deducted is more than half the pay: check the two figures.")
    if None not in (f.get("pay_previous"), f.get("pay_total")) and abs(f["pay_previous"] + pay - f["pay_total"]) > 0.01:
        notes.append("Previous + this employment pay does not add up to the total for the year.")
    if None not in (f.get("tax_previous"), f.get("tax_total")) and abs(f["tax_previous"] + tax - f["tax_total"]) > 0.01:
        notes.append("Previous + this employment tax does not add up to the total for the year.")
    if f.get("paye_ref") and not re.fullmatch(r"\d{3}/[A-Z0-9]+", f["paye_ref"], re.I):
        notes.append(f"PAYE reference '{f['paye_ref']}' does not look like one (e.g. 120/AB12345).")
    if second is not None:
        s = nil_tax(clean(second))
        if not s.get("pay_this") and f.get("pay_this"):
            # The second reader found no pay at all: the first reader's figures are not confirmed (a page that is not a
            # P60, read as one: 'ABC COMPANY LTD' on an invoice), so not entered until a person checks the P60
            f["one_reader"] = True
            notes.append("Only one of the two readers found a P60 on this page: not entered until it is checked.")
        for k, label in (("pay_this", "pay"), ("tax_this", "tax")):
            if s.get(k) is None or abs((s.get(k) or 0) - (f.get(k) or 0)) > 0.005:
                notes.append(f"The two readers disagree on the {label} (£{f.get(k) or 0:,.2f} or "
                             f"£{s.get(k) or 0:,.2f}): look at the P60.")
        if f.get("tax_code") and s.get("tax_code") and str(f["tax_code"]).upper() != str(s["tax_code"]).upper():
            notes.append(f"The two readers disagree on the tax code ({f['tax_code']} or {s['tax_code']}).")
    return ("CHECK" if notes else "READ"), notes


def nil_tax(f: Dict[str, Any]) -> Dict[str, Any]:
    """A P60 whose tax box is left blank, for a year's pay within what its tax code allows tax-free (£9,096 on 1257L,
    which allows £12,579): nothing was deducted, so its tax is nil, not unread. A BR, 0T, K or emergency code taxes
    from the first pound, so a blank there stays a point to look at."""
    if f.get("pay_this") is None or f.get("tax_this") is not None:
        return f
    parts = code_parts(f.get("tax_code"))
    digits = re.sub(r"\D", "", str(f.get("tax_code") or ""))
    if not digits or parts["k"] or parts["flat"] or parts["emergency"]:
        return f
    year_pay = f.get("pay_total") if f.get("pay_total") is not None else f["pay_this"]
    if 0 <= year_pay <= int(digits) * 10 + 9:
        f["tax_this"] = 0.0
        if f.get("tax_total") is None:
            f["tax_total"] = 0.0
    return f


def code_parts(code: Optional[str]) -> Dict[str, Any]:
    """A tax code in its parts: '1131N' -> suffix N; 'K475' -> K; '1257L M1' or '1257L X' -> emergency; 'S1257L' and
    'C1257L' (Scotland, Wales) read the same way."""
    c = re.sub(r"\s", "", (code or "").upper())
    emergency = bool(re.search(r"(M1|W1|X)$", c))
    c = re.sub(r"(M1|W1|X)$", "", c)
    c = re.sub(r"^[SC](?=K|\d)", "", c)
    m = re.fullmatch(r"(K)?(\d*)([A-Z]{0,2})", c)
    if not m:
        return {"code": code, "k": False, "suffix": None, "emergency": emergency, "flat": c in ("BR", "D0", "D1", "0T", "NT")}
    return {"code": code, "k": bool(m.group(1)), "suffix": m.group(3) or None, "emergency": emergency,
            "flat": c in ("BR", "D0", "D1", "0T", "NT")}


def code_points(p60s: List[Dict[str, Any]], marriage: Optional[str], lel: float) -> List[Dict[str, Any]]:
    """What a P60's tax code and NI table say must be checked (R-FAM-04, R-NIC-02): an N suffix (Marriage
    Allowance given) or M (received) not on Family and loans; a K, T or emergency code to reconcile; earnings at the
    lower earnings limit under the year's limit (the job may not give a qualifying year)."""
    out = []
    for f in p60s:
        who = f.get("employer") or "a P60"
        code = code_parts(f.get("tax_code"))
        c = f.get("tax_code")
        if code["suffix"] == "N" and marriage != "TRANSFERRED":
            out.append({"key": f"code_n:{who}", "text": f"Tax code {c} ({who}) ends in N: the person gave Marriage Allowance "
                        f"to their spouse, so the personal allowance is cut by the transfer (applied from the code). "
                        f"Confirm it on Family and loans (R-FAM-04)."})
        if code["suffix"] == "M" and marriage != "RECEIVED":
            out.append({"key": f"code_m:{who}", "text": f"Tax code {c} ({who}) ends in M: the person receives Marriage "
                        f"Allowance from their spouse. Set it on Family and loans; it is not allowed if they pay tax above "
                        f"the basic rate (R-FAM-04)."})
        if code["k"]:
            out.append({"key": f"code_k:{who}", "text": f"Tax code {c} ({who}) is a K code: untaxed income or tax owed was "
                        f"collected through it. Find what it was and reconcile the tax paid (R-FAM-04)."})
        if code["suffix"] == "T":
            out.append({"key": f"code_t:{who}", "text": f"Tax code {c} ({who}) ends in T: HMRC adjusted it by hand. Check "
                        f"what it allowed for (R-FAM-04)."})
        if code["flat"]:
            # BR, D0, D1, 0T or NT: no allowance in this job: a second job, other income or
            # benefits coded, or a mistake; the allowance is given elsewhere or the tax is wrong
            out.append({"key": f"code_flat:{who}", "text": f"Tax code {c} ({who}) gives no personal allowance in this job: "
                        f"is it a second job, or is other income or a benefit coded? If it is the main job, the tax may "
                        f"be over or under: reconcile it on the return (R-FAM-04)."})
        if code["emergency"]:
            out.append({"key": f"code_x:{who}", "text": f"Tax code {c} ({who}) was used on an emergency basis (M1, W1 or X): "
                        f"the tax for the year may be wrong. Reconcile it on the return (R-FAM-04)."})
        lel_pay = f.get("earnings_at_lel")
        if lel_pay is not None and lel_pay < lel:
            out.append({"key": f"lel:{who}", "text": f"Earnings at the lower earnings limit on {who}'s P60 are "
                        f"£{lel_pay:,.2f}, under £{lel:,.0f}: this job may not give a qualifying year for the State "
                        f"Pension. Check the NI record (R-NIC-02)."})
    return out
