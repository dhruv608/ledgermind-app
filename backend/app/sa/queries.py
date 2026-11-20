"""The return's queries, as the firm's Queries sheet keeps them:

  client query        a plain-English question to the client (an Unknown source, a change over 25%, this year's
                      questions, a document to send, a sign of new income the accountant chose to ask about)
  accountant decision a judgement for the accountant (money treated as not taxable, R-SP-03; a line the two readers
                      read differently; a sign of new income not yet decided)
  block               the return cannot be finished while it is open (an Unknown source is a client query and
                      blocks finalisation; R-EX-05: the yearly questions are compulsory; R-OUT-01: no pack while a Block is open)

Nothing is stored here: each query comes from its line (last year's checklist, the questions, the bank signs) and its
answer is kept on that line, so answering on either page answers both."""

import re
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

CLIENT, DECISION = "CLIENT", "DECISION"


def queries(db: Session, job) -> Dict:
    from backend.app.sa import lastyear, signals
    ly = lastyear.view(db, job)
    qs = signals.for_job(db, job)
    items: List[Dict] = []

    def add(key: str, kind: str, text: str, page: str, block: bool, answer, done: bool, about: str = "") -> None:
        items.append({"key": key, "kind": kind, "text": text, "page": page, "block": block and not done,
                      "answer": answer, "status": "DONE" if done else ("ANSWERED" if answer else "OPEN"), "about": about})

    # No usable last year (no working paper, or a blank template: no lines read): the new-client route (R-EX-06)
    if not ly["lines"]:
        add("ly:none", DECISION, ("A first return with us" if job.first_return else "No usable last-year working paper")
            + ": there is no list of last year's sources to check this year against. Pull last year's return through "
            "agent access (HMRC online) before preparing, and add its sources on Last year (R-EX-06).",
            "last-year", True, None, False, "Last year")
    for l in ly["lines"]:
        about = f"{l['source_label']}: {l['name']}"
        if l["kind"] == "EXEMPT":
            add(f"exp:{l['id']}", DECISION,
                f"{l['name']} ({'£{:,.2f}'.format(l['last_amount']) if l['last_amount'] is not None else 'no figure'}) was treated "
                f"as not taxable last year. Decide this year's treatment: evidence is needed, never the client's label alone.",
                "last-year", True, l["answer"], bool(l["hand"]), about)
            if l["question"]:
                add(f"exp-q:{l['id']}", CLIENT, l["question"], "last-year", False, l["answer"], bool(l["hand"]), about)
            continue
        if l["question"]:
            # Last year's carry-forward items are the accountant's to deal with, not a question for the client
            add(f"exp:{l['id']}", DECISION if l["source"] == "CARRY_FORWARD" else CLIENT, l["question"], "last-year",
                l["status"] == "UNKNOWN" and l["kind"] != "USE_OF_HOME", l["answer"],
                l["status"] not in ("UNKNOWN", "CHANGED") or bool(l["hand"]), about)
        if not l["agreed"]:
            add(f"check:{l['id']}", DECISION, f"Last year's {l['name']} was read differently by the two readers: check it "
                f"against the working paper.", "last-year", False, None, False, about)

    open_q = [q for q in qs["questions"] if not q["answer"]]
    if open_q:
        add("questions", CLIENT, "Please answer this year's questions: " + " ".join(q["question"] for q in open_q),
            "last-year", True, None, False, "This year's questions")
    for q in qs["questions"]:
        if q["follow"]:
            add(f"q:{q['key']}", CLIENT, q["follow"], "last-year", False, q["note"], bool(q["note"]), q["question"])
    for s in qs["signals"]:
        if s["state"] == "ASKED":
            add(f"s:{s['key']}", CLIENT, s["question"], "last-year", False, s["note"], bool(s["note"]), s["title"])
        elif not s["state"]:
            add(f"sd:{s['key']}", DECISION, f"{s['title']} in the bank ({len(s['lines'])} line(s), £{s['total']:,.2f}): ask the "
                f"client or mark it not income.", "last-year", False, None, False, s["title"])

    # Family and loans: the Child Benefit charge, Marriage Allowance and loan plans (answered on their page)
    from backend.app.sa import family
    from backend.app.sa.income import calculation
    from backend.app.sa.models import SAFamily
    answers = {q["key"]: q["answer"] for q in qs["questions"]}
    calc = calculation(db, job)
    for f in family.issues(db.get(SAFamily, job.id), calc["calculation"], answers, job.tax_year):
        add(f"fam:{f['key']}", f["kind"], f["text"], "family", f["block"], None, False, "Family and loans")
    # Property: owner, Form 17, Rent-a-Room choice, a sale to enter (answered on the property pages)
    for page, pool in (("property", calc["property"]), ("foreign", calc["foreign_property"])):
        for r in pool["properties"]:
            for i in r.get("issues", []):
                add(f"prop:{i['key']}", i["kind"], i["text"], page, i["block"], None, False, f"Property: {r['name']}")
    # Capital gains: dates, costs, the 60-day return, choices (answered on the Capital gains page)
    for i in calc["cgt"]["issues"]:
        add(f"cg:{i['key']}", i["kind"], i["text"], "capital_gains", i["block"], None, False, "Capital gains")
    # Foreign income: treaty questions, foreign tax to reclaim; income from abroad said but nothing entered blocks
    for r in calc["foreign"]:
        for i in r["issues"]:
            add(f"fx:{i['key']}", i["kind"], i["text"], "foreign", i["block"], None, False, "Foreign income")
    # The tax-year gate (R-IN-05): most dated documents for other years means this year's are missing
    import json as _json
    import re as _re
    from backend.app.sa.models import SADocument as _D
    from backend.app.sa.extract.interest import _tax_year_of
    dated = []
    for d in db.query(_D).filter(_D.job_id == job.id, _D.status != "DUPLICATE"):
        if d.kind in ("WORKING_PAPER", "TAX_CALCULATION", "BUNDLE"):
            continue                       # last year's paper and calculation are meant to be last year's
        year = d.tax_year
        if d.kind == "BANK_STATEMENT" and d.fields:
            last = _json.loads(d.fields).get("last")
            year = _tax_year_of(last) or year  # a statement by the date it ends
        if year:
            dated.append((d.filename, year))
    other = [n for n, y in dated if y != job.tax_year]
    if len(dated) >= 3 and len(other) * 2 > len(dated):
        listed = ", ".join(sorted({n.split("/")[-1] for n in other})[:6])
        add("gate:year", CLIENT, f"Most of the documents sent are for other tax years ({len(other)} of {len(dated)}: "
            f"{listed}). Please send the documents for {job.tax_year} (6 April {job.tax_year[:4]} to 5 April "
            f"{int(job.tax_year[:4]) + 1}).", "documents", True, None, False, "Documents")
    # Gift cards or products received: income of the trade, or a benefit? Never assumed
    gifts = sorted({d.filename.split("/")[-1] for d in db.query(_D).filter(_D.job_id == job.id)
                    if _re.search(r"e-?gift|gift ?card|voucher", d.filename or "", _re.I)})
    if gifts:
        add("sig:gifts", DECISION, f"Gift cards or vouchers are among the documents ({', '.join(gifts[:4])}): were they "
            f"received for work (trading income), from an employer (a benefit), or as a personal gift? (Step 4)",
            "documents", False, None, False, "Documents")
    # A foreign tax letter with no foreign income on the return blocks it (R-SA106-07)
    import json as _json
    from backend.app.sa.extract import foreign_tax as _ftax
    from backend.app.sa.models import SADocument
    # A letter whose figures could not be read still blocks: the income it is about must be found
    letters = [_json.loads(d.fields) if d.fields else {"country": d.filename.replace("\\", "/").split("/")[-1]}
               for d in db.query(SADocument).filter(
                   SADocument.job_id == job.id, SADocument.kind == "FOREIGN_TAX", SADocument.status.in_(("READ", "CHECK")))]
    letters = [f for f in letters if not f.get("other_person")]
    if letters and not calc["foreign"] and not calc["income"]["foreign"]:
        add("fx:letter", DECISION, "A foreign tax document (" + "; ".join(_ftax.summary(f) for f in letters) + ") but no "
            "foreign income is entered: find the income and enter it in pounds on Foreign income (R-SA106-07).",
            "foreign", True, None, False, "Foreign income")
    if answers.get("abroad") == "YES" and not calc["foreign"] and not calc["income"]["foreign"]:
        add("fx:none", DECISION, "The client had income or money from abroad, but no foreign income is entered: find it and "
            "enter it on Foreign income (R-SA106-07).", "foreign", True, None, False, "Foreign income")
    import json as _json
    from backend.app.sa.models import SADocument
    # HMRC's tax calculations (sa302.py): last year's sets this year's payments on account (R-FAM-03); this year's,
    # once filed, is checked against the return here
    from backend.app.sa.extract import sa302 as _sa302
    from backend.app.sa.models import SAPayments as _Pay
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "TAX_CALCULATION",
                                         SADocument.status.in_(("READ", "CHECK"))):
        f = _json.loads(d.fields) if d.fields else {}
        if f.get("other_person"):
            continue
        if f.get("tax_year") == _sa302.previous(job.tax_year):
            each = _sa302.poa_from_last_year(f)
            if each and db.get(_Pay, job.id) is None:
                add("hmrc:poa", DECISION, f"HMRC's {f['tax_year']} calculation set payments on account of £{each:,.2f} each "
                    f"for {job.tax_year} (31 January and 31 July): check they were paid and enter them on Tax calculation "
                    f"(R-FAM-03).", "tax", False, None, False, "HMRC record")
        elif f.get("tax_year") == job.tax_year and f.get("due") is not None:
            ours = calc["calculation"]["balance"]
            if abs(ours - f["due"]) > 1:
                add("hmrc:diff", DECISION, f"HMRC's {job.tax_year} calculation shows £{f['due']:,.2f} due; this return works "
                    f"out £{ours:,.2f}: find the difference before filing.", "tax", False, None, False, "HMRC record")
    # Employment status screen for each trade (status.py, R-SA103-10): its income lines from the bank and the client's
    # sheet, against the employers on the return
    from backend.app.sa import books as _books
    from backend.app.sa.models import SABusiness as _Biz, SABusinessItem as _Item, SALine as _Line
    from backend.app.sa.status import signals as _status
    employers = [l.label for l in db.query(_Line).filter(_Line.job_id == job.id, _Line.source == "EMPLOYMENT")]
    for biz in db.query(_Biz).filter(_Biz.job_id == job.id):
        lines = [(None, i.description, float(i.amount or 0))
                 for i in db.query(_Item).filter(_Item.business_id == biz.id, _Item.heading == "TURNOVER", _Item.doc_id.isnot(None))]
        try:
            lines += [(l["on"], l["description"], l["in"]) for l in _books.view(db, job, biz)["lines"]
                      if l["heading"] == "TURNOVER" and l["in"]]
        except Exception:
            pass
        found = _status(lines, employers, bool(biz.use_trading_allowance), job.person_name)
        if found:
            add(f"status:{biz.id}", DECISION, f"{biz.name}: signs this may be employment, not self-employment: "
                + " ".join(found) + " Check the employment status before the return is finished (R-SA103-10).",
                "self_employment", False, None, False, "Self-employment")
    # The director checks from the linked company's books (director.py, R-DIR-02 to -06)
    from backend.app.sa.director import points as _director
    try:
        for pt in _director(db, job):
            add(f"dir:{pt['key']}", DECISION, pt["text"], "dividends", False, None, False, "Director")
    except Exception:
        pass                               # a company file that cannot be read gives no director points
    # Household links to the firm's other clients this year (household.py, R-IN-06)
    from backend.app.sa.household import links as _links
    for l in _links(db, job):
        add(f"house:{l['job_id']}", DECISION, f"Linked to {l['person']}'s return: " + "; ".join(l["why"]) + ". Count each "
            "joint item once and split it by ownership between the two returns (R-IN-06).", "details", False, None, False,
            "Household")
    # Rent in the person's own bank not yet on a property (property_bank.py, R-SA105-01)
    from backend.app.sa.property_bank import found as _bank_rent
    try:
        rent = _bank_rent(db, job)
    except Exception:
        rent = []                          # statements that cannot be put together give no rent point
    if rent:
        add("prop:bank", DECISION, f"Rent of £{sum(g['total'] for g in rent):,.2f} from {len(rent)} payer"
            f"{'s' if len(rent) > 1 else ''} in the bank is not on a property yet: put each payer on its property on the "
            f"Property page (R-SA105-01).", "property", False, None, False, "Property")
    # Dividends in the bank with no voucher on the return (bank_dividends.py, R-SAV-04)
    from backend.app.sa.bank_dividends import found as _bank_divs
    try:
        divs = _bank_divs(db, job)
    except Exception:
        divs = []
    for g in divs:
        add(f"div:bank:{g['payer'][:40]}", CLIENT, f"Dividends of £{g['total']:,.2f} from {g['payer']} were paid into the bank "
            f"({g['count']} payment{'s' if g['count'] > 1 else ''}) but no voucher is on the return: please send the dividend "
            f"vouchers, or for the client's own company its dividend record (R-SAV-04, R-DIR-01).", "dividends", False, None,
            False, "Dividends")
    # The trade's own points: a loss, a business that stopped, building work without CIS, cash basis entry
    from backend.app.sa.trade_points import points as _trade_points
    for pt in _trade_points(db, job, calc):
        add(f"trade:{pt['key']}", pt["kind"], pt["text"], pt.get("page", "self_employment"), pt["block"], None,
            bool(pt.get("done")), "Self-employment")
    # Admin points: coding out, leaving Self Assessment, Making Tax Digital (admin.py, R-ADM-01 to 03)
    from backend.app.sa.admin import points as _admin
    from backend.app.sa.models import SADocument as _Doc
    kinds = {k for (k,) in db.query(_Doc.kind).filter(_Doc.job_id == job.id, _Doc.status != "DUPLICATE").distinct()}
    for pt in _admin(calc, job.tax_year, kinds):
        add(f"adm:{pt['key']}", DECISION, pt["text"], "tax", False, None, False, "Admin")
    # Foster care: placement dates, and the method when over the limit (R-SP-01; answered on Self-employment)
    for i in calc["care"]["issues"]:
        add(f"care:{i['key']}", i["kind"], i["text"], "self_employment", i["block"], None, False, "Foster care")
    # The P60s' tax codes and NI tables (R-FAM-04, R-NIC-02): the P60s on the return, never another person's
    import json as _json
    from backend.app.sa.extract import p60 as _p60
    from backend.app.sa.engine.calc import rates_for
    from backend.app.sa.models import SADocument
    fam = db.get(SAFamily, job.id)
    used = [_json.loads(d.fields) for d in db.query(SADocument).filter(
        SADocument.job_id == job.id, SADocument.kind == "P60", SADocument.status.in_(("READ", "CHECK"))) if d.fields]
    used = [f for f in used if not f.get("other_person")]
    # A P60 in a name that differs from the person's blocks until it is confirmed on Documents (a name that does
    # not match is an error); confirming it marks it read, which clears this
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "P60",
                                         SADocument.status == "CHECK"):
        f = _json.loads(d.fields) if d.fields else {}
        if f.get("name_check") and not f.get("other_person"):
            add(f"p60:name:{d.id}", DECISION, f"The P60 from {f.get('employer') or 'an employer'} names {f.get('employee')}: "
                f"confirm on Documents that it is this person's before the return is finished (R-IN-07).",
                "documents", True, None, False, "Employment")
    lel = rates_for(job.tax_year).get("class1", {}).get("lower_earnings_limit", 0)
    for pt in _p60.code_points(used, fam.marriage if fam else None, lel):
        add(f"p60:{pt['key']}", DECISION, pt["text"], "employment", False, None, False, "Employment")
    # Receiving Marriage Allowance (an M code) while taxed above the basic rate: not allowed (ITA s55B, R-FAM-04)
    from backend.app.sa.family import above_basic as _above
    from backend.app.sa.income import marriage_from_codes as _ma
    if not (fam and fam.marriage) and _ma(db, job) == "RECEIVED" and _above(calc["calculation"]):
        add("p60:ma_rate", DECISION, "The tax code shows Marriage Allowance received (M), but this person is taxed above "
            "the basic rate, so it is not allowed (ITA s55B). Choose on Family and loans whether the election stands "
            "(R-FAM-04).",
            "employment", False, None, False, "Employment")
    # Self-employed profits under the small profits threshold: Class 2 is not treated as paid (R-NIC-01); done once the
    # accountant has made the Class 2 choice on Tax calculation
    if calc["calculation"]["class2_below_threshold"]:
        from backend.app.sa.models import SAPayments
        credits = _ni_credits(db, job)
        add("nic:class2", DECISION, "Self-employed profits are under the small profits threshold, so Class 2 is not treated "
            "as paid and the year may not count for the State Pension: check the client's NI record and ask whether they "
            "want to pay voluntary Class 2 (R-NIC-01). Choose it on Tax calculation."
            + (f" First check the NI credits: the client {credits}, which may give a credit for the year (Carer's Credit, "
               f"foster carer credits, or credits with a benefit), so voluntary Class 2 may not be needed (R-NIC-03)."
               if credits else ""), "tax", False, None,
            db.get(SAPayments, job.id) is not None, "National Insurance")
    # Class 4 with a State Pension on the return: none is due if State Pension age was reached before 6 April
    c = calc["calculation"]
    from backend.app.sa.models import SALine as _SPLine
    if c["class4"] and db.query(_SPLine.id).filter(_SPLine.job_id == job.id, _SPLine.include == 1, _SPLine.source == "PENSIONS",
                                                   _SPLine.kind == "STATE_PENSION").first():
        add("nic:class4", DECISION, "The client gets the State Pension and Class 4 is charged on the self-employed "
            "profits: no Class 4 is due if they reached State Pension age before 6 April of the year (SOP N4). Check the "
            "date of birth and mark it on Tax calculation (exempt, or checked and not exempt).", "tax", False, None,
            bool(c.get("class4_checked")), "National Insurance")
    if answers.get("exempt") == "YES":
        add("q:exempt", DECISION, "The client says they received money that is not taxable. Decide it on the evidence (the "
            "will, the insurer's or employer's letter): never on the client's label alone (R-SP-03).", "documents", False,
            None, False, "Other income")
    if answers.get("sold") == "YES" and not calc["cgt"]["disposals"]:
        add("cg:none", DECISION, "The client sold or gave away something of value, but no disposal is entered: enter each "
            "one on Capital gains (the client is asked for the papers).", "capital_gains", True, None, False, "Capital gains")

    for kind in (CLIENT, DECISION):
        for n, it in enumerate((i for i in items if i["kind"] == kind), start=1):
            it["no"] = n
    return {"items": items,
            "counts": {"client": sum(1 for i in items if i["kind"] == CLIENT and i["status"] == "OPEN"),
                       "decisions": sum(1 for i in items if i["kind"] == DECISION and i["status"] != "DONE"),
                       "blocks": sum(1 for i in items if i["block"])}}


