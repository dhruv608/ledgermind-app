"""
Related party transactions (P&L and balance sheet):
  - the related party list: the directors on the setup screen (typed, or brought in from Companies House with the
    shareholders over 25%), first name, surname, full name, role, related company names;
  - P&L lines whose contact / description name a related party (full name, or surname with low confidence);
  - balance sheet lines the same way, and every line of a director's loan / director's account (each DLA line listed);
  - a fixed asset line naming a related party (valuation and disclosure);
  - repeated P&L costs with a related party but no loan or payable with them (expenses masking a loan);
  - report: date, amount, account, P&L or balance sheet, contact, matched name, match source.
Bank lines are left out: the other side of the same payment is reported.
Salary and pension paid to directors are left out (payroll covers them). Report only: nothing is reclassified.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, GLTransaction, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, account_name_keys

DLA_CODES = {5400, 5800}
MIN_SURNAME = 3
PAYROLL_WORDS = re.compile(r"salar|wages|pension|bonus|\bnic?\b|national insurance|\bpaye\b|payroll", re.I)
DIRECTOR_ACCOUNT = re.compile(r"director", re.I)
LEGAL_WORDS = re.compile(r"\b(ltd|limited|plc|llp|uk|group|holdings?|the|and|co)\b|[^a-z0-9 ]")
COMPANY_WORDS = re.compile(r"\b(ltd|limited|plc|llp|holdings?|group|company|co)\b", re.I)

FLAG_PL = "Profit & loss expense involves a related party. Review classification and disclosure."
FLAG_BS = "Balance sheet balance involves a related party. Review for correct classification and overstatement risk."
FLAG_FA = "Fixed asset involves a related party. Review valuation and disclosure."
FLAG_LOAN = ("Repeated profit & loss costs with a related party and no loan or payable balance with them: "
             "expenses may be masking a loan or drawings.")
REPEATED_COSTS = 3


@dataclass
class Party:
    name: str
    role: str
    source: str                       # "Companies House" or "Manual list"
    kind: str = "person"              # person / company
    first: str = ""
    surname: str = ""
    aliases: List[str] = field(default_factory=list)   # other names on the register for the same person


@dataclass
class RelatedLine:
    when: date
    amount: float                     # debit positive
    account: str
    side: str                         # "P&L" / "Balance sheet"
    contact: str
    description: str
    party: str
    match: str                        # "Full name" / "Surname only (low confidence)" / "Company name" / "Director's account"
    source: str
    message: str


@dataclass
class PartySummary:
    party: Party
    lines: List[RelatedLine] = field(default_factory=list)

    @property
    def pl(self) -> List[RelatedLine]:
        return [l for l in self.lines if l.side == "P&L"]

    @property
    def bs(self) -> List[RelatedLine]:
        return [l for l in self.lines if l.side == "Balance sheet"]


def _words(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()) + " "


def related_parties(engagement: ClientEngagement) -> List[Party]:
    """The related party master list from the client setup."""
    profile = getattr(engagement, "profile", None)
    if profile is None:
        return []
    register = json.loads(profile.companies_house or "{}") if getattr(profile, "companies_house", None) else {}
    from_register = {p["name"].lower(): p for p in register.get("people", [])}
    # The Directors box is the master list (the accountant approves it); Companies House only says who is who
    names = list(dict.fromkeys(json.loads(profile.directors or "[]")))
    parties = []
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        reg = from_register.get(name.lower())
        kind = reg.get("kind", "person") if reg else "person"
        words = [w for w in re.split(r"\s+", name) if w]
        parties.append(Party(
            name=name,
            role=", ".join(reg["roles"]) if reg else "Director",
            source="Companies House" if reg else "Manual list",
            kind=kind,
            first=words[0] if kind == "person" and words else "",
            surname=words[-1] if kind == "person" and len(words) > 1 else "",
            aliases=list((reg or {}).get("also_listed_as", [])),
        ))
    # The other shareholders and the companies the directors own or control, from the client details
    # (FRS 102 s33.2): searched the same way
    setup = json.loads(profile.setup or "{}") if getattr(profile, "setup", None) else {}
    people = setup.get("people") or {}
    known = {p.name.lower() for p in parties}
    for holder in people.get("shareholders") or []:
        name = ((holder.get("name") if isinstance(holder, dict) else holder) or "").strip()
        if not name or name.lower() in known:
            continue
        known.add(name.lower())
        is_company = bool(COMPANY_WORDS.search(name))
        words = [w for w in re.split(r"\s+", name) if w]
        parties.append(Party(name=name, role="Shareholder", source="Client details",
                             kind="company" if is_company else "person",
                             first=words[0] if not is_company and words else "",
                             surname=words[-1] if not is_company and len(words) > 1 else "", aliases=[]))
    for company in people.get("related_companies") or []:
        name = ((company.get("name") if isinstance(company, dict) else company) or "").strip()
        if not name or name.lower() in known:
            continue
        known.add(name.lower())
        parties.append(Party(name=name, role="Related company", source="Client details", kind="company",
                             first="", surname="", aliases=[]))
    return parties


def _match_any(party: Party, text: str) -> Optional[str]:
    """The party's own name first, then the other names the register lists for the same person."""
    found = _match(party, text)
    for alias in party.aliases:
        if found:
            break
        words = alias.split()
        found = _match(Party(name=alias, role=party.role, source=party.source, kind=party.kind, first=words[0],
                             surname=words[-1] if len(words) > 1 else ""), text)
    return found


