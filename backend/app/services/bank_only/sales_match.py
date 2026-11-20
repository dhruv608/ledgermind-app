"""
Raw data route, step 3: match customer receipts to sales invoices, customer by customer.

Rules, strongest first, within one customer:
  A  the bank line quotes the invoice number(s) and the amount equals them           clear     automatic
  B  the receipt equals one open invoice exactly, and no other open one has that amount   clear     automatic
  C  the receipt equals the total of one set of open invoices, and only one set does    clear     automatic
  F  the receipt is within the tolerance of one open invoice                           probable  person confirms
  E  oldest open invoices first until the receipt runs out (last one part-paid)        probable  person confirms
  G  nothing fits (no customer, or no open invoice)                                    none      query the client
(D, "March statement" references, is not used: the inputs carry no statement wording. F is tried before E: it names
one invoice, E only a running order.)
Never: an invoice dated after the receipt (unless the line quotes it); a receipt moved to another customer to make a match work.
"""

import re
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Tuple

from backend.app.services.bank_only.bank_sort import CUSTOMER, BankSort, _words
from backend.app.services.bank_only.input_files import BankLine, Invoice, number_key

TOLERANCE = 5.0              # write-off tolerance (default £5, from the Engagement Setup)
CLEAR = {"A", "B", "C", "X"}         # X: a bill paid in another currency (amount within the exchange difference)
_LEGAL = re.compile(r"\b(ltd|limited|plc|llp|co|the|uk)\b\.?")


def customer_key(name: str) -> str:
    """One customer however written: 'ABC Ltd', 'A.B.C. Limited' and 'ABC LTD' are the same."""
    text = _LEGAL.sub(" ", (name or "").lower().replace(".", ""))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


@dataclass
class OpenItem:
    invoice: Invoice
    brought_forward: bool                 # an unpaid invoice from an earlier year
    paid: float = 0.0
    allocations: List[Tuple[BankLine, float, str]] = field(default_factory=list)   # (receipt, amount, rule)

    @property
    def outstanding(self) -> float:
        return round(self.invoice.gross - self.paid, 2)

    @property
    def marked_received(self) -> bool:
        """The invoicing record (Dext 'Received Amount') shows it paid in full."""
        return self.invoice.received is not None and abs(self.invoice.received - self.invoice.gross) < 0.005

    @property
    def status(self) -> str:
        if self.outstanding <= 0.005:
            return "Paid"
        return "Part-paid" if self.paid > 0.005 else "Unpaid"

    @property
    def clear(self) -> bool:
        """Every allocation on it was a clear match (only clear matches can name an invoice as outstanding)."""
        return all(rule in CLEAR for _, _, rule in self.allocations)


@dataclass
class Receipt:
    line: BankLine
    customer: str                         # the customer it was linked to ("" = unidentified)
    allocated: float = 0.0
    rules: List[str] = field(default_factory=list)
    note: str = ""
    # A bill paid in another currency: the bank paid this much more (+) or less (-) than the bill in pounds, an
    # exchange loss or gain, not money left unexplained
    fx: float = 0.0

    @property
    def amount(self) -> float:
        """Money in for a customer receipt; money out for a supplier payment (the bill matching uses the same rules)."""
        return self.line.money_in or self.line.money_out

    @property
    def unallocated(self) -> float:
        return round(self.amount - self.allocated - self.fx, 2)

    @property
    def status(self) -> str:
        if self.unallocated <= 0.005:
            return "Allocated"
        return "Part-allocated" if self.allocated > 0.005 else "Unallocated"

    @property
    def needs_person(self) -> bool:
        return any(r not in CLEAR for r in self.rules) or self.unallocated > 0.005


