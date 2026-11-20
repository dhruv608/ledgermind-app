"""This year's questions (R-EX-05) and the signs of new income in the bank statements.

  questions  the yearly yes/no list is compulsory: every one answered before the return is finished; a Yes says
             what to ask for next (P60, CIS statements, disposals ...)
  signals    patterns in the year's bank lines that point to income not on the return yet; each becomes a
             confirmation question, never an assumption. The accountant asks it or dismisses it.

Each answer is kept in sa_answers ('q:<question>', 's:<signal>:<payer>')."""

import re
from collections import defaultdict
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

# (key, question, what a Yes needs, last year's answer key in the working paper)
QUESTIONS = [
    ("new_job", "Did you start a new job?", "Please send the P60 or P45 from the new job.", None),
    ("left_job", "Did you leave a job?", "Please send the P45.", None),
    ("new_property", "Did you buy, or start letting, a property?", "Please send the rent and costs, and the purchase papers.", None),
    ("sold", "Did you sell or give away anything of value: property, shares or crypto?",
     "Please send the sale and purchase details (capital gains; a UK home sold needs the 60-day check).", "capital_gains"),
    ("abroad", "Did you have income or money from abroad?", "Please send the foreign statements and any foreign tax assessment.", None),
    ("platform", "Did you sell on eBay, Etsy, Vinted, Airbnb, TikTok, YouTube or a similar site?",
     "Were these your own used things, or done to make money? Please send the platform's yearly report.", None),
    ("director", "Are you a director or shareholder of a company?", "Please send the dividend vouchers and the director's loan statement.", "director"),
    ("construction", "Did you do construction work?", "Please send the CIS statements from each contractor.", None),
    # Cash takings not paid into the bank are added to the turnover
    ("cash", "Do you take cash from customers that is not all paid into the bank?",
     "Please give the cash takings not banked for the year, or send the till record.", None),
    # A VAT-registered trade is worked net of VAT; its returns are needed
    ("vat", "Are you VAT registered (or did you register in the year)?",
     "Please send the VAT returns for the year, and say if you use the flat rate scheme.", None),
    ("new_pension", "Did you start a new pension, or pay into a personal pension?", "Please send the contribution statement.", None),
    ("child_benefit", "Do you or your partner receive Child Benefit?", "How many children, and the date it started (High Income Child Benefit Charge).", "child_benefit"),
    ("student_loan", "Are you repaying a student or postgraduate loan?", "Which plan is it on?", "student_loan"),
    ("married", "Did you marry, enter a civil partnership, or separate?", "The date, and your partner's income (Marriage Allowance).", "marriage_allowance"),
    # R-SP-03: money the client calls not taxable needs evidence and the accountant's decision, never their label alone
    ("exempt", "Did you receive money you think is not taxable: an inheritance, a gift, an insurance pay-out, or a salary "
               "you were told is tax free?",
     "Please send the papers that show what it is (the will, the insurer's letter, the employer's letter): it is checked "
     "before it is left off the return.", None),
]

