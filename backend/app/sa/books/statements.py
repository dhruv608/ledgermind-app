"""The bank statements read for a job: its accounts and period, own transfers, rent, and the people and employers
who pay money in."""

import hashlib
import json
import re
from datetime import date
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.sa.trade import HEADINGS
from backend.app.sa.books.rules import OUTSIDE, OWN_TRANSFER, platform_of


def key_of(on: Optional[str], description: str, money_in: float, money_out: float, balance: Optional[float]) -> str:
    raw = f"{on}|{description.strip().lower()}|{money_in:.2f}|{money_out:.2f}|{balance}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def label(heading: str) -> str:
    return HEADINGS[heading][0] if heading in HEADINGS else OUTSIDE.get(heading, heading)


def accounts(db: Session, job):
    """Each account's statements from every file, put together: [(account, bank, Account)]."""
    from backend.app.sa.extract.statement import PageRead, StatementLine, assemble
    from backend.app.sa.models import SADocument
    by_account: dict = {}
    names: dict = {}
    seen: set = set()
    docs = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "BANK_STATEMENT",
                                       SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id).all()
    fields = {d.id: json.loads(d.fields) if d.fields else {} for d in docs}
    platforms = {d.id: platform_of(d.filename, fields[d.id].get("bank")) for d in docs}
    copies = platform_copies(docs, fields, platforms)
    for d in docs:
        if d.id in copies:
            continue
        f = fields[d.id]
        platform = platforms[d.id]
        # A platform's report is its own account (not the card or bank number it may print)
        acct = f"{platform} report" if platform else (f.get("account_last4") or f"file {d.id}")
        names.setdefault(acct, f.get("bank"))
        for p in f.get("pages") or []:
            lines = [StatementLine(on, desc, i, o, bal, p["page"]) for on, desc, i, o, bal in p.get("lines") or []]
            for l in lines:
                l.platform = platform
                l.currency = f.get("currency") if f.get("currency") not in (None, "GBP") else None
            # The same page in another file (a report saved twice under two names, no account number to put the two
            # together by): every line the same is a copy, counted once
            same = tuple((l.on, round(l.money_in or 0, 2), round(l.money_out or 0, 2), (l.description or "").strip().lower())
                         for l in lines)
            if len(lines) >= 2 and same in seen:
                continue
            seen.add(same)
            # A page with no balance printed anywhere is not a bank page (the client's own sheet or a list of
            # payments sent with the statements): its lines are kept only where the bank does not show them
            if lines and p.get("bf") is None and p.get("cf") is None and all(l.balance is None for l in lines):
                for l in lines:
                    l.no_balance = True
            by_account.setdefault(acct, []).append((d.id, PageRead(p["page"], lines, p.get("bf"), p.get("cf"),
                                                                   chains=p.get("chains", True))))
    return [(acct, names.get(acct), assemble(reads)) for acct, reads in by_account.items()]


def platform_copies(docs, fields: dict, platforms: dict) -> set:
    """A platform's month sent twice in two layouts (eBay's detailed and summary statements): the report with more lines
    (every sale gross, each fee a cost) is kept; another of the same platform and month whose dates all fall inside the
    kept one's is the same money again. Weekly statements of one month do not overlap, so all are kept."""
    from collections import Counter
    spans: dict = {}
    for d in docs:
        if not platforms[d.id]:
            continue
        dates = sorted(l[0] for p in fields[d.id].get("pages") or [] for l in p.get("lines") or [] if l[0])
        if not dates:
            continue
        month = Counter(x[:7] for x in dates).most_common(1)[0][0]
        inside = [x for x in dates if x[:7] == month]
        spans.setdefault((platforms[d.id], month), []).append((len(dates), inside[0], inside[-1], d.id))
    copies = set()
    for group in spans.values():
        kept = []
        for n, lo, hi, doc_id in sorted(group, reverse=True):
            if any(klo <= lo and hi <= khi for klo, khi in kept):
                copies.add(doc_id)
            else:
                kept.append((lo, hi))
    return copies


