"""
Rental property / property trading recognition checks.
Each property is classified first (by the accountant on the setup screen, one row per property):
  RENTAL   held to earn rent: the property is a fixed asset
  TRADING  bought / developed to sell: the property is stock (inventory / WIP)
A ledger line belongs to a property by its tag (QuickBooks class / location, Xero tracking), else by the
property's name or words in the account or description ('Residential Property:Rent receivables'). With a
single property, every property-type line (rent, mortgage, landlord, service charge...) is that property's.

  A1  rental: improvement costs (renovation, fit-out, structural...) expensed before the rent started
  A2  rental: running costs (repairs, utilities, insurance, cleaning, agents) before the rent started
  A3  rental: large improvement costs expensed after the rent started
  B1  trading: acquisition / development costs (land, construction, architect, legal, stamp duty) expensed
  B2  trading: property held as a fixed asset, or depreciated
  B3  trading: property sale recorded with no cost of sales
  C1  any: the same property both a fixed asset and stock, or its development costs both expensed and in WIP
The rent start date is the one entered, else the first rent received in the ledger.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import MasterCOA, TBRecord
from backend.app.services.sop.common import GLLine, MIN_LINE_AMOUNT, gl_lines, year_months

RENTAL, TRADING = "RENTAL", "TRADING"
INCOME_SECTIONS = {"Sales", "Other operating income"}
FIXED_ASSET_CODES = range(4000, 4170)      # intangible and tangible fixed assets
STOCK_CODES = range(4300, 4311)            # stock and work in progress

# A line about a property (used to give lines to the only property, and to suggest properties)
PROPERTY_WORDS = re.compile(r"\b(rents? (income|received|receivables?)|rental income|tenants?|lettings?|letting agents?|"
                            r"landlords?|mortgages?|service charges?|ground rent|managing agents?|"
                            r"property management|residential property|commercial property|buy to let|btl)\b",
                            re.IGNORECASE)
RENT_INCOME = re.compile(r"\b(rent|rental|rents|letting|tenant)", re.IGNORECASE)
IMPROVEMENT = re.compile(r"\b(renovat\w*|refurb\w*|fit[- ]?out|extension|conversion|structural|rewir\w*|"
                         r"new (kitchen|bathroom|roof|boiler|windows)|plumbing overhaul|electrical overhaul|"
                         r"loft|underpinning|damp proof\w*)\b", re.IGNORECASE)
RUNNING = re.compile(r"\b(repairs?|maintenance|utilit\w*|gas|electric\w*|water|council tax|management fees?|"
                     r"letting agents?|agent'?s? fees?|cleaning|insurance|service charges?|ground rent)\b", re.IGNORECASE)
DEVELOPMENT = re.compile(r"\b(land|plot|construction|build(ing)? (costs?|works?)|builders?|groundworks?|architect\w*|"
                         r"planning|surveyor\w*|structural engineer\w*|legal|solicitor\w*|conveyancing|stamp duty|"
                         r"sdlt|land registry|development)\b", re.IGNORECASE)
ALREADY_LET_DAYS = 45      # rent within the first 45 days of the year: the property was let before the year began
NOT_COST_SOURCES = re.compile(r"journal", re.IGNORECASE)   # year-end and correcting journals are not costs incurred
GENERIC_HEADINGS = {"expenses", "expense", "income", "other income", "sales", "revenue", "cost of sales",
                    "overheads", "other expenses", "creditors", "debtors", "bank", "fixed assets"}

FLAGS = {
    "A1": "Improvement costs incurred before rental commencement should be capitalised, not expensed.",
    "A2": "Rental expenses recorded before rental income started. Review whether these should be capitalised.",
    "A3": "Significant property improvement recorded as expense. Review whether capitalisation is required.",
    "B1": "Costs directly attributable to property development should be included in inventory/WIP.",
    "B2": "Property held for resale should be treated as inventory, not a fixed asset.",
    "B3": "Property sale recorded with no cost of sales. The property's inventory / WIP should be released to cost of sales.",
    "C1": "Inconsistent accounting treatment detected for the same property.",
}
SEVERITY = {"A1": "HIGH", "A2": "MEDIUM", "A3": "MEDIUM", "B1": "HIGH", "B2": "HIGH", "B3": "HIGH", "C1": "MEDIUM"}
QUESTION = {RENTAL: "Was the property let out at the time this cost was incurred?",
            TRADING: "Is this property held for resale or long-term rental?"}


@dataclass
class PropertyEntry:
    name: str
    model: str                  # RENTAL or TRADING
    rent_start: Optional[date]  # entered by the accountant (else found in the ledger)
    words: List[str]            # how the property appears in the ledger (always includes its name)


@dataclass
class PropertyFlag:
    property: str
    model: str
    rule: str
    when: Optional[date]
    account: str
    description: str
    amount: float

    @property
    def reason(self) -> str:
        return FLAGS[self.rule]

    @property
    def question(self) -> str:
        return QUESTION[self.model]


@dataclass
class PropertySummary:
    entry: PropertyEntry
    rent_start: Optional[date]
    rent_start_source: str      # 'entered', 'first rent in the ledger' or 'no rent this year'
    rent_income: float = 0.0
    lines: int = 0
    flags: List[PropertyFlag] = field(default_factory=list)


def property_entries(profile) -> List[PropertyEntry]:
    """The accountant's property list from the client setup."""
    entries = []
    for p in json.loads(getattr(profile, "properties", None) or "[]") if profile is not None else []:
        name = str(p.get("name") or "").strip()
        model = str(p.get("model") or "").strip().upper()
        if not name or model not in (RENTAL, TRADING):
            continue
        start = None
        if p.get("rent_start"):
            try:
                start = date.fromisoformat(str(p["rent_start"])[:10])
            except ValueError:
                start = None
        words = [w.strip().lower() for w in (p.get("words") or []) if str(w).strip()]
        entries.append(PropertyEntry(name, model, start, sorted({name.lower(), *words}, key=len, reverse=True)))
    return entries