CREDIT_BENEFITS = re.compile(r"carer|universal credit|child benefit|jobseeker|\bjsa\b|\besa\b|employment and support|"
                             r"incapacity|\bpip\b|disability", re.I)


def _ni_credits(db: Session, job) -> Optional[str]:
    """What gives the client a possible NI credit for the year (R-NIC-03): fostering, or a benefit paid to them."""
    from backend.app.sa.models import SADocument, SALine
    if db.query(SADocument.id).filter(SADocument.job_id == job.id, SADocument.kind == "FOSTER_LETTER").first():
        return "fosters"
    for l in db.query(SALine).filter(SALine.job_id == job.id, SALine.source == "PENSIONS"):
        if l.kind == "BENEFIT" or CREDIT_BENEFITS.search(l.label or ""):
            return f"receives {l.label}"
    return None


def client_text(data: Dict, person: str, tax_year: str) -> str:
    """The open client queries as one message to send (numbered, plain English)."""
    open_q = list({i["text"]: i for i in data["items"] if i["kind"] == CLIENT and i["status"] == "OPEN"}.values())
    lines = [f"Hello {person.split()[0] if person else ''},".replace(" ,", ","), "",
             f"To finish your {tax_year} tax return we need a few things from you:", ""]
    lines += [f"{n}. {i['text']}" for n, i in enumerate(open_q, start=1)]
    lines += ["", "Thank you."]
    return "\n".join(lines)