def period(job, biz) -> Tuple[str, str]:
    """The business's accounting period, else the tax year."""
    from backend.app.sa.income import tax_year_dates
    start, end = (x.isoformat() for x in tax_year_dates(job.tax_year))
    if biz is not None:
        start, end = biz.period_start or start, biz.period_end or end
    return start, end


def payee_word(description: str) -> str:
    """A payee by its first word of four letters or more ('SCREWFIX DIRECT' and 'SCREWFIX DIR LTD' are one payee)."""
    from backend.app.services.bank_only.books import payee_key
    words = [w for w in re.findall(r"[a-z]+", payee_key(description)) if len(w) >= 4]
    return words[0] if words else ""


PAIR_MIN = 500.0                # from this amount a shared word pairs two lines; under it the bank must say transfer
PAIR_DAYS = 2
PAIR_COMMON = {"via", "online", "transaction", "transfer", "payment", "faster", "automated", "credit", "debit", "bill",
               "card", "the", "and", "ltd", "limited", "ref", "from", "to"}


def own_transfer_pairs(lines, keep) -> set:
    """Money out of one of the person's accounts and the same amount into another of them within two days, the two
    lines sharing a distinctive word or saying transfer ('NORTH SHOP AB VIA' out, 'SOUTH SHOP AB VIA' in):
    one transfer between their own accounts, not a cost and takings. Returns the ids of the paired bank lines."""
    words = lambda t: {w for w in re.findall(r"[a-z0-9]{2,}", (t or "").lower()) if w not in PAIR_COMMON and not w.isdigit()}
    # Transfers must pair whatever the amount; a small amount is common, so under PAIR_MIN the
    # two lines must say transfer, a shared word alone is not enough
    outs = [s.line for s in lines if s.line.money_out > 0]
    ins = [s.line for s in lines if s.line.money_in > 0]
    used, paired = set(), set()
    for o in outs:
        for i in ins:
            if id(i) in used or keep[id(i)][0] == keep[id(o)][0]:
                continue
            if abs(i.money_in - o.money_out) > 0.005 or abs((i.when - o.when).days) > PAIR_DAYS:
                continue
            said = (OWN_TRANSFER.search(f"{o.description} {i.description}")
                    or re.search(r"\btransfer\b|\btfr\b", f"{o.description} {i.description}", re.I))
            if said or o.money_out >= PAIR_MIN and words(o.description) & words(i.description):
                used.add(id(i))
                paired |= {id(i), id(o)}
                break
    return paired


def lets_property(db: Session, job) -> bool:
    """The person lets property too (a property on the return, or a letting agent's statement sent)."""
    from backend.app.sa.models import SADocument, SAProperty
    return bool(db.query(SAProperty.id).filter(SAProperty.job_id == job.id).first()
                or db.query(SADocument.id).filter(SADocument.job_id == job.id, SADocument.kind == "LETTING_STATEMENT").first())


# A payment from a person, not a company ('MISS J SMITH', 'BACS Jane Smith'; not 'AB DEVELOPMENTS LT')
PERSON_TITLE = re.compile(r"^\W*(?:(?:bacs|bgc|fp|fpi|faster payment|credit)\s+)?(mr|mrs|miss|ms|mstr|dr)\b", re.I)
COMPANY_WORDS = {"ltd", "lt", "limited", "plc", "llp", "inc", "co", "company", "services", "service", "group", "uk",
                 "trading", "developments", "solutions", "holdings", "council", "bank", "building", "society", "insurance",
                 "properties", "property", "partners", "associates", "enterprises", "international", "the", "and",
                 "hmrc", "dwp", "paypal", "ebay", "amazon", "stripe", "sumup", "square", "interest", "refund", "transfer",
                 "card", "payment", "payments", "pos", "cash", "deposit", "cheque", "chq", "giro", "tfr", "salary", "wages",
                 "pay", "tesco", "sainsbury", "asda", "shop", "store", "online", "ref", "invoice", "inv"}


