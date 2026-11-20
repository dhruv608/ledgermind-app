"""The firm's query rules that no other check raises: each looks at the job's trial balance, ledger lines (the client's GL, or on a bank job the books
worked out from the bank), aged lists and Companies House details, and gives a query for the Queries tab only. They
change no review point, journal or workbook figure.

  TB-06 asset sold or scrapped          TB-11 two director's loan accounts for one director
  TB-13 other debtors / creditors breakdown   DL-06 personal tax paid by the company
  GL-07 legal or professional fees that may be capital   AR-04 credit balances on the aged debtors (debit on creditors)
  YE-06 large amounts after the year end   BK-16 lines dated before the company was formed
  SQ-01 first period   SQ-03 expenses paid personally   SQ-04 income not banked or received in advance
  SQ-05 share capital paid in?

The amounts that decide a query are the firm's own (Firm setting "query_limits"), the defaults (LIMITS) otherwise."""

import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord

logger = logging.getLogger(__name__)

# Default limits: a firm can set its own in the Firm setting "query_limits"
LIMITS = {
    "disposal": 500.0,            # TB-06: an asset line or sale receipt worth asking about
    "breakdown": 1000.0,          # TB-13: other debtors / other creditors needing a breakdown
    "professional_fees": 2000.0,  # GL-07: one legal or professional fee that may be capital
    "listing": 100.0,             # AR-04: a credit balance on the debtors list (debit on the creditors list)
    "large_one_off": 2000.0,      # YE-06: an amount after the year end worth asking about
    # Bank jobs (queries/bank_rules.py)
    "property_payment": 5000.0,   # BK-11: a payment to solicitors / estate agents worth a completion statement
    "cash_total": 250.0,          # BK-07: cash in and out in the year worth asking about
    "personal_total": 250.0,      # BK-13: spending that looks personal worth asking about
    "lender_receipt": 500.0,      # BK-05: money in from a lender (a new loan?)
    "regular_payment": 50.0,      # BK-04: a regular payment to a lender or lessor, a month
    "unpaid_bill": 100.0,         # AS-02: a bill unpaid at the year end
    "unknown_in": 500.0,          # BK-01: money in taken as sales worth asking about (£500 per payer)
    "one_off_in": 2000.0,         # BK-01: a payer seen once or twice paying in this much is not takings
    "pay_person": 500.0,          # PY-08: pay to one person, with no payroll report, worth asking about
}

ASSET_SECTIONS = ("Tangible assets", "Intangible assets")
BANK_SECTION = "Cash at bank and in hand"
SHARE_SECTION = "Share capital"
CALLED_UP_NOT_PAID = 4480
DIRECTORS_LOAN_CODES = tuple(range(5400, 5410)) + tuple(range(5800, 5810))
LEGAL_FEES, PROFESSIONAL_FEES = 3302, 3303
TITLES = ("mr", "mrs", "ms", "miss", "dr", "sir")
# Money in from selling a car or a property (TB-06): dealers, auctions, car buyers, a sale's completion
SALE_WORDS = re.compile(r"\b(motors?|car sales|cars? ltd|auctions?|we ?buy ?any ?car|cinch|carwow|motorpoint|bca|"
                        r"arnold clark|completion|sale proceeds|part ?ex(change)?)\b", re.I)
# HMRC self assessment payments carry the taxpayer's 10-digit UTR and a K (DL-06)
SELF_ASSESSMENT = re.compile(r"\b(self ?-?assessment|\d{10}\s?k)\b|\bhmrc\b.*\bsa\b", re.I)    # 'HMRC GOV.UK SA'
SHARES = re.compile(r"\bshares?\b", re.I)
PERSONAL_LOAN_WORDS = re.compile(r"\bloan\b.*\b(friend|family|mum|dad|brother|sister|owe)\b|\b(friend|family)\b.*\bloan\b|"
                                 r"\bstill owe\b|\bpersonal loan\b", re.I)
# The cost of forming the company (SQ-01): the Companies House fee or a formation agent
FORMATION = re.compile(r"companies ?house|formation|incorporat|1st formations|\bcompany registration\b", re.I)