def _match(party: Party, text: str) -> Optional[str]:
    """How a ledger text names this party (case-insensitive, whole words), or None."""
    hay = _words(text)
    if party.kind == "company":
        key = " ".join(LEGAL_WORDS.sub(" ", party.name.lower()).split())
        return "Company name" if key and f" {key} " in hay else None
    surname = _words(party.surname).split()
    has_surname = bool(surname) and all(f" {w} " in hay for w in surname)
    first = _words(party.first).strip()
    if first and has_surname and f" {first} " in hay:
        return "Full name"
    # 'J Smith-Jones', 'J. Smith': the initial right before the surname
    if first and surname and f" {first[0]} {surname[0]} " in hay:
        return "Initial and surname"
    if has_surname and len("".join(surname)) >= MIN_SURNAME:
        return "Surname only (low confidence)"
    return None


def related_party_review(engagement: ClientEngagement, tb_records: Iterable[TBRecord], db: Session) -> List[PartySummary]:
    parties = related_parties(engagement)
    if not parties:
        return []
    tb_records = list(tb_records)
    chart = ChartLookup(db)
    codes = ChartLookup.gl_account_codes(tb_records)
    summaries = {p.name: PartySummary(p) for p in parties}
    director_account_party = Party(name="Director's loan / director's account", role="Director", source="Account name")
    dla = PartySummary(director_account_party)

    for tx in db.execute(select(GLTransaction).where(GLTransaction.engagement_id == str(engagement.id))
                         .order_by(GLTransaction.transaction_date)).scalars():
        account = tx.raw_account_name or ""
        code = next((codes[k] for k in account_name_keys(account) if k in codes), None)
        if code is None or tx.transaction_date is None:
            continue
        amount = round(float(tx.debit_amount or 0) - float(tx.credit_amount or 0), 2)
        if abs(amount) < 0.005:
            continue
        # Salary and pension to directors: payroll covers them
        if PAYROLL_WORDS.search(chart.name(code)) or PAYROLL_WORDS.search(account):
            continue
        side = "P&L" if chart.is_pl(code) else "Balance sheet"
        section = (chart.section(code) or "").lower()
        # The bank side of a payment is the same transaction again
        if "cash at bank" in section:
            continue
        message = FLAG_PL if side == "P&L" else FLAG_FA if "fixed asset" in section or "tangible" in section else FLAG_BS
        contact, description = (tx.reference or "").strip(), (tx.description or "").strip()

        hit = False
        for p in parties:
            how = _match_any(p, f"{contact} | {description}") or (_match_any(p, account) if side == "Balance sheet" else None)
            if how:
                summaries[p.name].lines.append(RelatedLine(tx.transaction_date, amount, account, side, contact, description,
                                                           p.name, how, p.source, message))
                hit = True
                break
        # Every line of a director's loan account / account named after a director: each line listed
        if not hit and (code in DLA_CODES or (side == "Balance sheet" and DIRECTOR_ACCOUNT.search(account))):
            dla.lines.append(RelatedLine(tx.transaction_date, amount, account, side, contact, description,
                                         "Director's account", "Director's account", "Account name", FLAG_BS))

    result = [s for s in summaries.values() if s.lines]
    if dla.lines:
        result.append(dla)
    return result