def _has(word: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None


def _owner(l: GLLine, entries: List[PropertyEntry]) -> Optional[PropertyEntry]:
    """The property a ledger line belongs to: its tag first, then the property's words, then (with one property)
    any property-type line."""
    if l.tracking:
        tagged = [p for p in entries if any(_has(w, l.tracking.lower()) for w in p.words)]
        if len(tagged) == 1:
            return tagged[0]
    text = f"{l.account} {l.description}".lower()
    hits = [(max(len(w) for w in p.words if _has(w, text)), p) for p in entries if any(_has(w, text) for w in p.words)]
    if hits:
        return max(hits, key=lambda h: h[0])[1]          # the most specific name wins
    if len(entries) == 1 and PROPERTY_WORDS.search(l.account):   # by account: 'service charges' on a phone bill is not rent
        return entries[0]
    return None


def find_property_issues(period_end: date, lines: Iterable[GLLine], chart: Dict[int, MasterCOA],
                         entries: List[PropertyEntry], capital_limit: float) -> List[PropertySummary]:
    by_property: Dict[str, List[GLLine]] = {p.name: [] for p in entries}
    for l in lines:
        if l.when <= period_end and l.code in chart:
            owner = _owner(l, entries)
            if owner is not None:
                by_property[owner.name].append(l)

    year_start = year_months(period_end)[0].replace(day=1)
    summaries = []
    for p in entries:
        mine = sorted(by_property[p.name], key=lambda l: l.when)
        section = lambda l: chart[l.code].category
        is_pl = lambda l: chart[l.code].financial_class == "Profit and Loss"
        income = [l for l in mine if section(l) in INCOME_SECTIONS and l.credit >= MIN_LINE_AMOUNT]
        rent = [l for l in income if RENT_INCOME.search(f"{l.account} {l.description}")] or income
        if p.rent_start:
            start, source = p.rent_start, "entered"
        elif rent and (rent[0].when - year_start).days <= ALREADY_LET_DAYS:
            start, source = year_start, "let before the year began (rent from the first weeks)"
        elif rent:
            start, source = rent[0].when, "first rent in the ledger"
        else:
            start, source = None, "no rent this year"
        s = PropertySummary(p, start, source, round(sum(l.credit - l.debit for l in rent), 2), len(mine))
        costs = [l for l in mine if is_pl(l) and section(l) not in INCOME_SECTIONS and l.debit >= MIN_LINE_AMOUNT
                 and not NOT_COST_SOURCES.search(l.source)]
        flag = lambda rule, l, amount=None: s.flags.append(PropertyFlag(
            p.name, p.model, rule, l.when if l else None, l.account if l else "", l.description if l else "",
            round(amount if amount is not None else l.debit, 2)))

        if p.model == RENTAL:
            for l in costs:
                text = f"{l.account} {l.description}"
                before = start is None or l.when < start
                if before and IMPROVEMENT.search(text):
                    flag("A1", l)
                elif before and RUNNING.search(text):
                    flag("A2", l)
                elif not before and IMPROVEMENT.search(text) and l.debit >= capital_limit:
                    flag("A3", l)
        else:
            for l in costs:
                if DEVELOPMENT.search(f"{l.account} {l.description}") and section(l) != "Cost of sales":
                    flag("B1", l)
            # B2: the property sits in fixed assets (or is depreciated): one line per account
            fa: Dict[str, float] = {}
            for l in mine:
                if l.code in FIXED_ASSET_CODES or section(l) == "Depreciation":
                    fa[l.account] = fa.get(l.account, 0.0) + l.debit - l.credit
            for account, amount in fa.items():
                if abs(amount) >= MIN_LINE_AMOUNT:
                    s.flags.append(PropertyFlag(p.name, p.model, "B2", None, account,
                                                "Movements on this fixed asset / depreciation account this year", round(amount, 2)))
            sold = sum(l.credit - l.debit for l in mine if section(l) in INCOME_SECTIONS and not RENT_INCOME.search(l.account))
            cost = sum(l.debit - l.credit for l in mine if section(l) == "Cost of sales")
            if sold >= MIN_LINE_AMOUNT and cost < MIN_LINE_AMOUNT:
                s.flags.append(PropertyFlag(p.name, p.model, "B3", None, "Sales",
                                            f"Sale proceeds £{sold:,.2f}; no cost of sales for this property", round(sold, 2)))

        # C1: the same property treated two ways
        in_fa = any(l.code in FIXED_ASSET_CODES for l in mine)
        in_stock = any(l.code in STOCK_CODES for l in mine)
        dev_expensed = [l for l in costs if IMPROVEMENT.search(f"{l.account} {l.description}")
                        or DEVELOPMENT.search(f"{l.account} {l.description}")]
        if in_fa and in_stock:
            s.flags.append(PropertyFlag(p.name, p.model, "C1", None, "", "Recorded both as a fixed asset and as stock / WIP", 0.0))
        elif in_stock and dev_expensed:
            s.flags.append(PropertyFlag(p.name, p.model, "C1", None, "",
                                        f"Development costs both in stock / WIP and expensed ({len(dev_expensed)} expense line(s))",
                                        round(sum(l.debit for l in dev_expensed), 2)))
        summaries.append(s)
    return summaries


def property_review(engagement_id: str, period_end: date, tb_records: Iterable[TBRecord], db: Session,
                    profile, capital_limit: float = 500.0) -> List[PropertySummary]:
    entries = property_entries(profile)
    if not entries:
        return []
    tb_records = list(tb_records)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    return find_property_issues(period_end, gl_lines(engagement_id, tb_records, db), chart, entries, capital_limit)


def suggest_properties(engagement_id: str, tb_records: Iterable[TBRecord], db: Session) -> List[Dict]:
    """Properties the ledger seems to have, for the accountant to confirm: tags on property-type lines, and account
    headings with property-type sub-accounts ('Residential Property' with 'Rent receivables' under it)."""
    tb_records = list(tb_records)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    lines = gl_lines(engagement_id, tb_records, db)
    has_rent = lambda ls: any(l.code in chart and chart[l.code].category in INCOME_SECTIONS
                              and PROPERTY_WORDS.search(l.account) for l in ls)

    found: Dict[str, Tuple[List[GLLine], str]] = {}
    tags = Counter(l.tracking for l in lines if l.tracking and PROPERTY_WORDS.search(l.account))
    for tag, _n in tags.most_common(20):
        found[tag] = ([l for l in lines if l.tracking == tag], f"tag '{tag}' on property lines")
    names = {t.raw_account_name for t in tb_records} | {l.account for l in lines}
    for name in sorted(names):
        if ":" not in name:
            continue
        parent, child = name.split(":", 1)[0].strip(), name.split(":", 1)[1]
        if parent.lower() in GENERIC_HEADINGS or not (PROPERTY_WORDS.search(child) or PROPERTY_WORDS.search(parent)):
            continue
        if parent not in found:
            found[parent] = ([l for l in lines if l.account.startswith(parent + ":")], f"account heading '{parent}'")
    if not found:
        rent_lines = [l for l in lines if l.code in chart and chart[l.code].category in INCOME_SECTIONS
                      and PROPERTY_WORDS.search(l.account)]    # 'Rent received', not 'PO Box rental'
        if rent_lines:
            found["Rental property"] = (rent_lines, "rent income in the ledger")
    return [{"name": name, "model": RENTAL if has_rent(ls) else TRADING, "rent_start": None, "words": [],
             "reason": f"Found from the {why} ({len(ls)} ledger line(s))"} for name, (ls, why) in found.items()]
