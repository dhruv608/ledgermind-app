"""
Raw data route, step 5: write the double entries and produce the GL and trial balance. Year-end adjustments (depreciation, accruals, tax) are not made here: they follow in the
normal review and journals, as for a Xero/QuickBooks client.

  opening balances    last year's closing trial balance, by firm code
  sales invoices      Dr trade debtors (gross) / Cr sales (net) and Cr VAT (VAT registered)
  purchase bills      Dr cost by its head (gross; net and Dr VAT when VAT registered) / Cr trade creditors
  bank, money in      Dr bank / Cr trade debtors for the part matched to invoices, the rest by its head
  bank, money out     Cr bank / Dr trade creditors for the part matched to bills, the rest by its head
Anything not yet known (unsorted lines, receipts with no invoice, payments with no bill) goes to suspense 9999 with
its question, never to sales or a cost by default.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from backend.app.services.bank_only.bank_sort import (CUSTOMER, HEAD_CODES, SUPPLIER, TRANSFERS, UNSORTED, _RULES,
                                                CHANNEL_WORDS, PROPERTY_HOW, BankSort, SortedLine, _name_matches)
from backend.app.services.bank_only.bills_match import BillsMatch
from backend.app.services.bank_only.categories import DIRECTORS_LOAN, code_for, paid_by_director
from backend.app.services.bank_only.input_files import Invoice, RawInput
from backend.app.services.bank_only.sales_match import SalesMatch

SALES, DEBTORS, CREDITORS, VAT, BANK, SUSPENSE = 0, 4400, 5200, 5300, 4800, 9999
EXCHANGE = 3562         # foreign exchange gains/losses: a bill in another currency paid for a little more or less
NAMES = {SALES: "Sales", DEBTORS: "Trade debtors", CREDITORS: "Trade creditors", VAT: "VAT", BANK: "Bank current account",
         SUSPENSE: "Suspense", 1400: "Materials / purchases", 3230: "Vehicle running costs", 3260: "Insurance",
         3320: "Subscriptions", 3301: "Accountancy fees", 3240: "Computer software", 3290: "Telephone and internet",
         3351: "Bank charges", 3360: "Donations", 5310: "Corporation tax", 5320: "PAYE and NI", 5330: "Net wages",
         5400: "Directors loan account", 900: "Bank interest receivable", TRANSFERS: "Transfers", EXCHANGE: "Foreign exchange gains/losses"}


@dataclass
class Entry:
    when: date
    code: int
    debit: float
    credit: float
    narrative: str
    source: str                 # where it comes from: "opening", "sales BD200576", "bill row 12", "bank row 40"


@dataclass
class Ledger:
    entries: List[Entry] = field(default_factory=list)
    # Client questions (plain English, the evidence line, no accounting terms):
    # {key, group: explain / confirm / documents, text}
    questions: List[Dict[str, str]] = field(default_factory=list)
    bill_heads: Dict[int, Tuple[str, int]] = field(default_factory=dict)     # bill row -> (head, code)

    def ask(self, key: str, group: str, text: str) -> None:
        self.questions.append({"key": key, "group": group, "text": text})

    def add(self, when: date, code: int, amount: float, narrative: str, source: str) -> None:
        """amount: debit positive, credit negative."""
        amount = round(amount, 2)
        if abs(amount) >= 0.005:
            self.entries.append(Entry(when, code, max(amount, 0.0), max(-amount, 0.0), narrative, source))

    def trial_balance(self) -> Dict[int, float]:
        tb: Dict[int, float] = {}
        for e in self.entries:
            tb[e.code] = round(tb.get(e.code, 0.0) + e.debit - e.credit, 2)
        return dict(sorted(tb.items()))

    def out_of_balance(self) -> float:
        return round(sum(e.debit - e.credit for e in self.entries), 2)


def bill_head(bill: Invoice, paid_by: Optional[SortedLine] = None, materials: int = 1100,
              no_bill: int = 1400) -> Tuple[str, int]:
    """What a Dext bill is: Dext's category when it has one the firm's chart knows (the accountant's starting head,
    which he checks); else the firm's rules on the supplier and description, else on the bank line that paid it
    ('Tesco Pay At Pump' -> vehicle running costs); unknown -> suspense, for the accountant. 'Directors Current
    Account' says who paid, not what for: the cost goes by the rules (the director's loan is credited separately)."""
    code = code_for(bill.category, materials)
    if code is not None and not paid_by_director(bill.category) and code != SALES:
        return bill.category, code
    texts = [f"{bill.party} {bill.description}"] + ([paid_by.line.description] if paid_by is not None else [])
    for text in texts:
        for pattern, head, way in _RULES:
            if way != "in" and pattern.search(text):
                code = no_bill if head == "Purchases (no bill)" else HEAD_CODES.get(head)   # goods: the client's purchases code
                if code is not None and head not in ("Net wages", "Corporation tax paid", "VAT paid", "PAYE and NI paid"):
                    return head, code
    return UNSORTED, SUSPENSE


def build_ledger(raw: RawInput, bank: BankSort, sales: SalesMatch, bills: BillsMatch,
                 opening: Optional[Dict[int, float]] = None, vat_registered: bool = False,
                 bill_heads: Optional[Dict[int, str]] = None) -> Ledger:
    """bill_heads: the accountant's choice of head for a bill (bill row -> head), over the firm's rules."""
    led = Ledger()
    start = (raw.year_end.replace(year=raw.year_end.year - 1) + timedelta(days=1)) if raw.year_end else None

    # Opening balances (last year's closing trial balance)
    for code, amount in (opening or {}).items():
        led.add(start, code, amount, "Opening balance", "opening")

    # Sales invoices
    for inv in raw.sales:
        vat = inv.vat if vat_registered else 0.0
        led.add(inv.when, DEBTORS, inv.gross, f"{inv.party} {inv.number}", f"sales {inv.number}")
        led.add(inv.when, SALES, -(inv.gross - vat), f"{inv.party} {inv.number}", f"sales {inv.number}")
        led.add(inv.when, VAT, -vat, f"Output VAT {inv.number}", f"sales {inv.number}")

    # Purchase bills, each to its cost by head
    paid_by: Dict[int, SortedLine] = {id(s.bill): s for s in bank.lines if s.bill is not None}
    for b in raw.purchases:
        chosen = (bill_heads or {}).get(b.row)
        if isinstance(chosen, tuple):        # (head, code) chosen by the accountant: any code of the firm's chart
            head, code = chosen
        elif chosen:
            head, code = chosen, HEAD_CODES.get(chosen) if HEAD_CODES.get(chosen) is not None else SUSPENSE
        else:
            head, code = bill_head(b, paid_by.get(id(b)), raw.materials_code, raw.no_bill_code)
        if head == "Purchases (no bill)":
            code = raw.no_bill_code
        led.bill_heads[b.row] = (head, code)
        vat = b.vat if vat_registered else 0.0
        src = f"bill row {b.row}"
        led.add(b.when, code, b.gross - vat, f"{b.party} {b.number}".strip(), src)
        led.add(b.when, VAT, vat, f"Input VAT {b.party}", src)
        # Paid by the director personally (Dext 'Directors Current Account'): owed to the director, not a creditor
        owed_to = DIRECTORS_LOAN if paid_by_director(b.category) else CREDITORS
        led.add(b.when, owed_to, -b.gross, f"{b.party} {b.number}".strip() +
                (" (paid by the director)" if owed_to == DIRECTORS_LOAN else ""), src)
        if code == SUSPENSE and b.gross >= 0.005:
            led.ask(f"bill:{b.row}", "explain", f"We have a bill from {b.party} for £{b.gross:,.2f} dated "
                                                f"{b.when:%d %B %Y}. What was it for?")

    # Bank: receipts against debtors, payments against creditors, the rest by head; each account on its own code
    bank_code = {a.name: a.code for a in raw.accounts}
    receipt_of = {id(r.line): r for r in sales.receipts}
    payment_of = {id(p.line): p for p in bills.payments}
    unknown: List[Tuple[str, SortedLine, float]] = []       # lines in suspense, asked about after the loop
    one_sided: List[Tuple[str, SortedLine, float]] = []     # transfers with no other side, asked about after the loop
    end = raw.year_end
    starts = {a.name: a.starts for a in raw.accounts if a.starts}
    for s in bank.lines:
        b = s.line
        # Lines after the year end are next year's: they stay on the Books tab (marked outside the year) for the
        # accruals and the cut-off, never as this year's income or costs. Lines before a year counted back from the
        # year end are kept (a first period can run up to 18 months)
        if end and b.when > end:
            continue
        # Lines before the year that last year's TB already holds (input_files: the account's balance on the day
        # before the year agrees with it)
        if b.account in starts and b.when < starts[b.account]:
            continue
        src = f"bank row {b.ref or b.row}"
        key = f"bank:{b.ref or b.row}"
        amount = b.money_in - b.money_out
        led.add(b.when, bank_code.get(b.account, BANK), amount, b.description, src)
        if b.money_in > 0 and id(b) in receipt_of:
            rc = receipt_of[id(b)]
            led.add(b.when, DEBTORS, -rc.allocated, b.description, src)
            if rc.unallocated > 0.005:
                led.add(b.when, SUSPENSE, -rc.unallocated, f"Money in, no invoice: {b.description}", src)
                led.ask(key, "explain", f"We can see £{rc.unallocated:,.2f} paid in on {b.when:%d %B %Y} "
                                                    f"(\"{b.description}\"). What was this payment for?")
            continue
        if b.money_out > 0 and id(b) in payment_of:
            p = payment_of[id(b)]
            led.add(b.when, CREDITORS, p.allocated, b.description, src)
            led.add(b.when, EXCHANGE, p.fx, f"Exchange difference: {b.description}", src)
            if p.unallocated > 0.005:
                led.add(b.when, SUSPENSE, p.unallocated, f"Paid with no bill: {b.description}", src)
                led.ask(key, "documents", f"Please send the invoice for £{p.unallocated:,.2f} paid on "
                                                      f"{b.when:%d %B %Y} (\"{b.description}\").")
            continue
        code = _bank_code(s, raw.no_bill_code)
        led.add(b.when, code, -amount, f"{s.head}: {b.description}", src)
        if code == TRANSFERS and s.pair is None:
            one_sided.append((key, s, amount))
        if code == SUSPENSE:
            unknown.append((key, s, amount))
    _ask_unknown(led, unknown)
    _ask_one_sided(led, one_sided)
    _ask_never_paid(led, bills, bank)
    return led


# Below this a supplier's unpaid bills are not worth a question (a £4.99 eBay book)
NEVER_PAID_MIN = 100.0


def _ask_never_paid(led: Ledger, bills: BillsMatch, bank: BankSort) -> None:
    """A supplier with bills this year but no payment to it on any bank statement: paid in cash, from an account we do not have, or by the director, or still owed. One question per
    supplier, since each answer moves the bills off trade creditors to a different place."""
    from backend.app.services.bank_only.sales_match import customer_key
    by: Dict[str, List] = {}
    for it in bills.items:
        if not it.brought_forward and not paid_by_director(it.invoice.category):
            by.setdefault(customer_key(it.invoice.party), []).append(it)
    for key, its in by.items():
        if not key or any(it.paid > 0.005 for it in its):
            continue
        total = round(sum(it.outstanding for it in its), 2)
        party = its[0].invoice.party
        if total < NEVER_PAID_MIN or any(s.line.money_out > 0 and _name_matches(party, s.line.description)
                                         for s in bank.lines):
            continue
        first, last = min(it.invoice.when for it in its), max(it.invoice.when for it in its)
        when = f"dated {first:%d %B %Y}" if len(its) == 1 else f"dated {first:%d %B %Y} to {last:%d %B %Y}"
        what, were = ("a bill", "Was it") if len(its) == 1 else (f"{len(its)} bills", "Were they")
        led.ask(f"unpaid:{key}", "confirm", f"We have {what} from {party} for £{total:,.2f} {when}, but no payment "
                                            f"to {party} on the bank statements. {were} paid in cash, from another "
                                            f"account or card, or personally by a director, or still owed at the year end?")


# A payment to a person by bank transfer: their name and the bank's long reference ('JOHN SMITH 100000001148873855',
# 'MR JOHN SMITH 300000001487818291 SALARY')
TO_A_PERSON = re.compile(r"^\s*(?:(?:mr|mrs|ms|miss|dr)\.?\s+)?[a-z][a-z'.-]+(?:\s+[a-z][a-z'.-]+){1,3}\s+\d{9,}", re.I)
GROUP_FROM = 3          # a payee with this many unknown lines gets one question for all of them
LARGE_PAYMENT = 10000.0  # money out to one payee from this much may have bought property, a vehicle or equipment
SOLICITORS = re.compile(r"\b(solicitors?|llp|law|legal|conveyanc\w*|notar\w*|completion)\b", re.I)


def _asset_question(example: str) -> str:
    """The extra question for a large payment: a fixed asset bought (its completion statement or invoice decides
    the cost, stamp duty and fees), a loan repaid, or something else."""
    if SOLICITORS.search(example):
        return (" This looks like a payment to solicitors: was it to buy a property? If so, please send the "
                "completion statement (the price, stamp duty and legal fees are all part of the property's cost).")
    return (" If it bought property, a vehicle or equipment, please send the completion statement or purchase "
            "invoice (it is a fixed asset); if it repaid a loan, please send the loan statement.")


def _ask_one_sided(led: Ledger, one_sided: List[Tuple[str, SortedLine, float]]) -> None:
    """Transfers with no other side in the statements we have: one request per other account or card with several
    (10 repayments to one card are one request for the card's statements, not 10), else one per line."""
    from backend.app.services.bank_only.books import payee_key
    groups: Dict[str, List[Tuple[str, SortedLine, float]]] = {}
    for item in one_sided:
        groups.setdefault(payee_key(item[1].line.description), []).append(item)
    for name, items in groups.items():
        if name and len(items) >= GROUP_FROM:
            first, last = min(i[1].line.when for i in items), max(i[1].line.when for i in items)
            net = round(sum(i[2] for i in items), 2)
            example = items[0][1].line.description
            led.ask(f"transfer:{name}", "documents",
                    f"We can see {len(items)} transfers like \"{example}\" between {first:%d %B %Y} and "
                    f"{last:%d %B %Y} (£{abs(net):,.2f} {'in' if net > 0 else 'out'} in all), but not the other side. "
                    f"Please send the statements of the account or card they came from or went to.")
            continue
        for key, s, amount in items:
            b = s.line
            led.ask(key, "documents", f"We can see £{abs(amount):,.2f} moved {'into' if amount > 0 else 'out of'} the "
                                     f"{b.account or 'bank'} account on {b.when:%d %B %Y} (\"{b.description}\"), but not "
                                     f"the other side. Please send the statement of the account it came from or went to.")


def _ask_property(led: Ledger, key: str, s: SortedLine, amount: float) -> None:
    """A property company's large one-off amount: what it was decides where it goes (a sale of a property held to
    sell is turnover, of a rental property a disposal; a deposit before completion is owed to the buyer; building or
    buying a property to sell is stock, a rental one a fixed asset)."""
    b = s.line
    if amount > 0:
        led.ask(key, "explain", f"We can see £{amount:,.2f} paid in on {b.when:%d %B %Y} (\"{b.description}\"). Was this "
                                f"from selling a property (which one, and was it held to sell or to rent out?), a "
                                f"deposit on a sale not yet completed, a loan, or something else? If a property was "
                                f"sold, please send the completion statement.")
    else:
        led.ask(key, "explain", f"We can see £{-amount:,.2f} paid out on {b.when:%d %B %Y} (\"{b.description}\"). Was "
                                f"this to buy or build a property (which one, and is it to sell or to rent out?), "
                                f"repairs, a loan repaid, or something else? Please send the completion statement or "
                                f"the builder's invoices.")


def _ask_unknown(led: Ledger, unknown: List[Tuple[str, SortedLine, float]]) -> None:
    """The lines in suspense, put to the client: one question per payee with several (19 payments to the same
    person are one question, not 19), else one per line. A person paid by transfer is asked about as a person
    (wages, a subcontractor, the director?)."""
    from backend.app.services.bank_only.books import payee_key
    groups: Dict[str, List[Tuple[str, SortedLine, float]]] = {}
    for item in unknown:
        if item[1].how.startswith(PROPERTY_HOW):
            _ask_property(led, *item)
            continue
        groups.setdefault(payee_key(item[1].line.description), []).append(item)
    for name, items in groups.items():
        if name and len(items) >= GROUP_FROM:
            first, last = min(i[1].line.when for i in items), max(i[1].line.when for i in items)
            out = [i for i in items if i[2] < 0]
            way = "payments to" if len(out) >= len(items) - len(out) else "receipts from"
            total = sum(abs(i[2]) for i in items)
            example = items[0][1].line.description
            person = bool(TO_A_PERSON.search(example))
            led.ask(f"payee:{name}", "explain",
                    f"We can see {len(items)} {way} \"{example}\" totalling £{total:,.2f} between {first:%d %B %Y} and "
                    f"{last:%d %B %Y}. " + ("Who is this person, and what were they paid for (wages, work as a "
                                            "subcontractor, the director, or something else)?" if person else
                                            "What were these for?")
                    + (_asset_question(example) if way == "payments to" and not person
                       and sum(-i[2] for i in out) >= LARGE_PAYMENT else ""))
            continue
        for key, s, amount in items:
            b = s.line
            led.ask(key, "explain", f"We can see £{abs(amount):,.2f} {'paid in' if amount > 0 else 'paid out'} "
                                    f"on {b.when:%d %B %Y} (\"{b.description}\"). What was this for?"
                                    + (_asset_question(b.description) if -amount >= LARGE_PAYMENT else ""))


def _bank_code(s: SortedLine, no_bill: int = 1400) -> int:
    """The firm code for a bank line that is not matched to an invoice or bill."""
    if s.head == "Refund received":
        # A refund from a shop the firm's rules know reverses that cost; any other refund waits in suspense
        for pattern, head, way in _RULES:
            if way == "out" and pattern.search(CHANNEL_WORDS.sub(" ", s.line.description)) and HEAD_CODES.get(head):
                return HEAD_CODES[head]
        return SUSPENSE
    if s.head in (CUSTOMER, SUPPLIER):
        return SUSPENSE          # a receipt or payment the matching could not place
    if s.head == "Purchases (no bill)":
        return no_bill                            # 1400, or 1100 when last year used 1100
    # The line's own code: the head's code, or the one the sorting worked out for this client (a loan or pension on
    # last year's code, a refund on its payee's head); a head the accountant wrote on the statement carries its own
    code = s.code if s.code is not None else HEAD_CODES.get(s.head)
    return code if code is not None else SUSPENSE