def query_limits(db: Session) -> Dict[str, float]:
    """The firm's query limits (Firm setting 'query_limits', any left out at the default)."""
    from backend.app.models.firm_settings import FirmSetting
    row = db.get(FirmSetting, "query_limits")
    try:
        saved = json.loads(row.value) if row is not None else {}
    except ValueError:
        saved = {}
    return {k: float(saved.get(k, v)) for k, v in LIMITS.items()}


def _money(v: float) -> str:
    return f"£{abs(v):,.2f}"


def _query(key: str, audience: str, title: str, detail: str, amount: float = 0.0, round_: int = 2,
           lines: Optional[List[str]] = None, rule: str = "") -> Dict[str, Any]:
    if lines:
        shown = lines[:25]
        detail += "\n\n" + "\n".join(f"- {l}" for l in shown)
        if len(lines) > len(shown):
            detail += f"\n- …and {len(lines) - len(shown)} more"
    return {"key": f"r1:{key}", "source": "rules", "round": round_, "audience": audience, "title": title,
            "detail": detail, "amount": round(amount, 2), "blocking": False, "go_to": "", "items": [], "done": False,
            "ref": rule}


def _line_text(l) -> str:
    when = f"{l.when:%d/%m/%Y} " if l.when else ""
    return f"{when}{(l.description or l.account or '').strip()}: {_money(l.debit - l.credit)}"


def _companies_house(profile) -> Dict[str, Any]:
    try:
        return json.loads(profile.companies_house or "{}") if profile is not None and profile.companies_house else {}
    except ValueError:
        return {}


def _directors(profile) -> List[str]:
    try:
        names = json.loads(profile.directors or "[]") if profile is not None and profile.directors else []
    except ValueError:
        names = []
    return [n if isinstance(n, str) else (n.get("name") or "") for n in names]


