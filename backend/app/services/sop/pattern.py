"""
Pattern and anomaly checks on payments and expenses: a review and confirmation report, not
an adjustment engine. Each flagged payment shows its date, amount, account, description and the reason(s):
  Rule 1  a bank payment with no description, or a generic one ('payment', 'transfer', 'online')
  Rule 2  a payment posted to a vague account (miscellaneous, suspense, sundry, other expenses...)
  Rule 3  a payment far above the account's usual payment
  Rule 4  a one-off large payment: large, to a supplier that appears only once or twice in the year
  Rule 5  12 vs 11 regular payments: done by the accruals check (G10.2), not repeated here
  Rule 6  irregular timing: a supplier paid most months, with a gap of 2 months or more
  Rule 8  a supplier that appears once, with a description that doesn't say what the payment was for
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import MasterCOA, TBRecord
from backend.app.services.sop.common import (GLLine, MIN_LINE_AMOUNT, NOT_PREPAYABLE_SECTIONS, PAYROLL_CODES, gl_lines,
                                             supplier_name, year_months)

BANK_CODES = set(range(4800, 4831))
NOT_PAYMENT_SOURCES = re.compile(r"journal|transfer|adjustment|revaluation", re.IGNORECASE)   # entries, not payments
MONEY_IN_SOURCES = re.compile(r"deposit|receive|receipt|sales", re.IGNORECASE)      # money in, not payments
GENERIC_DESCRIPTIONS = {"payment", "payments", "transfer", "online", "online payment", "online transfer",
                        "bank transfer", "faster payment", "fp", "bp", "bill payment", "dd", "direct debit", "so",
                        "standing order", "card", "card payment", "pos", "debit", "withdrawal", "cash",
                        "cash withdrawal", "misc", "sundry", "na", "n a", "none", "other", "expense", "expenses"}
# VAT suspense / control accounts are where VAT normally sits, so they are not 'vague'
VAGUE_ACCOUNT = re.compile(r"\b(misc\w*|sundr\w*|suspense|other expenses?|general expenses?|uncategori[sz]ed\w*|"
                           r"ask my accountant|unknown|unallocated|other debtors?|other creditors?)\b", re.IGNORECASE)
VAT_ACCOUNT = re.compile(r"\bvat\b", re.IGNORECASE)
VAGUE_CODES = {9999, 3390, 3392, 3393, 3394, 3395}   # suspense and sundry codes of the firm's chart

NO_DESCRIPTION_MIN_AMOUNT = 50.0  # Rule 1: ignore small bank fees with no description
LARGE_MULTIPLE = 3          # Rule 3: more than 3x the top of the account's usual range ...
LARGE_MIN_AMOUNT = 1000.0   # ... and at least this much
USUAL_MIN_PAYMENTS = 6      # an account needs this many payments to have a 'usual' amount
ONE_OFF_MIN_AMOUNT = 1000.0 # Rule 4: a large payment
ONE_OFF_MAX_TIMES = 2       # Rule 4: supplier seen only once or twice in the year
UNKNOWN_MIN_AMOUNT = 500.0  # Rule 8: ignore small one-off purchases
REGULAR_MIN_MONTHS = 6      # Rule 6: a supplier paid in at least 6 months of the year is a regular payment
GAP_MONTHS = 2              # Rule 6: 2 months or more without a payment between payments

REASON_NO_DESCRIPTION = "Payment has no or unclear description. Please confirm nature of expense."
REASON_VAGUE_ACCOUNT = "Payment posted to a generic account. Please confirm correct classification."
REASON_LARGE = "Unusually large payment compared to normal transactions."
REASON_ONE_OFF = "One-off large payment. Please confirm nature."
REASON_IRREGULAR = "Irregular timing of payments. Please confirm correctness."
REASON_UNKNOWN_SUPPLIER = "Unidentified supplier payment. Please clarify."
PATTERN_RULES = {1: (REASON_NO_DESCRIPTION, "LOW"), 2: (REASON_VAGUE_ACCOUNT, "MEDIUM"), 3: (REASON_LARGE, "MEDIUM"),
                 4: (REASON_ONE_OFF, "MEDIUM"), 6: (REASON_IRREGULAR, "LOW"), 8: (REASON_UNKNOWN_SUPPLIER, "LOW")}
PATTERN_QUESTION = ("We noticed the following payments that either lack descriptions, appear unusual, or don't follow "
                    "the normal pattern. Please confirm what these relate to and whether any accruals are required.")


@dataclass
class PatternFlag:
    when: Optional[date]        # None for a timing flag (it covers several payments)
    account: str
    code: int
    description: str
    amount: float
    reasons: List[str] = field(default_factory=list)
    rules: List[int] = field(default_factory=list)


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z ]", " ", (text or "").lower()).split())


def _memo(description: str) -> str:
    """What the payment was for: the part after the supplier ('Slack - Pro plan' -> 'pro plan')."""
    parts = (description or "").split(" - ", 1)
    return parts[1].strip().lower() if len(parts) > 1 else ""


def _upper_quartile(values: List[float]) -> float:
    """The top of an account's usual range: 3 in 4 of its payments are at or below this."""
    values = sorted(values)
    return values[min(len(values) - 1, (3 * len(values)) // 4)]


def find_pattern_issues(period_end: date, lines: Iterable[GLLine], chart: Dict[int, MasterCOA]) -> List[PatternFlag]:
    # Lines with no transaction type are system entries (e.g. Xero's currency revaluations), not payments
    in_year = [l for l in lines if l.when <= period_end and l.source.strip()
               and not NOT_PAYMENT_SOURCES.search(l.source)]
    bank = [l for l in in_year if l.code in BANK_CODES and l.credit >= MIN_LINE_AMOUNT
            and not MONEY_IN_SOURCES.search(l.source)]
    expense = [l for l in in_year if l.code in chart and chart[l.code].financial_class == "Profit and Loss"
               and chart[l.code].category not in NOT_PREPAYABLE_SECTIONS and l.code not in PAYROLL_CODES
               and l.debit >= MIN_LINE_AMOUNT]
    other = [l for l in in_year if l.code not in BANK_CODES and l.debit >= MIN_LINE_AMOUNT
             and not (l.code in chart and chart[l.code].financial_class == "Profit and Loss"
                      and chart[l.code].category in NOT_PREPAYABLE_SECTIONS)]

    flags: Dict[Tuple, PatternFlag] = {}

    def flag(l: GLLine, amount: float, rule: int, reason: str) -> None:
        f = flags.setdefault((l.when, l.account, l.description, amount),
                             PatternFlag(l.when, l.account, l.code, l.description, amount))
        if rule not in f.rules:
            f.rules.append(rule)
            f.reasons.append(reason)

    # Rule 1: bank payments with no or a generic description
    for l in bank:
        if l.credit >= NO_DESCRIPTION_MIN_AMOUNT and (_words(l.description) in GENERIC_DESCRIPTIONS
                                                    or not _words(l.description)):
            flag(l, l.credit, 1, REASON_NO_DESCRIPTION)

    # Rule 2: payments posted to vague accounts (by the client's account name, or the firm's suspense / sundry codes)
    for l in other:
        if (VAGUE_ACCOUNT.search(l.account) and not VAT_ACCOUNT.search(l.account)) or l.code in VAGUE_CODES:
            flag(l, l.debit, 2, REASON_VAGUE_ACCOUNT)

    # Rule 3: far above the account's usual range of payments
    by_account: Dict[str, List[float]] = {}
    for l in expense:
        by_account.setdefault(l.account, []).append(l.debit)
    usual = {a: _upper_quartile(v) for a, v in by_account.items() if len(v) >= USUAL_MIN_PAYMENTS}
    for l in expense:
        if l.account in usual and l.debit >= LARGE_MIN_AMOUNT and l.debit > LARGE_MULTIPLE * usual[l.account]:
            flag(l, l.debit, 3, REASON_LARGE)

    # Rules 4 and 8: suppliers seen once or twice in the year (counted over every expense line)
    times: Dict[str, int] = {}
    for l in expense:
        times[supplier_name(l.description)] = times.get(supplier_name(l.description), 0) + 1
    for l in expense:
        supplier = supplier_name(l.description)
        if not supplier:
            continue
        if l.debit >= ONE_OFF_MIN_AMOUNT and times[supplier] <= ONE_OFF_MAX_TIMES:
            flag(l, l.debit, 4, REASON_ONE_OFF)
        memo = _words(_memo(l.description))
        if times[supplier] == 1 and l.debit >= UNKNOWN_MIN_AMOUNT and (not memo or memo == _words(supplier)
                                                                       or memo in GENERIC_DESCRIPTIONS):
            flag(l, l.debit, 8, REASON_UNKNOWN_SUPPLIER)

    # Rule 6: a supplier paid in most months of the year, with a gap of 2+ months between payments
    months = year_months(period_end)
    index = {(m.year, m.month): i for i, m in enumerate(months)}
    paid: Dict[Tuple[str, str], List[GLLine]] = {}
    for l in expense:
        supplier = supplier_name(l.description)
        if supplier and (l.when.year, l.when.month) in index:
            paid.setdefault((l.account, supplier), []).append(l)
    timing = []
    for (account, supplier), payments in paid.items():
        present = sorted({index[(l.when.year, l.when.month)] for l in payments})
        if len(present) < REGULAR_MIN_MONTHS:
            continue
        gaps = [(a, b) for a, b in zip(present, present[1:]) if b - a - 1 >= GAP_MONTHS]
        if gaps:
            dates = ", ".join(f"{d:%d/%m/%Y}" for d in sorted(l.when for l in payments))
            missing = "; ".join(f"{months[a + 1]:%b %Y} to {months[b - 1]:%b %Y}" for a, b in gaps)
            first = payments[0]
            timing.append(PatternFlag(None, account, first.code,
                                      f"{first.description.split(' - ')[0]}: no payment {missing}. Paid on {dates}",
                                      round(sum(l.debit for l in payments), 2), [REASON_IRREGULAR], [6]))

    result = sorted(flags.values(), key=lambda f: (min(f.rules), f.when, f.account)) + \
        sorted(timing, key=lambda f: f.account)
    return result


def pattern_review(engagement_id: str, period_end: date, tb_records: Iterable[TBRecord], db: Session) -> List[PatternFlag]:
    tb_records = list(tb_records)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    return find_pattern_issues(period_end, gl_lines(engagement_id, tb_records, db), chart)
