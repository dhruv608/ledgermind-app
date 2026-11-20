"""
Raw data route: the Books tab. Works the client's books out from its uploaded files (steps 1-5) with the accountant's
choices on top, gives the screen its lists, and writes the trial balance and ledger the rest of the app reads (the same
records a Xero/QuickBooks upload makes), so Accounts, Review, Journals and Workbook run on it unchanged.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.core.s3 import s3_service
from backend.app.models.database import ClientEngagement, GLTransaction, MasterCOA, TBRecord
from backend.app.models.raw_books import RawBooksChoice
from backend.app.services.bank_only.bank_sort import CUSTOMER, HEAD_CODES, SUPPLIER, TRANSFER, TRANSFERS, UNSORTED, \
    CHANNEL_WORDS, UNKNOWN_ACCOUNT_HOW, sort_bank
from backend.app.services.bank_only.bills_match import BillsMatch, match_bills
from backend.app.services.bank_only.categories import materials_code, no_bill_code
from backend.app.services.bank_only.input_files import BANK_CODES, CARD_CODE, RawInput, read_input_files
from backend.app.services.bank_only.ledger import CREDITORS, DEBTORS, EXCHANGE, NAMES, SUSPENSE, VAT, build_ledger
from backend.app.services.bank_only.sales_match import CLEAR, SalesMatch, match_sales

SOURCE_SYSTEM = "BANK_DEXT"          # ClientEngagement.source_system for a client with no accounting software
ROLES_FILE = "_roles.json"

# What the accountant can pick for a bank line or bill (head -> firm code from HEAD_CODES)
CHOICES = ["Sales (no invoice)", "Purchases (no bill)", "Vehicle running costs", "Insurance", "Subscriptions",
           "Accountancy fees", "Computer software", "Telephone and internet", "Bank charges", "Donations",
           "Director's loan", "Corporation tax paid", "VAT paid", "PAYE and NI paid", "Net wages",
           "Bank interest received", "Transfer between own accounts", "Ask the client"]


def is_books_client(engagement: ClientEngagement) -> bool:
    return (engagement.source_system or "").upper() == SOURCE_SYSTEM


def client_files(engagement_id: str) -> Tuple[List[Tuple[str, bytes]], Dict[str, str]]:
    """The client's uploaded files and what each was taken as at upload."""
    files, roles = [], {}
    for name, data in s3_service.list_files(f"raw_uploads/{engagement_id}/"):
        if name == ROLES_FILE:
            try:
                roles = json.loads(data.decode())
            except ValueError:
                roles = {}
        elif name.lower().endswith((".xlsx", ".xlsm", ".csv")):
            files.append((name, data))
    return files, roles


# Bank wording that is not the payee's name: 'CARD PAYMENT TO TESCO MOBILE ON 12/03' -> 'tesco mobile'
_NOT_NAME = set("""card payment payments purchase debit credit dd direct so standing order fp faster bacs bgc chaps tfr
transfer to from ref reference pos contactless gbp on at via visa mastercard mc online bill paid receipt received
cash withdrawal atm fee charge mobile-pay apple google pay ltd limited the and of for uk co www com
internet banking line online automated transaction channel faster bill thank you giro counter returned
charges account sort code""".split())


RECEIPT_FROM = re.compile(r"\breceipt\s+ref\b.*?\bfrom\s+(.+)$")


def payee_key(description: str) -> str:
    """The payee's name in a bank line, for one head for all its lines ('' when the line has no name in it). A
    transfer that names only an account ('Internet Banking Transfer to Account 03976025') is that account."""
    # Whole words only: a reference with digits in it ('AB12CD', '123456') is not part of the name
    text = CHANNEL_WORDS.sub(" ", (description or "").lower())
    # A receipt that quotes its reference first ('FASTER PAYMENTS RECEIPT REF.ELECTRICAL WORK FROM John Smith'):
    # the payer is the name after 'from', not the reference (a sole trader's 'electrical work' is not a supplier)
    if (payer := RECEIPT_FROM.search(text)):
        text = payer.group(1)
    words = re.split(r"[\s*/,.:;#()\-]+", text)
    name = [w for w in words if re.fullmatch(r"[a-z][a-z&']+", w) and w not in _NOT_NAME and len(w) > 2]
    if not name and (acc := re.search(r"\baccount\s+(?:no\.?\s*)?(\d{6,8})\b", text)):
        return f"account {acc.group(1)}"
    return " ".join(name[:3])