@dataclass
class SalesMatch:
    items: List[OpenItem]
    receipts: List[Receipt]

    def outstanding(self, brought_forward: Optional[bool] = None) -> List[OpenItem]:
        return [i for i in self.items if i.outstanding > 0.005
                and (brought_forward is None or i.brought_forward == brought_forward)]

    def debtors(self) -> float:
        return round(sum(i.outstanding for i in self.outstanding()), 2)

    def customers(self) -> List[Dict]:
        """The customer summary."""
        rows: Dict[str, Dict] = {}
        for i in self.items:
            k = customer_key(i.invoice.party)
            r = rows.setdefault(k, {"customer": i.invoice.party, "brought_forward": 0.0, "invoiced": 0.0,
                                    "credit_notes": 0.0, "received": 0.0})
            if i.brought_forward:
                r["brought_forward"] += i.invoice.gross
            elif i.invoice.gross < 0:
                r["credit_notes"] += i.invoice.gross
            else:
                r["invoiced"] += i.invoice.gross
        for rc in self.receipts:
            if rc.customer:
                k = customer_key(rc.customer)
                rows.setdefault(k, {"customer": rc.customer, "brought_forward": 0.0, "invoiced": 0.0,
                                    "credit_notes": 0.0, "received": 0.0})["received"] += rc.amount
        for r in rows.values():
            pos = round(r["brought_forward"] + r["invoiced"] + r["credit_notes"] - r["received"], 2)
            r["position"] = pos
            r["status"] = "Settled" if abs(pos) < 0.005 else ("Underpaid" if pos > 0 else "Overpaid")
        return sorted(rows.values(), key=lambda r: r["customer"].lower())


def match_sales(invoices: List[Invoice], sorted_bank: BankSort,
                brought_forward: Optional[List[Invoice]] = None) -> SalesMatch:
    items = [OpenItem(i, True) for i in (brought_forward or [])] + [OpenItem(i, False) for i in invoices]
    by_customer: Dict[str, List[OpenItem]] = {}
    for it in items:
        by_customer.setdefault(customer_key(it.invoice.party), []).append(it)
    by_number: Dict[str, List[OpenItem]] = {}
    for it in items:
        key = number_key(it.invoice.number)
        if key:
            by_number.setdefault(key, []).append(it)

    receipts, unknown = [], []
    for s in sorted(sorted_bank.lines, key=lambda s: s.line.when):
        if s.head != CUSTOMER:
            continue
        quoted = _quoted(s.line, by_number)
        customer = quoted[0].invoice.party if quoted else s.customer
        rc = Receipt(s.line, customer)
        receipts.append(rc)
        if not customer:
            unknown.append(rc)
            continue
        # An invoice the receipt quotes may be dated after it (paid a few days early)
        open_items = [it for it in _pool(by_customer, customer) if it.outstanding > 0.005 and (
            it.invoice.when <= s.line.when or (it in quoted and (it.invoice.when - s.line.when).days <= 31))]
        _allocate(rc, open_items, [q for q in quoted if q in open_items])

    # The payer names learnt from the receipts already linked (a word on a linked receipt's line that is not in the
    # customer's name then names that customer on other lines); a word used for two customers names neither
    aliases: Dict[str, set] = {}
    for rc in receipts:
        if rc.customer and rc.allocated > 0.005:
            own = set(_words(rc.customer))
            for w in set(_words(rc.line.description)) - own:
                aliases.setdefault(w, set()).add(rc.customer)
    for rc in unknown:
        named = {next(iter(c)) for w, c in aliases.items() if len(c) == 1 and w in _words(rc.line.description)}
        if len(named) == 1:
            rc.customer = named.pop()
            rc.note = "customer recognised from an earlier receipt's payer name"
            open_items = [it for it in _pool(by_customer, rc.customer)
                          if it.outstanding > 0.005 and it.invoice.when <= rc.line.when]
            _allocate(rc, open_items, [])
            rc.rules = [r if r not in CLEAR else "F" for r in rc.rules]      # a learnt name: a person confirms
        else:
            rc.rules.append("G")
            rc.note = "customer not identified"

    # Second pass: a receipt still not placed (customer not identified, or nothing open under the name on the bank
    # line, which is often the person paying, not the customer invoiced) goes to the one open invoice, or the one set
    # of one customer's open invoices, that it equals; probable, so a person confirms (rule F)
    for rc in receipts:
        if rc.unallocated <= 0.005 or rc.allocated > 0.005:
            continue
        _place_by_amount(rc, items)
    _instalments(receipts, items)
    return SalesMatch(items, receipts)