# Loans and HP (5100-5199, 5500-5599): a lender who is a person may be a close family member of a director
# (FRS 102 s33): asked, when not on the related party list already (a loan from a person can sit in bank loans)
LOAN_CODES = set(range(5100, 5200)) | set(range(5500, 5600))
# A name word: 'Smith', 'McNeil', 'MacDonald', "O'Brien", 'Smith-Jones'
_NAME_WORD = r"(?:Mc|Mac|O')?[A-Z][a-z]+(?:-[A-Z][a-z]+)?"
PERSON_NAME = re.compile(rf"(?:(?:mr|mrs|ms|miss|dr)\.?\s+)?{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,2}}")
LENDER_WORDS = re.compile(r"\b(bank|banking|loans?|finance|financial|capital|credit|funding|fund|lending|leasing|"
                          r"mortgage|building society|hmrc|council|government|recovery|bounce|transfer|payment|"
                          r"repayment|interest|ltd|limited|plc|llp|group|holdings?|services?|inc|llc|corp|gmbh|kft|bv|"
                          r"sarl|sas|srl|customers?|express|solicitors?|accountants?)\b", re.I)


def person_lenders(engagement: ClientEngagement, tb_records: Iterable[TBRecord], db: Session) -> List[dict]:
    """The people the company's loan accounts name as lenders (the payee on the loan's ledger lines, or the loan
    account's own name), with the accounts, the money lent and repaid; those on the related party list are left out
    (their lines are on G3.2)."""
    from backend.app.services.workbook.balance_tabs import LOAN_NAME, NOT_A_LOAN
    tb_records = list(tb_records)
    codes = ChartLookup.gl_account_codes(tb_records)
    parties = related_parties(engagement)
    found: dict = {}
    for tx in db.execute(select(GLTransaction).where(GLTransaction.engagement_id == str(engagement.id))
                         .order_by(GLTransaction.transaction_date)).scalars():
        account = tx.raw_account_name or ""
        code = next((codes[k] for k in account_name_keys(account) if k in codes), None)
        # A loan account repaid in the year is not in the TB (nil at the year end): known by its name
        if code not in LOAN_CODES and not (code is None and LOAN_NAME.search(account) and not NOT_A_LOAN.search(account)):
            continue
        # The lender named by the line's payee, or by the loan account itself ('Investor Loan - John Smith')
        candidates = [(tx.description or "").split(" - ")[0].strip()] + [p.strip() for p in account.split(" - ")[1:]]
        payee = next((c for c in candidates if PERSON_NAME.fullmatch(c) and not LENDER_WORDS.search(c)), None)
        if payee is None:
            continue
        if any(_match_any(p, payee) in ("Full name", "Initial and surname", "Company name") for p in parties):
            continue
        key = " ".join(payee.lower().split())
        row = found.setdefault(key, {"name": payee, "accounts": {}, "lent": 0.0, "repaid": 0.0, "lines": 0})
        row["accounts"][account] = code or 0
        row["lent"] = round(row["lent"] + float(tx.credit_amount or 0), 2)
        row["repaid"] = round(row["repaid"] + float(tx.debit_amount or 0), 2)
        row["lines"] += 1
    return list(found.values())


def masking_loans(summaries: List[PartySummary]) -> List[PartySummary]:
    """Several P&L costs with a related party and nothing on the balance sheet with them (expenses masking a loan)."""
    # Per party: a director's own loan account covers that director only, not a related company
    has_dla = any(s.party.source == "Account name" for s in summaries)
    return [s for s in summaries if s.party.source != "Account name" and len([l for l in s.pl if l.amount > 0]) >= REPEATED_COSTS
            and not s.bs and not (has_dla and s.party.kind == "person" and s.party.role != "Shareholder")]