def _last_year_payees(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    """Heads chosen for a payee in last year's job in the app: used again this year (until changed)."""
    from backend.app.services.review.last_year import last_year_job
    last = last_year_job(engagement, db)
    if last is None:
        return {}
    return {k: v for k, v in _choices(db, last.id).items() if k.startswith("payee:")}


# A payee whose lines last year were nearly all on one code, in last year's finished ledger (whatever made it: the
# rules, the accountant's choices, or Xero / QuickBooks): that code again this year, for lines no rule sorts (a
# rule's head stays: cash taken out at Asda was the director's, the shopping there is still stock)
MEMORY_LINES, MEMORY_SHARE = 2, 0.8
# The other side of a payment, not what it was for
NOT_REMEMBERED = {DEBTORS, CREDITORS, VAT, SUSPENSE, TRANSFERS, EXCHANGE, CARD_CODE, *BANK_CODES}
# A bank-only job's ledger writes the head before the bank's words ('Telephone and internet: VODAFONE ...')
HEAD_PREFIX = re.compile(r"^[^:]{2,60}:\s+")


def _last_year_ledger(engagement: ClientEngagement, db: Session) -> Dict[str, int]:
    """payee -> code from last year's job in the app."""
    from collections import Counter
    from backend.app.services.review.last_year import last_year_job
    from backend.app.services.sop.common import gl_lines
    last = last_year_job(engagement, db)
    if last is None:
        return {}
    tb = db.query(TBRecord).filter(TBRecord.engagement_id == last.id).all()
    seen: Dict[str, Counter] = {}
    for line in gl_lines(last.id, tb, db):
        if line.code in NOT_REMEMBERED:
            continue
        desc = HEAD_PREFIX.sub("", line.description, count=1) if line.source.startswith("bank row")             else line.description
        key = payee_key(desc)
        if key:
            seen.setdefault(key, Counter())[line.code] += 1
    out: Dict[str, int] = {}
    for key, c in seen.items():
        code, n = c.most_common(1)[0]
        if n >= MEMORY_LINES and n / sum(c.values()) >= MEMORY_SHARE:
            out[key] = code
    return out


# The firm's other clients: a payee this many of them gave one head on the Books tab ('every line of this payee'),
# none another, is that head for a new client's unsorted lines (a national supplier's name)
FIRM_CLIENTS = 2


def _firm_payees(engagement: ClientEngagement, db: Session) -> Dict[str, Dict[str, Any]]:
    """payee -> the choice the firm's other clients (not this company in another year) agree on."""
    from backend.app.services.ingestion.client_identity import company_key
    rows = db.query(ClientEngagement.client_name, RawBooksChoice.key, RawBooksChoice.value)         .join(ClientEngagement, ClientEngagement.id == RawBooksChoice.engagement_id)         .filter(RawBooksChoice.key.like("payee:%"), ClientEngagement.owner_user_id == engagement.owner_user_id).all()
    own = company_key(engagement.client_name)
    by: Dict[str, Dict[str, set]] = {}
    for client, key, value in rows:
        company = company_key(client)
        if company != own:
            by.setdefault(key[len("payee:"):], {}).setdefault(json.dumps(json.loads(value), sort_keys=True),
                                                             set()).add(company)
    return {name: json.loads(next(iter(heads))) for name, heads in by.items()
            if len(heads) == 1 and len(next(iter(heads.values()))) >= FIRM_CLIENTS}


def firm_chart(db: Session) -> Dict[int, str]:
    """Every code of the chart (code -> name), the firm's standard list and the rest of the full chart: what the
    accountant can pick for a line."""
    return {c.std_code: c.std_name for c in db.query(MasterCOA).all()}


def chart_for_picking(db: Session) -> List[Dict[str, Any]]:
    """The chart for the Books tab's picker: code, name, section, P&L or balance sheet, and whether the code is on the
    firm's standard list (the rest of the full chart comes after it)."""
    return [{"code": c.std_code, "name": c.std_name, "section": c.category or "",
             "pl": c.financial_class == "Profit and Loss", "extended": bool(c.is_extended)}
            for c in db.query(MasterCOA).order_by(MasterCOA.is_extended, MasterCOA.std_code).all()]


def resolve(choice: Optional[Dict[str, Any]], chart: Dict[int, str]) -> Optional[Tuple[str, int]]:
    """(head, code) of a choice: {"head": one of the common heads} or {"code": any code of the firm's chart}."""
    if not choice:
        return None
    code = choice.get("code")
    if code is not None:
        try:
            code = int(code)
        except (TypeError, ValueError):
            return None
        if code not in chart and code not in NAMES:
            return None
        # Shown with its code ("3290 Telecommunications and data costs"), never mistaken for a common head's name
        return f"{code:04d} {chart.get(code) or NAMES.get(code)}", code
    head = choice.get("head")
    return (head, HEAD_CODES[head]) if head in HEAD_CODES else None


def picked(choice: Optional[Dict[str, Any]]) -> str:
    """The dropdown value of a choice: "code:3290" or "head:Insurance" ("" when none)."""
    if not choice:
        return ""
    return f"code:{int(choice['code'])}" if choice.get("code") is not None else (f"head:{choice['head']}" if choice.get("head") else "")


def _choices(db: Session, engagement_id: str) -> Dict[str, Any]:
    return {c.key: json.loads(c.value) for c in db.query(RawBooksChoice).filter_by(engagement_id=engagement_id).all()}


def save_choice(db: Session, engagement_id: str, key: str, value: Any, user_id: Optional[int]) -> None:
    """value None removes the choice (back to what the app worked out)."""
    row = db.query(RawBooksChoice).filter_by(engagement_id=engagement_id, key=key).first()
    if value is None:
        if row:
            db.delete(row)
    elif row:
        row.value, row.user_id, row.updated_at = json.dumps(value), user_id, datetime.utcnow()
    else:
        db.add(RawBooksChoice(engagement_id=engagement_id, key=key, value=json.dumps(value), user_id=user_id))
    db.commit()


def clear_choices(db: Session, engagement_id: str) -> None:
    db.query(RawBooksChoice).filter_by(engagement_id=engagement_id).delete(synchronize_session=False)


def _directors(engagement: ClientEngagement) -> List[str]:
    try:
        return json.loads(engagement.profile.directors or "[]") if engagement.profile else []
    except ValueError:
        return []


def _company_to_confirm(engagement: ClientEngagement) -> Optional[str]:
    profile = engagement.profile
    if profile is None or profile.companies_house:
        return None
    choices = (json.loads(profile.detection_signals or "{}") or {}).get("ch_choices") or []
    return choices[0].get("company_name") if choices else None


def opening_key(name: str) -> str:
    return f"opening:{' '.join(name.lower().split())}"


def opening_coder(engagement: ClientEngagement, db: Session, choices: Optional[Dict[str, Any]] = None):
    """Codes for last year's TB lines that have only a name: the accountant's pick on the Books tab, else the mapping a
    trial balance gets (this client's code last year, the firm's habits and rules, the naming rules, then the AI,
    whose answers are kept for the client)."""
    choices = _choices(db, engagement.id) if choices is None else choices

    def code(lines: List[Tuple[str, float]]) -> Dict[str, Tuple[Optional[int], str, bool]]:
        chart = firm_chart(db)
        out: Dict[str, Tuple[Optional[int], str, bool]] = {}
        todo = []
        for name, amount in lines:
            chosen = resolve(choices.get(opening_key(name)), chart)
            if chosen:
                out[name] = (chosen[1], "chosen by the accountant", True)
            else:
                todo.append((name, amount))
        if todo:
            from backend.app.services.mapping.mapping_service import MappingService
            found = MappingService._map_rows([{"name": n, "account_type": None, "net": a} for n, a in todo],
                                             db, engagement.id)
            for (name, _), r in zip(todo, found):
                r = r or {}
                out[name] = (r.get("std_code"), r.get("mapping_reason") or "",
                             r.get("mapping_status") == "MATCHED" and float(r.get("confidence_score") or 0) >= 0.9)
        return out
    return code


def look_up_register(engagement: ClientEngagement, db: Session) -> None:
    """At upload, before the bank lines are sorted: the client on Companies House (its SIC codes, and the directors in
    the year, so lines paying them or their family go to the director's loan). A bank-only client has no setup yet;
    the accountant's own directors, or last year's, are kept, and nothing changes when the register cannot be asked."""
    from backend.app.services.setup import companies_house as ch
    from backend.app.services.setup.profile_service import ProfileService, confirmed_fields
    profile = ProfileService.get_or_create_profile(db, engagement.id)
    if profile.companies_house:
        return
    year_start = engagement.prior_period_end_date + timedelta(days=1) if engagement.prior_period_end_date else None
    try:
        found, choices = ch.find_client(engagement.client_name, engagement.period_end_date, year_start)
    except Exception:
        found, choices = None, []
    if not found:
        # No exact match ('Example Services Ltd' is registered as EXAMPLE SERVICES UK LIMITED): the closest
        # companies, for the accountant to confirm on the setup's People step ('Is this your company?')
        if choices:
            signals = json.loads(profile.detection_signals or "{}")
            signals["ch_choices"] = choices
            profile.detection_signals = json.dumps(signals)
            db.commit()
        return
    profile.companies_house = json.dumps(found)
    if "directors" not in confirmed_fields(profile) and not json.loads(profile.directors or "[]"):
        profile.directors = json.dumps([p["name"] for p in found.get("people", [])
                                        if set(ch.DIRECTOR_ROLES) & set(p.get("roles", [])) and p.get("kind") == "person"])
    db.commit()


# A food business by its name ('... Foods Ltd'): its supermarket shopping is stock
FOOD_NAME = re.compile(r"\bfoods?\b|kitchen|cuisine|cater", re.I)


def bank_industry(engagement: ClientEngagement) -> Tuple[Optional[str], str]:
    """(industry, where it was taken from) for sorting the bank lines: the accountant's, else the Companies House
    SIC codes, else the company name ('' when confirmed). A bank-only client is sorted before its setup is done, so
    the shops whose head follows the industry (a supermarket is stock for a food business) wait for none of it."""
    from backend.app.services.setup.companies_house import sic_industry
    from backend.app.services.setup.profile_service import NAME_INDUSTRY, confirmed_industry
    profile = engagement.profile
    if confirmed_industry(profile):
        return confirmed_industry(profile), ""
    register = json.loads(profile.companies_house or "{}") if profile is not None and profile.companies_house else {}
    by_sic = sic_industry(register)
    if by_sic and by_sic != "UNIV":
        return by_sic, f"Companies House SIC {', '.join(register.get('sic_codes', []))}"
    name = (engagement.client_name or "").lower()
    if FOOD_NAME.search(name):
        return "RES", "the company name"
    return next(((ind, "the company name") for pattern, ind in NAME_INDUSTRY if re.search(pattern, name)), (None, ""))


def work_out(engagement: ClientEngagement, db: Session):
    """Steps 1-5 on the client's files, with the accountant's choices."""
    files, roles = client_files(engagement.id)
    raw = read_input_files(files, roles, code_names=opening_coder(engagement, db), year_end=engagement.period_end_date)
    # Last year's job in the app knows last year's P&L (a closing TB often has none): the materials code from it
    from backend.app.services.review.last_year import last_year_job
    last = last_year_job(engagement, db)
    if last is not None:
        used: Dict[int, float] = {}
        for t in db.query(TBRecord).filter(TBRecord.engagement_id == last.id).all():
            if t.std_code is not None:
                used[t.std_code] = used.get(t.std_code, 0.0) + float(t.net_amount or 0.0)
        raw.materials_code, raw.no_bill_code = materials_code(used), no_bill_code(used, bank_only=raw.bank_only)
    choices = _choices(db, engagement.id)
    payroll = bool(engagement.profile.has_payroll) if engagement.profile else False
    industry, industry_from = bank_industry(engagement)
    from backend.app.services.setup.data_check import first_year, incorporated_in_year
    first = bool(incorporated_in_year(engagement, engagement.profile)) or first_year(engagement.profile)
    bank = sort_bank(raw, directors=_directors(engagement), payroll=payroll, industry=industry, first_period=first,
                     industry_from=industry_from)
    # One head for every line from a payee (this year's choice, else last year's), then the accountant's choice
    # on a line over both. A line paying a Dext bill, from a customer, or a paired transfer keeps its match.
    payees = {**_last_year_payees(engagement, db), **{k: v for k, v in choices.items() if k.startswith("payee:")}}
    chart = firm_chart(db)
    memory, firm = _last_year_ledger(engagement, db), _firm_payees(engagement, db)
    for s in bank.lines:
        chosen = resolve(choices.get(f"bank:{s.line.ref or s.line.row}"), chart)
        if chosen:
            (s.head, s.code), s.sure, s.how = chosen, True, "chosen by the accountant"
            s.bill, s.customer, s.pair = None, "", None
            continue
        name = payee_key(s.line.description)
        by_payee = resolve(payees.get(f"payee:{name}"), chart) if name else None
        if by_payee and s.bill is None and not s.customer and s.pair is None:
            this_year = f"payee:{name}" in choices
            (s.head, s.code), s.sure = by_payee, True
            s.how = f"chosen for every '{name}' line" + ("" if this_year else " (as last year)")
        elif name in memory and s.head == UNSORTED and s.bill is None and not s.customer and s.pair is None:
            got = resolve({"code": memory[name]}, chart)
            if got:
                (s.head, s.code), s.sure = got, False
                s.how = f"as last year: '{name}' lines went to {got[0]}"
        elif name in firm and s.head == UNSORTED and s.bill is None and not s.customer and s.pair is None:
            got = resolve(firm[name], chart)
            if got:
                (s.head, s.code), s.sure = got, False
                s.how = f"the firm's other clients put '{name}' lines to {got[0]}"
    # A payment from the bank coded to a card whose own statement is loaded: the card statement already records that
    # repayment, so coded to the card it counts twice. It is money moved between own accounts.
    card_codes = {a.code for a in raw.accounts if a.is_card}
    card_names = {a.name for a in raw.accounts if a.is_card}
    for s in bank.lines:
        if s.code in card_codes and s.line.account not in card_names:
            s.head, s.code = TRANSFER, TRANSFERS
            s.how = (f"{s.how}: a payment to the card, whose own statement is loaded, so a transfer between own accounts "
                     f"(coded to the card it would count twice)")
    sales = match_sales(raw.sales, bank, raw.opening_sales)
    bills = match_bills(raw.purchases, bank, raw.opening_bills)
    vat = bool(engagement.profile.is_vat_registered) if engagement.profile else False
    bill_heads = {int(k.split(":")[1]): r for k, v in choices.items()
                  if k.startswith("bill:") and (r := resolve(v, chart))}
    ledger = build_ledger(raw, bank, sales, bills, raw.opening_tb, vat_registered=vat, bill_heads=bill_heads)
    return raw, bank, sales, bills, ledger, choices


def _has_payroll(engagement: ClientEngagement, db: Session) -> bool:
    """A payroll report is uploaded for the job (its monthly figures, or the file itself)."""
    from sqlalchemy import select
    from backend.app.models.database import PayrollP32Record, SupplementaryDocument
    return bool(db.execute(select(PayrollP32Record.id).where(PayrollP32Record.engagement_id == engagement.id)).first()
                or db.execute(select(SupplementaryDocument.id).where(
                    SupplementaryDocument.engagement_id == engagement.id,
                    SupplementaryDocument.doc_type.in_(("PAYROLL_P32", "PAYROLL_FROM_GL")))).first())


def books(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    """Everything the Books tab shows."""
    from backend.app.services.queries.bank_rules import bank_queries
    from backend.app.services.queries.r1_rules import query_limits
    raw, bank, sales, bills, ledger, choices = work_out(engagement, db)
    receipt_of = {id(r.line): r for r in sales.receipts}
    payment_of = {id(p.line): p for p in bills.payments}

    bank_rows = []
    from backend.app.services.bank_only.ai_suggest import kept_suggestions
    ai_kept = kept_suggestions(str(engagement.id), db)
    for s in bank.lines:
        b = s.line
        key = f"bank:{b.ref or b.row}"
        rc, p = receipt_of.get(id(b)), payment_of.get(id(b))
        match = rc or p
        rules = match.rules if match else []
        probable = bool(match) and any(r not in CLEAR for r in rules) and match.allocated > 0.005
        confirmed = bool(choices.get(f"confirm:{key}"))
        open_part = match.unallocated if match else 0.0
        check = (not s.sure and s.head == UNSORTED) or (match is not None and open_part > 0.005) \
            or (s.head == TRANSFER and s.pair is None) or s.how.startswith(UNKNOWN_ACCOUNT_HOW) \
            or (probable and not confirmed) or (s.head in (CUSTOMER, SUPPLIER) and match is None)
        if key in choices:
            check = False
        what = s.how
        if match and match.allocated > 0.005:
            items = [(it.invoice.number or it.invoice.party, a) for it in (sales.items if rc else bills.items)
                     for l, a, _ in it.allocations if l is b]
            what = ("Pays " if p else "For ") + ", ".join(f"{n} £{a:,.2f}" for n, a in items[:4]) + \
                (f" (rule {'/'.join(rules)})" if rules else "")
        if match and open_part > 0.005:
            what += f"; £{open_part:,.2f} with no {'invoice' if rc else 'bill'}"
        bank_rows.append({
            "key": key, "row": b.row, "account": b.account, "date": b.when.isoformat(), "description": b.description,
            "money_in": b.money_in, "money_out": b.money_out, "head": s.head,
            "code": raw.no_bill_code if s.head == "Purchases (no bill)" else s.code,
            "why": what, "check": check, "chosen": key in choices, "probable": probable and not confirmed,
            "customer": (rc.customer if rc else "") or s.customer,
            # The head comes from a choice for all the payee's lines: made this year (can be undone here) or last year
            "payee": payee_key(b.description), "by_payee": s.how.startswith("chosen for every"),
            "picked": picked(choices.get(key)) or (picked(choices.get(f"payee:{payee_key(b.description)}"))
                                                   if s.how.startswith("chosen for every") else ""),
            "payee_this_year": s.how.startswith("chosen for every") and f"payee:{payee_key(b.description)}" in choices,
            # The AI's suggestion for a line no rule fits (asked with the Suggest button), shown, never applied
            "ai": ai_kept.get(payee_key(b.description)) if s.head == UNSORTED and key not in choices else None,
        })

    invoices = []
    for it in sales.items:
        invoices.append({
            "number": it.invoice.number, "date": it.invoice.when.isoformat(), "customer": it.invoice.party,
            "amount": it.invoice.gross, "paid": it.paid, "outstanding": it.outstanding, "status": it.status,
            "last_year": it.brought_forward,
            "paid_by": [{"date": l.when.isoformat(), "amount": a, "rule": r} for l, a, r in it.allocations],
        })
    bill_rows = []
    for it in bills.items:
        head, code = ledger.bill_heads.get(it.invoice.row, ("Last year's bill", 5200)) if not it.brought_forward \
            else ("Last year's bill", 5200)
        key = f"bill:{it.invoice.row}"
        bill_rows.append({
            "key": key, "row": it.invoice.row, "number": it.invoice.number, "date": it.invoice.when.isoformat(),
            "supplier": it.invoice.party, "amount": it.invoice.gross, "vat": it.invoice.vat, "paid": it.paid,
            "outstanding": it.outstanding, "status": it.status, "last_year": it.brought_forward,
            "head": head, "code": code, "check": code == SUSPENSE and key not in choices, "chosen": key in choices,
            "picked": picked(choices.get(key)),
            "paid_by": [{"date": l.when.isoformat(), "amount": a, "rule": r} for l, a, r in it.allocations],
        })

    questions = []
    for q in ledger.questions + _file_questions(raw) + _confirm_questions(sales, bills, choices) + STANDARD_QUESTIONS:
        answer = choices.get(f"answer:{q['key']}")
        questions.append({**q, "answer": (answer or {}).get("text", ""), "answered": bool(answer)})

    tb = ledger.trial_balance()
    closing_bank = raw.closing_bank
    bank_codes = sorted({a.code for a in raw.accounts} | {c for c in tb if c in BANK_CODES})
    checks = {
        "bank_books": round(sum(tb.get(c, 0.0) for c in bank_codes), 2), "bank_statement": closing_bank,
        # Each account: the books against its statement (the accounts together above); accounts on one code (two
        # cards on 5351) are agreed together
        "banks": [{"account": " + ".join(a.name for a in raw.accounts if a.code == code), "code": code,
                   "books": tb.get(code, 0.0),
                   "statement": (None if any(a.closing is None for a in raw.accounts if a.code == code)
                                 else round(sum(a.closing for a in raw.accounts if a.code == code), 2))}
                  for code in dict.fromkeys(a.code for a in raw.accounts)],
        "transfers": tb.get(TRANSFERS, 0.0),
        "debtors": sales.debtors(), "debtors_books": tb.get(4400, 0.0),
        "creditors": bills.creditors(), "creditors_books": -tb.get(5200, 0.0),
        "suspense": tb.get(SUSPENSE, 0.0), "out_of_balance": ledger.out_of_balance(),
        "questions_open": sum(1 for q in questions if not q["answered"]),
    }
    return {
        "client": raw.client_name, "year_end": raw.year_end.isoformat() if raw.year_end else None,
        "summary": {"bank_lines": len(bank_rows), "to_check": sum(r["check"] for r in bank_rows) +
                    sum(r["check"] for r in bill_rows), "debtors": sales.debtors(), "creditors": bills.creditors(),
                    "questions": len(questions)},
        "file_problems": [{"where": p.where, "severity": p.severity, "text": p.text} for p in raw.problems],
        # Last year's TB lines that had only a name: the code each was given, to check or change
        "opening": [{**line, "key": opening_key(line["name"]), "chosen": opening_key(line["name"]) in choices,
                     "picked": picked(choices.get(opening_key(line["name"]))) or f"code:{line['code']}"}
                    for line in raw.opening_lines],
        "bank": bank_rows, "customers": sales.customers(), "invoices": invoices, "bills": bill_rows,
        "questions": questions, "checks": checks, "choices": CHOICES,
        # The firm's bank query rules (BK-03 ... AS-02): for the Queries tab only
        "rule_queries": bank_queries(raw, bank, bills, query_limits(db), has_payroll=_has_payroll(engagement, db)),
        # Every code of the firm's chart, for picking any account for a line
        "chart": chart_for_picking(db),
        # Payments to the directors are only recognised once their names are on the Setup tab
        "directors_known": bool(_directors(engagement)),
        # No exact Companies House match at upload: the closest company, to confirm on the setup's People step
        "company_to_confirm": _company_to_confirm(engagement),
    }


# Asked of every client: the year-end entries the accountant makes for almost every company (mileage, use of home
# and the accountancy fee)
STANDARD_QUESTIONS = [
    {"key": "standard:mileage", "group": "documents",
     "text": "Please send your mileage log for the year (date, from, to, purpose and miles of each business journey "
             "made in your own car)."},
    {"key": "standard:use_of_home", "group": "confirm",
     "text": "Do you use your home for the business? If yes, please confirm the hours a month you work from home."},
    {"key": "standard:accountancy_fee", "group": "confirm",
     "text": "Please confirm the accountancy fee for this year's accounts."},
]


def _file_questions(raw: RawInput) -> List[Dict[str, str]]:
    """Problems in the client's own records that only the client can answer (invoice numbers used twice, gaps)."""
    out = []
    for n, p in enumerate(raw.problems):
        if p.where == "Sales" and ("used for two customers" in p.text or "missing from the sequence" in p.text):
            out.append({"key": f"file:{n}", "group": "explain", "text": p.text.replace(": ask the client", "")})
    return out


def _confirm_questions(sales: SalesMatch, bills: BillsMatch, choices: Dict[str, Any]) -> List[Dict[str, str]]:
    """A probable match (rules E and F) is confirmed with the client unless the accountant already confirmed it."""
    out = []
    for m, word in ((sales, "receipt"), (bills, "payment")):
        rows = m.receipts if word == "receipt" else m.payments
        for rc in rows:
            confirmed = choices.get(f"confirm:bank:{rc.line.ref or rc.line.row}")
            if rc.allocated <= 0.005 or all(r in CLEAR for r in rc.rules) or confirmed:
                continue
            items = [it for it in m.items for l, _, _ in it.allocations if l is rc.line]
            names = ", ".join(sorted({it.invoice.number or f"{it.invoice.when:%d/%m/%Y}" for it in items}))[:120]
            if word == "receipt":
                text = (f"Was the £{rc.amount:,.2f} from {rc.customer or 'the payer'} on {rc.line.when:%d %B %Y} "
                        f"for invoice{'s' if len(items) > 1 else ''} {names}?")
            else:
                text = f"Was the £{rc.amount:,.2f} paid on {rc.line.when:%d %B %Y} for the {rc.customer} bill(s) {names}?"
            out.append({"key": f"confirm:bank:{rc.line.ref or rc.line.row}", "group": "confirm", "text": text})
    return out


def make_trial_balance(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    """Write the books as the trial balance and ledger the rest of the app reads (replacing the previous ones)."""
    raw, _, _, _, ledger, _ = work_out(engagement, db)
    if ledger.out_of_balance():
        raise ValueError(f"The books do not balance (difference £{ledger.out_of_balance():,.2f})")
    chart = {c.std_code: c.std_name for c in db.query(MasterCOA).all()}

    accounts = {a.code: f"Bank - {a.name}" for a in raw.accounts} if len(raw.accounts) > 1 else {}

    def name(code: int) -> str:
        return accounts.get(code) or chart.get(code) or raw.opening_names.get(code) or NAMES.get(code) or f"Account {code}"

    def account(code: int) -> str:
        return f"{code:04d} {name(code)}"

    db.query(GLTransaction).filter(GLTransaction.engagement_id == engagement.id).delete(synchronize_session=False)
    db.query(TBRecord).filter(TBRecord.engagement_id == engagement.id).delete(synchronize_session=False)
    opening = raw.opening_tb
    for code, net in ledger.trial_balance().items():
        db.add(TBRecord(
            engagement_id=engagement.id, raw_account_name=account(code), std_code=code, std_name=name(code),
            debit_amount=max(net, 0.0), credit_amount=max(-net, 0.0), net_amount=net,
            opening_amount=opening.get(code, 0.0) if opening else None,
            mapping_status="MATCHED", confidence_score=1.0, match_source="BOOKS",
            mapping_reason="From the books prepared in the app (bank statement and Dext).",
        ))
    for e in ledger.entries:
        if e.source == "opening":
            continue
        db.add(GLTransaction(
            engagement_id=engagement.id, raw_account_name=account(e.code), transaction_date=e.when,
            description=e.narrative[:500], reference=e.source[:255], source="Books",
            debit_amount=e.debit, credit_amount=e.credit, net_amount=round(e.debit - e.credit, 2),
        ))
    db.commit()
    return {"accounts": len(ledger.trial_balance()), "entries": len(ledger.entries)}