def _quoted(line: BankLine, by_number: Dict[str, List["OpenItem"]]) -> List["OpenItem"]:
    """The invoices whose numbers the bank line quotes. A number shared by two invoices ('BD200546' and
    'BD200546a') counts only for the one whose customer is also named on the line."""
    out = []
    for ref in line.refs:
        found = by_number.get(ref, [])
        if len(found) > 1:
            found = [it for it in found if any(w in line.description.lower() for w in _words(it.invoice.party))]
        if len(found) == 1:
            out.append(found[0])
    return out


def _pool(by_customer: Dict[str, List["OpenItem"]], customer: str) -> List["OpenItem"]:
    """The customer's open items; with a name that starts the other ('John' and 'John Smith') both are one payer."""
    key = customer_key(customer)
    out = list(by_customer.get(key, []))
    for k, its in by_customer.items():
        if k != key and k and (key.startswith(k + " ") or k.startswith(key + " ")):
            out += its
    return out


def _place_by_amount(rc: "Receipt", items: List["OpenItem"]) -> None:
    window = [it for it in items if it.outstanding > 0.005 and it.invoice.when <= rc.line.when
              and (rc.line.when - it.invoice.when).days <= 180]
    same = [it for it in window if abs(it.outstanding - rc.unallocated) < 0.005]
    # Several of the same amount: the one the invoicing record (Dext) shows as received, if only one is; else the one
    # whose customer the bank line names by any part of the name (people pay as 'J Smith' for John Smith)
    if len(same) > 1:
        same = [it for it in same if it.marked_received] if sum(it.marked_received for it in same) == 1 else same
    if len(same) > 1:
        named = [it for it in same if _named_on(it.invoice.party, rc.line.description)]
        same = named if len(named) == 1 else same
    if len(same) == 1:
        it = same[0]
        rc.customer = it.invoice.party
        _pay(rc, it, it.outstanding, "F")
        rc.note = f"placed by amount on invoice {it.invoice.number} ({it.invoice.party}): please confirm"
        return
    groups: List[List[OpenItem]] = []
    by_party: Dict[str, List[OpenItem]] = {}
    for it in window:
        by_party.setdefault(customer_key(it.invoice.party), []).append(it)
    for its in by_party.values():
        groups += _sets_adding_to(sorted(its, key=lambda i: i.invoice.when)[:14], rc.unallocated, max_size=4)
        if len(groups) > 1:
            return
    if len(groups) == 1:
        rc.customer = groups[0][0].invoice.party
        for it in groups[0]:
            _pay(rc, it, it.outstanding, "F")
        rc.note = f"placed by amount on invoices {', '.join(i.invoice.number for i in groups[0])}: please confirm"


def _named_on(party: str, description: str) -> bool:
    """Any distinctive part of the customer's name (first name or surname) is a whole word on the bank line."""
    desc = description.lower()
    return any(len(w) >= 3 and re.search(rf"\b{re.escape(w)}\b", desc) for w in _words(party))


def _instalments(receipts: List["Receipt"], items: List["OpenItem"]) -> None:
    """A job paid in two parts (deposit and balance): two receipts not yet placed,
    within 30 days of each other and from the same payer (a word in common on both lines, or the customer named), that
    together equal one open invoice dated up to 10 days after the first or 60 days before it; only when one invoice
    fits. Probable: a person confirms (rule F)."""
    loose = sorted((r for r in receipts if r.allocated <= 0.005 and r.unallocated > 0.005), key=lambda r: r.line.when)
    used: set = set()
    for i, a in enumerate(loose):
        if id(a) in used:
            continue
        for b in loose[i + 1:]:
            if id(b) in used or (b.line.when - a.line.when).days > 30:
                continue
            total = round(a.unallocated + b.unallocated, 2)
            fits = [it for it in items if it.outstanding > 0.005 and abs(it.outstanding - total) < 0.005
                    and -60 <= (it.invoice.when - a.line.when).days <= 10]
            same_payer = bool(set(_words(a.line.description)) & set(_words(b.line.description)))
            fits = [it for it in fits if same_payer or (_named_on(it.invoice.party, a.line.description)
                                                       and _named_on(it.invoice.party, b.line.description))]
            if len(fits) == 1:
                it = fits[0]
                for rc in (a, b):
                    rc.customer = it.invoice.party
                    _pay(rc, it, rc.unallocated, "F")
                    rc.note = f"one of two payments of invoice {it.invoice.number} ({it.invoice.party}): please confirm"
                used.update((id(a), id(b)))
                break