# (kind, title, the words on the line, money in or out, the question; {payer} is filled in)
SIGNALS = [
    ("dividend", "Dividends", r"\bdiv(idend)?s?\b", "in", "Is {payer} your company? Please send the dividend vouchers."),
    ("cis", "Construction work", r"builder|construction|\blabou?r\b|plaster|roofing|scaffold|joinery|bricklay", "in",
     "Were you paid by {payer} under CIS? Please send the CIS statements."),
    ("overseas", "Money from abroad", r"internationa|\bswift\b|foreign|western union|remitly|\bwise\b|transferwise|worldremit|\bfx\b",
     "in", "What income did you have abroad? The payment from {payer}."),
    ("platform", "Online platform sales", r"\bebay\b|\betsy\b|vinted|airbnb|tiktok|youtube|depop|amazon payments|amzn payout|shpock",
     "in", "Were the payments from {payer} for your own used things, or done to make money? Please send the platform's yearly report."),
    ("letting", "Rent", r"letting|lettings|estate agent|property management|\brent\b", "in",
     "Are the payments from {payer} rent? Please send the letting statements."),
    ("benefit", "State benefits", r"\bdwp\b|\bjsa\b|\besa\b|carer|pension credit|universal credit|\bpip\b", "in",
     "What are the payments from {payer}? Some state benefits are taxable: please send the DWP letter."),
    ("savings", "Savings with no statement", r"savings?|\bsaver\b|\bisa\b|premium bonds|\bns ?& ?i\b|moneybox|\bchip\b|\bbond\b", "out",
     "Money went to {payer} during the year: please send the account's annual interest statement."),
    ("pension", "Pension payments", r"\bsipp\b|pension|aviva|scottish widows|standard life|royal london|hargreaves|aj bell|pensionbee|vanguard",
     "out", "Please send the contribution statement for your payments to {payer}."),
    ("childcare", "Childcare", r"nursery|childcare|childminder|tax-free childcare|tax free childcare", "out",
     "Do you or your partner receive Child Benefit? (payments to {payer})"),
]
LARGE = 2500.0                  # a one-off credit of this much or more, from a payer seen once in the year
REGULAR_TIMES = 3               # the same amount from one person this many times: room rent, a lodger
COMPANY = re.compile(r"\b(ltd|limited|plc|llp)\b", re.I)
REFUND = re.compile(r"refund|rebate|reversal|cashback|compensation|claim", re.I)
COMPANY_TIMES, COMPANY_TOTAL = 3, 500.0     # several payments from one company, this much in all
PERSON_NOT = re.compile(r"\b(ltd|limited|plc|llp|bank|council|hmrc|dwp|services|group|uk|insurance|pension|payments?)\b", re.I)


def _answers(db: Session, job) -> Dict[str, object]:
    from backend.app.sa.models import SAAnswer
    return {a.key: a for a in db.query(SAAnswer).filter(SAAnswer.job_id == job.id)}


def answer(db: Session, job, key: str, value: Optional[str], note: Optional[str] = None) -> None:
    from backend.app.sa.models import SAAnswer
    db.query(SAAnswer).filter(SAAnswer.job_id == job.id, SAAnswer.key == key).delete(synchronize_session=False)
    if value or note:
        db.add(SAAnswer(job_id=job.id, key=key[:120], value=value, note=note))
    db.commit()


def questions(db: Session, job, last_answers: Dict[str, bool]) -> List[Dict]:
    kept = _answers(db, job)
    out = []
    for key, text, follow, last_key in QUESTIONS:
        a = kept.get(f"q:{key}")
        last = last_answers.get(last_key) if last_key else None
        if key == "director" and job.company_engagement_id:
            last = True
        out.append({"key": key, "question": text, "answer": a.value if a else None, "note": a.note if a else None,
                    "follow": follow if a and a.value == "YES" else None,
                    "last_year": None if last is None else ("Yes" if last else "No")})
    return out