def _names(account: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", account.lower()) is not None


def r1_queries(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    from backend.app.services.queries.query_list import ACCOUNTANT, CLIENT, INTERNAL
    from backend.app.services.setup.data_check import first_year, incorporated_in_year
    from backend.app.services.setup.profile_service import ProfileService
    from backend.app.services.sop.common import gl_lines
    from backend.app.services.tax.ct_computation import final_balances

    tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == eng.id)).scalars())
    if not tb:
        return []
    limits = query_limits(db)
    profile = ProfileService.get_or_create_profile(db, eng.id)
    chart = db.query(MasterCOA).all()
    section = {c.std_code: c.category or "" for c in chart}
    names = {c.std_code: c.std_name or "" for c in chart}
    balances = final_balances(str(eng.id), tb, db)
    lines = gl_lines(str(eng.id), tb, db)
    ye: Optional[date] = eng.period_end_date
    out: List[Dict[str, Any]] = []

    # TB-06: an asset sold, part-exchanged or scrapped (a credit to an asset's cost, a disposal account used, or
    # money in from a dealer, an auction or a sale's completion)
    asset_cost = {c for c, s in section.items() if s in ASSET_SECTIONS and "cost" in names[c].lower()}
    asset_disposal = {c for c, s in section.items() if s in ASSET_SECTIONS and "disposal" in names[c].lower()}
    found = [l for l in lines if l.code in asset_cost and l.credit >= limits["disposal"]]
    found += [l for l in lines if l.code in asset_disposal and abs(l.debit - l.credit) >= limits["disposal"]]
    found += [l for l in lines if section.get(l.code) == BANK_SECTION and l.debit >= limits["disposal"]
              and SALE_WORDS.search(l.description or "")]
    if found:
        out.append(_query("TB-06", CLIENT, "Assets sold, part-exchanged or scrapped",
                          "The books show what looks like an asset leaving the business. For each asset sold, "
                          "part-exchanged or scrapped in the year, please confirm which asset it was, the date and the "
                          "price received, and send the sale invoice or part-exchange paperwork.",
                          sum(abs(l.debit - l.credit) for l in found), lines=[_line_text(l) for l in found],
                          rule="TB-06"))

    # TB-11: one director with two or more director's loan accounts (one account in the accounts and for s455)
    dla = [t for t in tb if t.std_code in DIRECTORS_LOAN_CODES and abs(float(t.net_amount or 0)) >= 0.005]
    people = []
    for director in _directors(profile):
        words = [w for w in re.findall(r"[a-z]+", director.lower()) if w not in TITLES]
        if words and len(words[-1]) >= 3:
            people.append((director, words[-1], [w for w in words[:-1] if len(w) >= 3]))
    seen = set()
    for director, surname, given in people:
        # An account naming the surname is this director's when it names their first name too, or no other name of
        # theirs while no other director has the surname (an account in a
        # relative's name is not the director's; two directors with one surname each have their own)
        family = sum(1 for p in people if p[1] == surname) > 1
        first_name = given[0] if given else ""
        own = [t for t in dla if _names(t.raw_account_name, surname) and (
            (first_name and _names(t.raw_account_name, first_name))
            or (not family and not any(_names(t.raw_account_name, w) for w in given[1:])))]
        ids = frozenset(t.id for t in own)
        if len(own) >= 2 and ids not in seen:
            seen.add(ids)
            out.append(_query(f"TB-11:{surname}:{given[0] if given else ''}", INTERNAL,
                              f"{director}: {len(own)} director's loan accounts",
                              "These accounts are all this director's loan. Combine them into one director's loan "
                              "account (the overdrawn balance and any s455 tax are worked on the total).",
                              sum(float(t.net_amount or 0) for t in own),
                              lines=[f"{t.raw_account_name}: {_money(float(t.net_amount or 0))}" for t in own],
                              rule="TB-11"))

    # TB-13: other debtors / other creditors over the limit need a breakdown from the client
    for code, bal in sorted(balances.items()):
        name = names.get(code, "")
        debtors = name.startswith("Other debtors")
        if not (debtors or name.startswith("Other creditors")) or abs(bal) < limits["breakdown"]:
            continue
        kind = "Other debtors" if debtors else "Other creditors"
        accounts = ", ".join(sorted({t.raw_account_name or "" for t in tb if t.std_code == code}))
        # The ledger's own words on a payment put there as a loan to or from a person ('loan from friend. Still
        # owe him'): quoted, with the director's loan as the likely home when it is the director's own loan
        said = [l for l in lines if l.code == code and l.debit + l.credit >= limits["breakdown"]
                and PERSONAL_LOAN_WORDS.search(l.description or "")]
        quote = ("" if not said else " The ledger says: " + "; ".join(
            f"'{(l.description or '')[:120]}' {_money(l.debit or l.credit)} on {l.when:%d/%m/%Y}" for l in said[:3])
            + ". If the company paid this for the director (the director's own loan from a friend or family), it "
              f"belongs on the director's loan account (Dr 5400 / Cr {code}): please confirm.")
        out.append(_query(f"TB-13:{code}", CLIENT, f"{kind} of {_money(bal)}: breakdown needed",
                          f"Please send a breakdown of the {_money(bal)} in {kind.lower()} at the year end ({accounts}): "
                          + ("who owes it to the company, what for, and whether it has since been received."
                             if debtors else "who the company owes it to, what for, and whether it has since been paid.")
                          + quote,
                          bal, rule="TB-13"))

    # DL-06: the director's own tax paid by the company (a self assessment payment or return fee in the costs; the
    # side in the bank, or one already in the director's loan account, is not asked about)
    found = [l for l in lines if SELF_ASSESSMENT.search(l.description or "") and l.debit + l.credit > 0
             and section.get(l.code) != BANK_SECTION and l.code not in DIRECTORS_LOAN_CODES]
    if found:
        out.append(_query("DL-06", ACCOUNTANT, "Personal tax paid by the company",
                          "These lines mention self assessment: the director's own tax (or the fee for the director's "
                          "own tax return), not the company's. Charge them to the director's loan account (or treat "
                          "them as pay through the payroll), and take them out of the company's costs.",
                          sum(abs(l.debit - l.credit) for l in found), lines=[_line_text(l) for l in found],
                          rule="DL-06"))

    # GL-07: a large legal or professional fee may be part of buying an asset (capital), not a cost of the year
    ask = ("Fees for buying a property or other asset, a new lease or raising a loan are part of that cost, not a "
           "cost of the year.")
    if lines:
        found = [l for l in lines if l.code in (LEGAL_FEES, PROFESSIONAL_FEES) and l.debit >= limits["professional_fees"]]
        if found:
            out.append(_query("GL-07", CLIENT, "Large legal or professional fees: what were they for?",
                              f"Please tell us what each of these fees was for. {ask}", sum(l.debit for l in found),
                              lines=[_line_text(l) for l in found], rule="GL-07"))
    else:
        for code in (LEGAL_FEES, PROFESSIONAL_FEES):
            bal = balances.get(code, 0.0)
            if bal >= limits["professional_fees"]:
                out.append(_query(f"GL-07:{code}", CLIENT, f"{names[code]} of {_money(bal)}: what were they for?",
                                  f"Please tell us what these fees were for. {ask}", bal, rule="GL-07"))

    # AR-04: a customer in credit on the debtors list, or a supplier in debit on the creditors list
    try:
        from backend.app.services.ingestion.ageing_reports import outstanding_items, read_ageing_reports
        reports = read_ageing_reports(str(eng.id), ye, tb)
    except Exception:
        reports = {}
    for kind, who, side in (("AR", "customers", "in credit (owed money by the company)"),
                            ("AP", "suppliers", "in debit (owing money to the company)")):
        report = reports.get(kind)
        odd = [i for i in (outstanding_items(report) if report is not None else []) if i.amount <= -limits["listing"]]
        if odd:
            out.append(_query(f"AR-04:{kind}", CLIENT, f"{len(odd)} {who} {side} at the year end",
                              f"These {who} show the other way round on the aged list. Was it an overpayment, a "
                              f"payment on account, a credit note not yet used, or a payment put against the wrong "
                              f"invoice?", sum(i.amount for i in odd),
                              lines=[f"{i.contact}{' ' + i.number if i.number else ''}: {_money(i.amount)}" for i in odd],
                              rule="AR-04"))

    # YE-06: large amounts in the bank after the year end (a new loan, an asset sold, a big order): may need a note
    if ye is not None:
        found = [l for l in lines if l.when > ye and section.get(l.code) == BANK_SECTION
                 and abs(l.debit - l.credit) >= limits["large_one_off"]]
        if found:
            out.append(_query("YE-06", ACCOUNTANT, "Large amounts after the year end",
                              "Check whether any of these is an event after the year end to note or adjust for (a new "
                              "loan, an asset bought or sold, a large customer lost or a dispute settled).",
                              sum(abs(l.debit - l.credit) for l in found), lines=[_line_text(l) for l in found],
                              rule="YE-06"))

    # BK-16: lines dated before the company was formed (costs before incorporation, or a statement from before)
    formed_text = _companies_house(profile).get("incorporated")
    try:
        formed = date.fromisoformat(formed_text) if formed_text else None
    except ValueError:
        formed = None
    if formed is not None:
        found = [l for l in lines if l.when < formed and l.debit + l.credit > 0]
        if found:
            out.append(_query("BK-16", ACCOUNTANT, f"Lines dated before the company was formed ({formed:%d %B %Y})",
                              "Costs paid before the company existed can be claimed as if paid on the first day of "
                              "trading, if they are the company's; anything else is the director's own.",
                              sum(abs(l.debit - l.credit) for l in found), lines=[_line_text(l) for l in found],
                              rule="BK-16"))

    first = bool(incorporated_in_year(eng, profile)) or first_year(profile)
    # SQ-01: the company's first period
    if first:
        # The formation cost the preparers ask about when it is not in the books
        formation = any(FORMATION.search(f"{l.account} {l.description or ''}") for l in lines)
        out.append(_query("SQ-01", CLIENT, "First accounting period",
                          "This looks like the company's first period. Please confirm the date the company started "
                          "trading, and send details of any costs paid before then (by the company or by you "
                          "personally) for setting up the business, including costs you paid before the company "
                          "was formed (pre-incorporation expenses), with the receipts."
                          + ("" if formation else " We could not see the cost of forming the company (the Companies "
                                                  "House fee or the formation agent's invoice): was it paid "
                                                  "personally, and how much was it?"), round_=1, rule="SQ-01"))

    # SQ-03, SQ-04: asked on every job
    out.append(_query("SQ-03", CLIENT, "Business expenses paid personally",
                      "Did you pay for anything for the business from your own money in the year (your own card, "
                      "cash or personal account)? If so, please list each one with the date and amount, and send "
                      "the receipts.", rule="SQ-03"))
    out.append(_query("SQ-04", CLIENT, "Income not banked or received in advance",
                      "Was any of the company's income received in cash and not paid into the bank, or paid to you "
                      "personally? And was any money received before the year end for work done after it "
                      "(deposits or payments in advance)? If so, please give the amounts.", rule="SQ-04"))

    # SQ-05: share capital in the books with no money for it seen (first year, or shares issued this year)
    share_codes = {c for c, s in section.items() if s == SHARE_SECTION}
    capital = -sum(balances.get(c, 0.0) for c in share_codes)
    issued_now = any(l.code in share_codes and l.credit > 0 for l in lines)
    if capital >= 0.005 and (first or issued_now) and abs(balances.get(CALLED_UP_NOT_PAID, 0.0)) < 0.005:
        paid = any(section.get(l.code) == BANK_SECTION and l.debit > 0 and SHARES.search(l.description or "")
                   for l in lines)
        if not paid:
            out.append(_query("SQ-05", ACCOUNTANT, f"Share capital of {_money(capital)}: was it paid in?",
                              "No money for the shares can be seen in the bank. If the shareholders have not paid "
                              "for them, show it as called up share capital not paid (a debtor); if it was paid "
                              "another way, note how.", capital, rule="SQ-05"))

    # The rule sets in their own files, each on its own: one that fails is logged and left out, the others still run
    from backend.app.services.queries.frs102_rules import frs102_queries
    from backend.app.services.queries.loan_rules import loan_queries
    from backend.app.services.queries.payroll_rules import director_split_query, payroll_queries
    from backend.app.services.queries.tb_rules import tb_queries
    from backend.app.services.queries.last_year_rules import last_year_queries
    from backend.app.services.queries.vat_rules import open_item_vat_queries, vat_queries
    for name, run in (
            # VT-01: a VAT return of the year with no payment seen (queries/vat_rules.py)
            ("VAT", lambda: vat_queries(db, eng)),
            # VT-02: cash accounting, an open invoice / bill with no VAT (queries/vat_rules.py)
            ("VAT open items", lambda: open_item_vat_queries(eng, profile, tb, lines)),
            # LY-01: last year's Notes & Queries points for the client (queries/last_year_rules.py)
            ("last year's points", lambda: last_year_queries(eng, profile)),
            # PY-03 ... PY-09: the payroll report against the books (queries/payroll_rules.py)
            ("payroll", lambda: payroll_queries(db, eng, balances, lines)),
            # PY-11: directors' pay not split from the staff wages, no per-employee payroll (queries/payroll_rules.py)
            ("directors' pay", lambda: director_split_query(db, eng, balances)),
            # TB-01 ... DL-05: loans, the director's loan, dividends and donations (queries/loan_rules.py)
            ("loans", lambda: loan_queries(db, eng, tb, balances, lines)),
            # G-001 ... D-010: the FRS 102 rulebook's questions (queries/frs102_rules.py)
            ("FRS 102", lambda: frs102_queries(db, eng, profile, tb, balances, lines)),
            # C-03 ... DL-04: the TB and ledger rules the review and the Data check ask only in part (queries/tb_rules.py)
            ("TB and ledger", lambda: tb_queries(db, eng, profile, tb, balances, lines))):
        try:
            out += run()
        except Exception:
            logger.exception("Queries: the %s rules failed for engagement %s", name, eng.id)
            db.rollback()
    return out