def _pay(rc: Receipt, it: OpenItem, amount: float, rule: str) -> None:
    amount = round(min(amount, it.outstanding, rc.unallocated), 2)
    if amount <= 0:
        return
    it.paid = round(it.paid + amount, 2)
    it.allocations.append((rc.line, amount, rule))
    rc.allocated = round(rc.allocated + amount, 2)
    if "G" in rc.rules:
        rc.rules.remove("G")            # placed after all: no longer "nothing fits"
    if rule not in rc.rules:
        rc.rules.append(rule)


def _allocate(rc: Receipt, open_items: List[OpenItem], quoted: List[OpenItem]) -> None:
    amount = rc.amount
    oldest = sorted(open_items, key=lambda it: (it.invoice.when, it.invoice.number))
    if not oldest:
        rc.rules.append("G")
        rc.note = "no open invoice for this customer"
        return

    # A: the invoices quoted on the line, and the amount equals them (within tolerance)
    if quoted and abs(sum(q.outstanding for q in quoted) - amount) <= TOLERANCE:
        for q in sorted(quoted, key=lambda it: it.invoice.when):
            _pay(rc, q, q.outstanding, "A")
        return

    # B: exactly one open invoice for this amount
    same = [it for it in oldest if abs(it.outstanding - amount) < 0.005]
    if len(same) > 1 and sum(it.marked_received for it in same) == 1:
        same = [it for it in same if it.marked_received]
    if len(same) == 1:
        _pay(rc, same[0], amount, "B")
        return

    # C: one set of open invoices adds up to the receipt (several equal-amount invoices give several sets: not C)
    if len(same) == 0:
        sets = _sets_adding_to(oldest[:18], amount)
        if len(sets) == 1:
            for it in sets[0]:
                _pay(rc, it, it.outstanding, "C")
            return

    # F: within tolerance of one open invoice (fees, small differences)
    near = [it for it in oldest if 0.005 <= abs(it.outstanding - amount) <= TOLERANCE]
    if len(near) == 1 and not same:
        _pay(rc, near[0], amount, "F")
        rc.note = f"£{abs(near[0].outstanding - amount):,.2f} difference to invoice {near[0].invoice.number}"
        return

    # E: oldest first (quoted invoices first when the amount did not fit them exactly); invoices the invoicing
    #    record shows as paid come before ones it does not, and this year's before ones brought forward
    order = sorted([i for i in oldest if i not in quoted],
                   key=lambda i: (not i.marked_received, i.brought_forward, i.invoice.when))
    for it in sorted(quoted, key=lambda i: i.invoice.when) + order:
        if rc.unallocated <= 0.005:
            break
        _pay(rc, it, rc.unallocated, "E")
    if rc.unallocated > 0.005:
        rc.note = f"£{rc.unallocated:,.2f} more than the open invoices: overpaid, or an invoice we do not have"


def _sets_adding_to(items: List[OpenItem], amount: float, max_size: int = 6) -> List[List[OpenItem]]:
    """Every set of 2 to max_size open invoices whose outstanding amounts add up to the receipt (stops at 2 sets:
    two answers already mean it is not a clear match)."""
    found: List[List[OpenItem]] = []
    target = round(amount * 100)
    cents = [round(it.outstanding * 100) for it in items]
    for size in range(2, min(max_size, len(items)) + 1):
        for combo in combinations(range(len(items)), size):
            if sum(cents[i] for i in combo) == target:
                found.append([items[i] for i in combo])
                if len(found) > 1:
                    return found
    return found