def find(lines: List[Dict], person: str, sources: set, employers: Optional[List[str]] = None) -> List[Dict]:
    """The signs of new income in the year's bank lines ({key, kind, title, question, payer, lines, total}); a sign
    the return already answers (a savings statement when interest is on the return) is left out."""
    from backend.app.services.bank_only.books import payee_key
    skip = {"savings": "SAVINGS" in sources, "pension": "RELIEFS" in sources, "letting": "PROPERTY" in sources,
            "dividend": "DIVIDENDS" in sources}
    own = {w for w in re.findall(r"[a-z]+", person.lower()) if len(w) >= 3}
    found: Dict[str, Dict] = {}
    flagged: set = set()

    def add(kind: str, title: str, question: str, payer: str, l: Dict) -> None:
        key = f"{kind}:{payer}"[:110]
        s = found.setdefault(key, {"key": key, "kind": kind, "title": title, "payer": payer, "lines": [],
                                   "question": question.format(payer=payer or "this payer")})
        s["lines"].append({"on": l["on"], "description": l["description"], "amount": l["in"] or l["out"]})
        flagged.add(id(l))

    for l in lines:
        if l.get("heading") == "TRANSFER":
            continue                    # money between the person's own accounts
        payer = payee_key(l["description"]) or l["description"][:40].lower()
        way = "in" if l["in"] else "out"
        for kind, title, words, need, question in SIGNALS:
            if need == way and not skip.get(kind) and re.search(words, l["description"], re.I):
                add(kind, title, question, payer, l)
                break
    # The same amount again and again from one person: room or chair rent, a lodger
    by = defaultdict(list)
    for l in lines:
        if l["in"] and l.get("heading") != "TRANSFER":
            by[(payee_key(l["description"]), l["in"])].append(l)
    for (payer, amount), ls in by.items():
        words = set(re.findall(r"[a-z]+", payer))
        if payer and len(ls) >= REGULAR_TIMES and amount >= 50 and not PERSON_NOT.search(payer) and not (words & own):
            for l in ls:
                add("regular", "Regular payments from one person", "What are the payments from {payer} for?", payer, l)
    # Several payments in from one company, with no trade on the return: work paid outside PAYE, commission or
    # expenses repaid, asked (it may be other income). Not an
    # employer (its P60 gives the pay), a selling platform, a refund or wages
    if "SELF_EMPLOYMENT" not in sources:
        from backend.app.sa.books import PAYOUT_PLATFORMS, WAGES_IN, _employer_words, employer_in
        emp = _employer_words(employers or [])
        company = defaultdict(list)
        for l in lines:
            d = l["description"] or ""
            if (l["in"] and l.get("heading") != "TRANSFER" and id(l) not in flagged and COMPANY.search(d)
                    and not REFUND.search(d) and not WAGES_IN.search(d) and not employer_in(d, emp)
                    and not set(re.findall(r"[a-z]{3,}", d.lower())) & PAYOUT_PLATFORMS):
                company[payee_key(d)].append(l)
        for payer, ls in company.items():
            if payer and len(ls) >= COMPANY_TIMES and sum(x["in"] for x in ls) >= COMPANY_TOTAL:
                for l in ls:
                    add("company", "Payments from a company", "What are the payments from {payer} for: dividends "
                        "from your company (please send the vouchers), work, commission, expenses repaid or something "
                        "else?", payer, l)
    # One large credit from a payer seen once in the year
    seen = defaultdict(int)
    for l in lines:
        if l["in"]:
            seen[payee_key(l["description"])] += 1
    for l in lines:
        payer = payee_key(l["description"])
        if l["in"] >= LARGE and seen[payer] == 1 and l.get("heading") not in ("TRANSFER", "TURNOVER") \
                and id(l) not in flagged:
            add("large", "Large one-off payment in", f"What was the £{l['in']:,.2f} on {l['on']} from {{payer}}?", payer or "an unknown payer", l)
    out = list(found.values())
    for s in out:
        s["total"] = round(sum(x["amount"] for x in s["lines"]), 2)
    return sorted(out, key=lambda s: -s["total"])


def view(db: Session, job, last_answers: Dict[str, bool]) -> Dict:
    from backend.app.sa import books
    from backend.app.sa.income import tax_year_dates
    from backend.app.sa.models import SALine
    start, end = (x.isoformat() for x in tax_year_dates(job.tax_year))
    lines = books.sort_lines(books.accounts(db, job), job.person_name, start, end, None, books.remittances(db, job))
    sources = {s for (s,) in db.query(SALine.source).filter(SALine.job_id == job.id).distinct()}
    from backend.app.sa.models import SAProperty
    if db.query(SAProperty).filter(SAProperty.job_id == job.id).count():
        sources.add("PROPERTY")
    kept = _answers(db, job)
    sigs = find(lines, job.person_name, sources, books.employers(db, job))
    for s in sigs:
        a = kept.get("s:" + s["key"])
        s["state"] = a.value if a else None
        s["note"] = a.note if a else None
    qs = questions(db, job, last_answers)
    return {"questions": qs, "signals": sigs, "bank_lines": len(lines),
            "open": sum(1 for q in qs if not q["answer"]) + sum(1 for s in sigs if not s["state"])}


def for_job(db: Session, job) -> Dict:
    """The questions and signs, with last year's answers from last year's working paper."""
    import json
    from backend.app.sa import lastyear
    doc = lastyear.last_year_doc(db, job)
    return view(db, job, (json.loads(doc.fields).get("answers") or {}) if doc else {})