def from_a_person(description: str) -> bool:
    if PERSON_TITLE.search(description or ""):
        return True
    words = [w for w in re.findall(r"[A-Za-z]+", description or "") if w.lower() not in ("bacs", "bgc", "fp", "fpi", "credit")]
    return 2 <= len(words) <= 4 and not {w.lower() for w in words} & COMPANY_WORDS and not re.search(r"\d{4,}", description or "")


def remittances(db: Session, job) -> List[Tuple[date, float]]:
    """What the letting agents paid over to the landlord (the statements' lines that are neither rent nor a cost), by date."""
    from backend.app.sa.models import SADocument
    out = []
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "LETTING_STATEMENT",
                                         SADocument.status.in_(("READ", "CHECK"))):
        f = json.loads(d.fields) if d.fields else {}
        for p in f.get("properties") or []:
            lines = p.get("lines") or []
            paid = [l for l in lines if l.get("heading") == "NOT_INCOME" and l.get("on") and l.get("amount")]
            if not paid:
                # No 'paid to landlord' line: what was paid over is the statement's rent less its costs
                rent = sum(float(l["amount"]) for l in lines if l.get("heading") == "RENT")
                costs = sum(float(l["amount"]) for l in lines if l.get("heading") not in ("RENT", "NOT_INCOME"))
                when = next((l.get("on") for l in lines if l.get("heading") == "RENT" and l.get("on")), f.get("period_to"))
                if rent and when:
                    paid = [{"on": when, "amount": round(rent - costs, 2)}]
            for l in paid:
                try:
                    out.append((date.fromisoformat(l["on"]), float(l["amount"])))
                except ValueError:
                    pass
    return out


def employers(db: Session, job) -> List[str]:
    """The person's employers, from every P60, P45 and payslip in the folder (any year) and the employment lines: the
    words that name them ('GB11-Acme Widgets Limited' gives acme, widgets)."""
    from backend.app.sa.models import SADocument, SALine
    names = [l.label for l in db.query(SALine).filter(SALine.job_id == job.id, SALine.source == "EMPLOYMENT")]
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind.in_(("P60", "P45", "PAYSLIP")),
                                         SADocument.fields.isnot(None)):
        names.append(json.loads(d.fields).get("employer") or "")
    return [n for n in names if n]


def employer_in(description: str, emp_words: List[set]) -> bool:
    """The employer's main name word, cut short or run into a reference as banks print it ('123456789HARRINGT' for
    Harrington Foods Limited): its first 7 letters anywhere in the line's letters."""
    letters = re.sub(r"[^a-z]", "", (description or "").lower())
    common = {"stores", "retail", "health", "trading", "foods", "motors", "systems", "solutions", "industries", "council",
              "hospital", "university", "school", "college", "international", "national", "british", "england"}
    return any(len(w) >= 6 and w not in common and w[:7] in letters for words in emp_words for w in words)


def _employer_words(names: List[str]) -> List[set]:
    noise = {"limited", "ltd", "plc", "llp", "the", "and", "group", "services", "company", "uk", "holdings"}
    return [w for w in (set(re.findall(r"[a-z]{3,}", n.lower())) - noise for n in names) if w]


# An agent's statement to the person (an actor's or a performer's agent): the fees in full, less the agent's commission
# ('Less commission due to Star Management @ 15% + VAT'). Its payments into the bank are then the same money, net
AGENT_COMMISSION = re.compile(r"commission (?:due |payable )?to ([A-Za-z][A-Za-z&' ]{2,60}?)(?: @| at |\s*\d|\s*$)", re.I)
AGENT_COMMON = {"management", "limited", "agency", "agents", "artists", "talent", "group", "associates"}


def _agent_words(accts) -> set:
    """The distinctive words of the agents whose statements are in the folder (a 'statement' with no account number)."""
    out: set = set()
    for acct, _bank, a in accts:
        if not str(acct).startswith("file "):
            continue
        for l in a.lines:
            m = AGENT_COMMISSION.search(l.description or "") if l.money_out else None
            if m:
                out |= set(re.findall(r"[a-z]{4,}", m.group(1).lower())) - AGENT_COMMON
    return out
