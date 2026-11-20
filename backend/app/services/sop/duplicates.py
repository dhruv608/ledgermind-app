"""
Duplicate transactions, customer side and supplier side kept separate:
  duplicate    the same bill / invoice number, same amount, same contact entered more than once;
  possible     the same contact and amount within a week, one with no number: for review;
  unallocated  a bill / invoice still outstanding at the year end (aged payables / receivables report) while a direct
               payment / receipt (Spend Money / Receive Money, QuickBooks Expense / Deposit) of the same amount was
               made to the same contact on or after its date: probably paid but not allocated, or paid twice;
  mixed        a contact with bills / invoices and also several direct payments / receipts: a warning only.
QuickBooks works the same way under other names, so both packages are covered.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import GLTransaction, TBRecord
from backend.app.services.ingestion.ageing_reports import outstanding_items, read_ageing_reports

DOCUMENT_SOURCES = {"supplier": {"payable invoice", "bill"}, "customer": {"receivable invoice", "invoice"}}
DIRECT_SOURCES = {"supplier": {"spend money", "expense", "cheque", "check"},
                  "customer": {"receive money", "deposit", "sales receipt"}}
AGEING_KIND = {"supplier": "AP", "customer": "AR"}
DIRECT_MIN_AMOUNT = 1.0
MIXED_MIN_DIRECT = {"supplier": 1, "customer": 2}   # mixed check; a supplier with one bill and one direct payment is
                                                     # highlighted
REVERSAL_DAYS = 14              # a direct debit returned by the bank within this many days was not a payment

FLAG_DUPLICATE_DOC = {"supplier": "Duplicate supplier bill detected: same bill number, amount and supplier.",
                      "customer": "Duplicate sales invoice detected: same invoice number, amount and customer."}
FLAG_POSSIBLE = {"supplier": "Possible duplicate bill: same supplier and amount within a week, one with no bill "
                             "number.",
                 "customer": "Possible duplicate invoice: same customer and amount within a week, one with no invoice "
                             "number."}
POSSIBLE_DAYS = 6               # within a week; 7 days apart is a weekly bill
POSSIBLE_MIN = 100.0            # as the other duplicate tests (BILL_DIRECT_MIN)
FLAG_UNALLOCATED = {
    "supplier": "Supplier payment exists but bill is still outstanding. Payment may be incorrectly unallocated or duplicated.",
    "customer": "Customer receipt exists but invoice is still outstanding. Receipt may be incorrectly unallocated or duplicated.",
}
FLAG_MIXED = "Inconsistent allocation behaviour detected. Review posting method."
DUPLICATE_QUESTION = {
    "supplier": "Please confirm whether this bill was paid, and whether the payment should be matched to it or was paid twice.",
    "customer": "Please confirm whether this invoice was received, and whether the receipt should be matched to it or was recorded twice.",
}

LEGAL_WORDS = re.compile(r"\b(ltd|limited|plc|llp|inc|co|uk|gbp|usd|eur)\b|\(.*?\)|[^a-z0-9 ]")


def _contact_key(name: str) -> str:
    """A contact name for matching the ledger with the ageing report ('A.B. Smith & Son Ltd' -> 'ab smith son')."""
    return " ".join(LEGAL_WORDS.sub(" ", (name or "").lower()).split())


@dataclass
class LedgerDocument:
    side: str                   # "supplier" or "customer"
    kind: str                   # "document" (bill / invoice) or "direct" (payment / receipt not through a bill)
    when: date
    contact: str
    number: str
    amount: float               # gross: the largest line of the document (the bank or control account line)
    source: str


def ledger_documents(engagement_id: str, db: Session) -> List[LedgerDocument]:
    """Bills, invoices and direct payments / receipts from the ledger, one per document (a document has a line on
    each account it touches; the largest is its gross amount)."""
    gross: Dict[Tuple[str, str, date, str, str], float] = {}
    for tx in db.execute(select(GLTransaction).where(GLTransaction.engagement_id == engagement_id)).scalars():
        source = (tx.source or "").strip().lower()
        side_kind = next(((side, kind) for side in ("supplier", "customer")
                          for kind, names in (("document", DOCUMENT_SOURCES[side]), ("direct", DIRECT_SOURCES[side]))
                          if source in names), None)
        if side_kind is None or not tx.transaction_date:
            continue
        contact = (tx.description or "").split(" - ")[0].strip()
        if not contact:
            continue
        key = (side_kind[0], side_kind[1], tx.transaction_date, contact, str(tx.reference or "").strip(), tx.source)
        gross[key] = max(gross.get(key, 0.0), float(tx.debit_amount or 0), float(tx.credit_amount or 0))
    return [LedgerDocument(side, kind, when, contact, number, round(amount, 2), source)
            for (side, kind, when, contact, number, source), amount in gross.items() if amount >= DIRECT_MIN_AMOUNT]


@dataclass
class DuplicateFlag:
    side: str
    check: str                  # "duplicate", "possible", "unallocated" or "mixed"
    contact: str
    amount: float
    message: str
    detail: str
    when: Optional[date] = None
    number: str = ""

    @property
    def question(self) -> str:
        return "Please confirm how payments to this contact are recorded." if self.check == "mixed" else DUPLICATE_QUESTION[self.side]


def _reversed(payment: "LedgerDocument", others: List["LedgerDocument"]) -> bool:
    """A direct payment the bank took back (a direct debit reversal: the same amount from the same contact a few
    days later, recorded as a deposit / receipt), or a receipt paid back: neither settled anything."""
    key = _contact_key(payment.contact)
    return any(_contact_key(o.contact) == key and abs(o.amount - payment.amount) < 0.01
               and 0 <= (o.when - payment.when).days <= REVERSAL_DAYS for o in others)


def find_duplicates(documents: List[LedgerDocument], outstanding: Dict[str, list], period_end: date) -> List[DuplicateFlag]:
    flags: List[DuplicateFlag] = []
    for side in ("supplier", "customer"):
        other_side = "customer" if side == "supplier" else "supplier"
        docs = [d for d in documents if d.side == side and d.kind == "document" and d.when <= period_end]
        # Direct payments / receipts, less those reversed (a direct debit taken, bounced and taken again
        # is one payment, not two)
        back = [d for d in documents if d.side == other_side and d.kind == "direct" and d.when <= period_end]
        direct = [d for d in documents if d.side == side and d.kind == "direct" and d.when <= period_end
                  and not _reversed(d, back)]
        # Outstanding items: the bills / invoices only. A detail report also lists the contact's unallocated
        # payments, credits and reversed direct debits ('Expense', 'Deposit'): those are not bills left unpaid
        owed = [i for i in outstanding.get(AGEING_KIND[side], [])
                if not getattr(i, "kind", "") or re.search(r"bill|invoice", i.kind)]
        owed_numbers = {(_contact_key(i.contact), i.number) for i in owed if i.number}

        # Duplicate: same number, amount and contact more than once. Only real document numbers (with a digit): Xero
        # 'references' such as 'MAILING FEE' repeat every month on genuine recurring bills.
        groups: Dict[Tuple[str, str, float], List[LedgerDocument]] = {}
        for d in docs:
            if re.search(r"\d", d.number):
                groups.setdefault((_contact_key(d.contact), d.number.lower(), d.amount), []).append(d)
        for (key, _number, amount), same in groups.items():
            if len(same) < 2:
                continue
            first = min(same, key=lambda d: d.when)
            still_owed = (key, first.number) in owed_numbers
            dates = ", ".join(f"{d.when:%d/%m/%Y}" for d in sorted(same, key=lambda d: d.when))
            flags.append(DuplicateFlag(
                side, "duplicate", first.contact, amount,
                FLAG_DUPLICATE_DOC[side] + (" One is still outstanding." if still_owed else ""),
                f"{len(same)} entries of {first.number} for £{amount:,.2f} on {dates}", first.when, first.number))

        # Possible duplicate: same contact and amount, dated within POSSIBLE_DAYS of each other, one of the two with no
        # number: for review. Two different numbers are not raised, as they are nearly always repeat sales and orders
        # (weekly sessions, online orders); a document with no number repeating a numbered one is the double entry.
        # Exactly a week apart is a weekly bill, not a double.
        same_amount: Dict[Tuple[str, float], List[LedgerDocument]] = {}
        for d in docs:
            if d.amount >= POSSIBLE_MIN:
                same_amount.setdefault((_contact_key(d.contact), d.amount), []).append(d)
        for (_key, amount), same in same_amount.items():
            same.sort(key=lambda d: (d.when, d.number))
            for a, b in zip(same, same[1:]):
                numbered = [bool(re.search(r"\d", x.number)) for x in (a, b)]
                if (b.when - a.when).days > POSSIBLE_DAYS or all(numbered):
                    continue
                flags.append(DuplicateFlag(
                    side, "possible", a.contact, amount, FLAG_POSSIBLE[side],
                    f"£{amount:,.2f} on {a.when:%d/%m/%Y} ({a.number or 'no number'}) and on {b.when:%d/%m/%Y} "
                    f"({b.number or 'no number'})", a.when, a.number))

        # Unallocated: outstanding at the year end, and a direct payment / receipt of the same amount to the same contact
        # on or after its date. A summary report has no dates: the ledger bill with that amount stands in for it.
        by_contact: Dict[str, List[LedgerDocument]] = {}
        for d in direct:
            by_contact.setdefault(_contact_key(d.contact), []).append(d)
        docs_by_contact: Dict[str, List[LedgerDocument]] = {}
        for d in docs:
            docs_by_contact.setdefault(_contact_key(d.contact), []).append(d)
        used = set()
        for item in owed:
            key = _contact_key(item.contact)
            if item.amount <= 0 or not key:
                continue
            candidates = []
            if item.when is not None:
                candidates = [(p, item.when, item.number) for p in by_contact.get(key, [])
                              if abs(p.amount - item.amount) < 0.01 and p.when >= item.when]
            else:
                for bill in docs_by_contact.get(key, []):
                    if bill.amount <= item.amount + 0.01:
                        candidates += [(p, bill.when, bill.number) for p in by_contact.get(key, [])
                                       if abs(p.amount - bill.amount) < 0.01 and p.when >= bill.when]
            for payment, doc_date, number in candidates:
                if id(payment) in used:
                    continue
                used.add(id(payment))
                kind = "bill" if side == "supplier" else "invoice"
                flags.append(DuplicateFlag(
                    side, "unallocated", item.contact, payment.amount, FLAG_UNALLOCATED[side],
                    f"{kind} {number or ''} dated {doc_date:%d/%m/%Y} outstanding at the year end; "
                    f"{payment.source} of £{payment.amount:,.2f} on {payment.when:%d/%m/%Y}".replace("  ", " "),
                    doc_date, number))
                break

        # Mixed: bills / invoices and also several direct payments / receipts to the same contact (warning only)
        for key, payments in by_contact.items():
            if key in docs_by_contact and len(payments) >= MIXED_MIN_DIRECT[side]:
                flags.append(DuplicateFlag(
                    side, "mixed", payments[0].contact, round(sum(p.amount for p in payments), 2), FLAG_MIXED,
                    f"{len(docs_by_contact[key])} {'bill' if side == 'supplier' else 'invoice'}(s) and "
                    f"{len(payments)} direct {'payment' if side == 'supplier' else 'receipt'}(s) this year"))
    order = {"duplicate": 0, "possible": 1, "unallocated": 2, "mixed": 3}
    flags.sort(key=lambda f: (order[f.check], f.side, -f.amount))
    return flags


def duplicate_review(engagement_id: str, period_end: date, db: Session) -> List[DuplicateFlag]:
    tb_records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement_id)).scalars().all()
    reports = read_ageing_reports(engagement_id, period_end, tb_records)
    # Only a report at this year end says what was outstanding at the year end
    outstanding = {kind: outstanding_items(r) for kind, r in reports.items() if r.as_at in (None, period_end)}
    return find_duplicates(ledger_documents(engagement_id, db), outstanding, period_end)


# ------------------------------------------------------------------------------------------------------------------
# A journal posted twice (a month's payroll journal or a commission journal entered again). A journal entry is its
# lines sharing date, reference and source (with no reference, date, source and narrative); two entries with the same
# lines (same accounts, same amounts) in one calendar month are raised. A monthly journal (rent, depreciation) is once
# a month, so it is not.
# ------------------------------------------------------------------------------------------------------------------
JOURNAL_SOURCE = re.compile(r"journal|\bjnl\b|\bgj\b|\bjl\b|\bjd\b|\bjc\b", re.I)
JOURNAL_TWICE_MIN = 100.0


@dataclass
class JournalTwice:
    month: date                  # the first day of the month
    times: int
    amount: float                # the debits of one entry
    dates: List[date]
    lines: List[Tuple[str, float]]   # account, debit - credit


def journals_twice(engagement_id: str, tb_records, db: Session, minimum: float = JOURNAL_TWICE_MIN) -> List[JournalTwice]:
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.sop.common import code_matcher, ledger_rows
    code_of = code_matcher(ChartLookup.gl_account_codes(list(tb_records)))
    entries: Dict[tuple, List[Tuple[str, str, float]]] = {}
    for t in ledger_rows(engagement_id, db):
        if not t.transaction_date or not JOURNAL_SOURCE.search(t.source or ""):
            continue
        ref = (t.reference or "").strip()
        key = (t.transaction_date, ref, (t.source or "").strip(), "" if ref else (t.description or "")[:40])
        code = code_of(t.raw_account_name)
        entries.setdefault(key, []).append((str(code) if code is not None else t.raw_account_name, t.raw_account_name,
                                            round(float(t.debit_amount or 0) - float(t.credit_amount or 0), 2)))
    same: Dict[tuple, List[Tuple[date, float, List[Tuple[str, float]]]]] = {}
    out = []
    for (when, _, _, _), lines in entries.items():
        # Posted twice on the same day under one reference: every line appears an even number of times and one copy
        # balances on its own (the same day is the commonest way of posting twice)
        counts: Dict[Tuple[str, float], int] = {}
        for c, _name, v in lines:
            counts[(c, v)] = counts.get((c, v), 0) + 1
        half = [(c, v) for (c, v), n in counts.items() for _ in range(n // 2)]
        if (len(lines) >= 4 and all(n % 2 == 0 for n in counts.values()) and abs(sum(v for _, v in half)) < 0.01
                and sum(v for _, v in half if v > 0) >= minimum):
            out.append(JournalTwice(month=when.replace(day=1), times=2, amount=round(sum(v for _, v in half if v > 0), 2),
                                    dates=[when, when], lines=[(c, v) for c, v in half]))
            continue
        amount = round(sum(v for _, _, v in lines if v > 0), 2)
        if len(lines) < 2 or amount < minimum:
            continue
        signature = tuple(sorted((c, v) for c, _, v in lines))
        same.setdefault(signature, []).append((when, amount, [(name, v) for _, name, v in lines]))
    for seen in same.values():
        by_month: Dict[date, list] = {}
        for when, amount, lines in seen:
            by_month.setdefault(when.replace(day=1), []).append((when, amount, lines))
        for month, items in by_month.items():
            # Weekly or fortnightly runs (payroll, standing journals) repeat at 7 or 14 days: recurring, not twice
            # (payroll is checked separately)
            days = sorted(w for w, _, _ in items)
            if len(items) > 1 and all((b - a).days in (7, 14) for a, b in zip(days, days[1:])):
                continue
            if len(items) > 1:
                out.append(JournalTwice(month=month, times=len(items), amount=items[0][1],
                                        dates=sorted(w for w, _, _ in items), lines=items[0][2]))
    return sorted(out, key=lambda j: -j.amount * j.times)


# ------------------------------------------------------------------------------------------------------------------
# The same cost entered as a bill and again as a direct payment (Spend Money): a near-certain duplicate. Both reach
# the P&L, so the cost is counted twice. Each bill line is paired with at most one direct line of the same supplier and amount within
# BILL_DIRECT_DAYS. Raised once per supplier.
# ------------------------------------------------------------------------------------------------------------------
BILL_SOURCE = re.compile(r"\bbill\b|payable invoice|purchase invoice", re.I)
DIRECT_SOURCE = re.compile(r"spend money|expense|cheque|\bcheck\b|card|bank payment", re.I)
BILL_DIRECT_DAYS = 45
BILL_DIRECT_MIN = 100.0


@dataclass
class BillAlsoPaid:
    supplier: str
    pairs: List[Tuple[date, date, float, str]]   # bill date, direct date, amount, cost account
    total: float


def bills_also_paid_direct(engagement_id: str, tb_records, db: Session,
                           minimum: float = BILL_DIRECT_MIN) -> List[BillAlsoPaid]:
    from backend.app.models.database import MasterCOA
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.sop.common import code_matcher, ledger_rows
    code_of = code_matcher(ChartLookup.gl_account_codes(list(tb_records)))
    pl = {c.std_code for c in db.query(MasterCOA).filter(MasterCOA.financial_class == "Profit and Loss")}
    bills, direct = [], []
    for t in ledger_rows(engagement_id, db):
        debit = float(t.debit_amount or 0)
        if not t.transaction_date or debit < minimum or code_of(t.raw_account_name) not in pl:
            continue
        supplier = _contact_key((t.description or "").split(" - ")[0])
        if not supplier:
            continue
        item = (t.transaction_date, round(debit, 2), supplier, t.raw_account_name, (t.description or "").split(" - ")[0].strip())
        if BILL_SOURCE.search(t.source or ""):
            bills.append(item)
        elif DIRECT_SOURCE.search(t.source or ""):
            direct.append(item)
    used, by_supplier = set(), {}
    for b in sorted(bills):
        match = next((i for i, d in enumerate(direct) if i not in used and d[2] == b[2] and d[1] == b[1]
                      and abs((d[0] - b[0]).days) <= BILL_DIRECT_DAYS), None)
        if match is None:
            continue
        used.add(match)
        d = direct[match]
        by_supplier.setdefault(b[2], (b[4], []))[1].append((b[0], d[0], b[1], b[3]))
    out = [BillAlsoPaid(supplier=name, pairs=pairs, total=round(sum(p[2] for p in pairs), 2))
           for name, pairs in by_supplier.values()]
    return sorted(out, key=lambda x: -x.total)


# ------------------------------------------------------------------------------------------------------------------
# A regular monthly charge entered twice in one month (a monthly direct debit, and in one month also the same
# supplier's bill for the same amount: the extra one comes out, with its VAT). Only a supplier with a steady charge (the same amount in RECURRING_MONTHS or more months, once a month in most of them): there a second
# one in a month stands out; a supplier billed fortnightly or at changing amounts is not judged.
# ------------------------------------------------------------------------------------------------------------------
RECURRING_MONTHS = 4
ONCE_SHARE = 0.75
STEADY_SHARE = 0.8             # the steady amount is at least this share of the supplier's lines on the account


@dataclass
class TwiceInMonth:
    supplier: str
    account: str
    amount: float
    months: List[Tuple[date, date]]      # the month's two dates (first, second)


def same_supplier(a: str, b: str) -> bool:
    """One supplier written two ways: 'Acme' on the bill, 'Acme Communications' on the direct debit."""
    return a == b or b.startswith(a + " ") or a.startswith(b + " ")


def twice_in_a_month(engagement_id: str, tb_records, db: Session) -> List[TwiceInMonth]:
    """A supplier's steady monthly charge (the same amount in RECURRING_MONTHS or more months, once in most of them,
    and most of the supplier's lines on that account) entered twice in one month as a bill AND a direct payment: the
    bill and the direct debit for the same month both as costs. Two direct payments, or a supplier bought from at
    varying amounts (card fees, a shop), are not judged (too many false flags)."""
    from backend.app.models.database import MasterCOA
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.sop.common import code_matcher, ledger_rows
    code_of = code_matcher(ChartLookup.gl_account_codes(list(tb_records)))
    pl = {c.std_code for c in db.query(MasterCOA).filter(MasterCOA.financial_class == "Profit and Loss")}
    lines: List[Tuple[str, float, date, str, str, str]] = []        # account, amount, date, key, name, kind
    for t in ledger_rows(engagement_id, db):
        debit = round(float(t.debit_amount or 0), 2)
        source = t.source or ""
        if (not t.transaction_date or debit < DIRECT_MIN_AMOUNT or code_of(t.raw_account_name) not in pl
                or "journal" in source.lower()):
            continue
        kind = "bill" if BILL_SOURCE.search(source) else "direct" if DIRECT_SOURCE.search(source) else ""
        name = (t.description or "").split(" - ")[0].strip()
        key = _contact_key(name)
        if key and kind:
            lines.append((t.raw_account_name, debit, t.transaction_date, key, name, kind))
    groups: Dict[Tuple[str, float], List[Tuple[date, str, str, str]]] = {}
    for account, amount, d, key, name, kind in lines:
        groups.setdefault((account, amount), []).append((d, key, name, kind))
    out: List[TwiceInMonth] = []
    for (account, amount), items in groups.items():
        keys: Dict[str, int] = {}
        for _d, k, _n, _kind in items:
            keys[k] = keys.get(k, 0) + 1
        main = max(keys, key=lambda k: (keys[k], len(k)))
        mine = sorted((d, n, kind) for d, k, n, kind in items if same_supplier(k, main))
        everything = [1 for acc, _a, _d, k, _n, _k in lines if acc == account and same_supplier(k, main)]
        if len(mine) < STEADY_SHARE * len(everything):
            continue                     # the supplier's charges on this account vary: not one steady charge
        by_month: Dict[Tuple[int, int], List[Tuple[date, str]]] = {}
        for d, _n, kind in mine:
            by_month.setdefault((d.year, d.month), []).append((d, kind))
        if len(by_month) < RECURRING_MONTHS:
            continue
        once = sum(1 for v in by_month.values() if len(v) == 1)
        doubled = [sorted(v) for v in by_month.values() if len(v) == 2 and {k for _d, k in v} == {"bill", "direct"}]
        if not doubled or once < ONCE_SHARE * len(by_month):
            continue
        shown = max((n for _d, n, _k in mine), key=len)
        out.append(TwiceInMonth(shown, account, amount, [(v[0][0], v[1][0]) for v in sorted(doubled)]))
    return sorted(out, key=lambda x: -x.amount * len(x.months))


# ------------------------------------------------------------------------------------------------------------------
# A cost booked twice in two ways:
#  - salary twice: a staff-cost account with payroll-journal debits and direct-payment debits each of £1,000 or more,
#    the smaller at least half the larger (the payroll journal made the cost and the payments to the director made it
#    again).
#  - accrued and billed: a credit to accruals of the same amount as a cost bill within 31 days (the invoice accrued by
#    journal and entered as a bill as well).
# ------------------------------------------------------------------------------------------------------------------
TWICE_MIN = 1000.0
TWICE_RATIO = 0.5
ACCRUALS_CODE = 5360


@dataclass
class CostTwice:
    kind: str                    # "salary" or "accrued and billed"
    account: str
    amount: float                # the amount counted twice (the smaller of the two)
    detail: str


def costs_booked_twice(engagement_id: str, tb_records, db: Session) -> List[CostTwice]:
    from backend.app.models.database import MasterCOA
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.sop.common import code_matcher, ledger_rows
    code_of = code_matcher(ChartLookup.gl_account_codes(list(tb_records)))
    chart = {c.std_code: c for c in db.query(MasterCOA)}
    staff: Dict[str, List[float]] = {}
    accrued, bills = [], []
    for t in ledger_rows(engagement_id, db):
        code = code_of(t.raw_account_name)
        c = chart.get(code)
        net = float(t.debit_amount or 0) - float(t.credit_amount or 0)
        if c is not None and c.category == "Employee costs":
            if JOURNAL_SOURCE.search(t.source or ""):
                staff.setdefault(t.raw_account_name, [0.0, 0.0])[0] += net
            elif DIRECT_SOURCE.search(t.source or ""):
                staff.setdefault(t.raw_account_name, [0.0, 0.0])[1] += net
        if not t.transaction_date:
            continue
        if code == ACCRUALS_CODE and -net >= BILL_DIRECT_MIN:
            accrued.append((t.transaction_date, round(-net, 2), (t.description or "")[:80]))
        elif (c is not None and c.financial_class == "Profit and Loss" and net > 0 and BILL_SOURCE.search(t.source or "")):
            bills.append((t.transaction_date, round(net, 2), t.raw_account_name))
    out = [CostTwice("salary", name, round(min(j, p), 2),
                     f"payroll journals £{j:,.2f} and direct payments £{p:,.2f} both posted to this cost")
           for name, (j, p) in staff.items() if j >= TWICE_MIN and p >= TWICE_MIN and min(j, p) >= TWICE_RATIO * max(j, p)]
    used = set()
    for when, amount, desc in accrued:
        i = next((i for i, b in enumerate(bills) if i not in used and b[1] == amount and abs((b[0] - when).days) <= 31), None)
        if i is not None:
            used.add(i)
            out.append(CostTwice("accrued and billed", bills[i][2], amount,
                                 f"accrued {when:%d/%m/%Y} ({desc}) and billed {bills[i][0]:%d/%m/%Y}"))
    return out


# ------------------------------------------------------------------------------------------------------------------
# The same bill entered twice with no bill number to compare: two cost bills from one supplier for the same amount on
# the same day (with the same, different or no reference), where only ONE of them was paid (two such bills can be normal,
# but one paid and the other outstanding is a duplicate). Paid = a bill payment from a bank account to that supplier
# for that amount.
# ------------------------------------------------------------------------------------------------------------------
PAID_SOURCE = re.compile(r"payable payment|bill payment", re.I)


@dataclass
class SameDayBills:
    supplier: str
    when: date
    amount: float
    account: str


SAME_DAY_PAID_DAYS = 60      # a bill's payment is looked for from its date to 60 days after


def same_day_bills(engagement_id: str, tb_records, db: Session, minimum: float = BILL_DIRECT_MIN) -> List[SameDayBills]:
    from backend.app.models.database import MasterCOA
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.sop.common import code_matcher, ledger_rows
    code_of = code_matcher(ChartLookup.gl_account_codes(list(tb_records)))
    pl = {c.std_code for c in db.query(MasterCOA).filter(MasterCOA.financial_class == "Profit and Loss")}
    banks = {c.std_code for c in db.query(MasterCOA).filter(MasterCOA.category == "Cash at bank and in hand")}
    seen: Dict[tuple, List[str]] = {}
    names: Dict[tuple, Tuple[str, str]] = {}
    paid: Dict[Tuple[str, float], List[date]] = {}
    for t in ledger_rows(engagement_id, db):
        net = float(t.debit_amount or 0) - float(t.credit_amount or 0)
        if PAID_SOURCE.search(t.source or "") and code_of(t.raw_account_name) in banks and net < 0:
            key = (_contact_key(re.sub(r"^payment:\s*", "", (t.description or "").split(" - ")[0], flags=re.I)), round(-net, 2))
            if t.transaction_date:
                paid.setdefault(key, []).append(t.transaction_date)
            continue
        if not t.transaction_date or net < minimum or not BILL_SOURCE.search(t.source or "") or code_of(t.raw_account_name) not in pl:
            continue
        supplier = _contact_key((t.description or "").split(" - ")[0])
        if not supplier:
            continue
        key = (supplier, t.transaction_date, round(net, 2))
        seen.setdefault(key, []).append((t.reference or "").strip().lower())
        names[key] = ((t.description or "").split(" - ")[0].strip(), t.raw_account_name)
    def paid_near(k) -> int:
        return sum(1 for d in paid.get((k[0], k[2]), []) if 0 <= (d - k[1]).days <= SAME_DAY_PAID_DAYS)
    return [SameDayBills(names[k][0], k[1], k[2], names[k][1]) for k, refs in seen.items()
            if len(refs) >= 2 and 1 <= paid_near(k) < len(refs)]


# ------------------------------------------------------------------------------------------------------------------
# A contact's ledger under its point, so the reviewer can see where the transactions went: every bill, payment and direct payment for the contact, one row per
# document with the accounts it touches.
# ------------------------------------------------------------------------------------------------------------------
BILL_PAYMENT_SOURCES = {"payable payment", "supplier payment", "payment"}   # and every 'bill payment (...)'


def contact_ledger(engagement_id: str, contacts: List[str], db: Session, limit: int = 500) -> List[Dict]:
    """For each contact: its documents in the ledger, oldest first: date, type (bill, paid a bill, direct payment or
    the ledger's own type), number, gross amount, and the accounts each line went to."""
    wanted = {_contact_key(c): c for c in contacts if _contact_key(c)}
    docs: Dict[str, Dict[Tuple, Dict]] = {k: {} for k in wanted}
    for tx in db.execute(select(GLTransaction).where(GLTransaction.engagement_id == engagement_id)).scalars():
        key = _contact_key((tx.description or "").split(" - ")[0])
        if key not in wanted:
            continue
        source = (tx.source or "").strip()
        low = source.lower()
        kind = ("bill" if low in DOCUMENT_SOURCES["supplier"] else "invoice" if low in DOCUMENT_SOURCES["customer"]
                else "direct payment" if low in DIRECT_SOURCES["supplier"] else "direct receipt"
                if low in DIRECT_SOURCES["customer"] else "paid a bill" if low in BILL_PAYMENT_SOURCES
                or low.startswith("bill payment") else "receipt for an invoice" if low.startswith("invoice payment")
                else low or "other")
        doc = docs[key].setdefault((tx.transaction_date, str(tx.reference or "").strip(), source), {
            "date": tx.transaction_date.isoformat() if tx.transaction_date else None, "type": kind, "source": source,
            "number": str(tx.reference or "").strip(), "amount": 0.0, "accounts": []})
        doc["amount"] = round(max(doc["amount"], float(tx.debit_amount or 0), float(tx.credit_amount or 0)), 2)
        if tx.raw_account_name and tx.raw_account_name not in doc["accounts"]:
            doc["accounts"].append(tx.raw_account_name)
    out = []
    for key, name in wanted.items():
        rows = sorted(docs[key].values(), key=lambda d: d["date"] or "")
        counts: Dict[str, int] = {}
        for d in rows:
            counts[d["type"]] = counts.get(d["type"], 0) + 1
        out.append({"contact": name, "counts": counts, "documents": rows[:limit], "more": max(len(rows) - limit, 0)})
    return out


def point_contacts(source_row_ref: str, details: str) -> List[str]:
    """The contacts a duplicates point is about: 'supplier Klaviyo' names one; the summary point lists them as
    'Apple (11 bill(s) and 78 direct payment(s)); ...'."""
    ref = (source_row_ref or "").strip()
    for side in ("supplier ", "customer "):
        if ref.startswith(side):
            return [ref[len(side):].strip()]
    if ref == "Suppliers with bills and direct payments":
        return [m.strip() for m in re.findall(r"(?:^|; )([^;]+?) \(\d+ (?:bill|invoice)\(s\)", details or "")]
    return []
