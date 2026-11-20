"""
Raw data route, step 4: match supplier payments to purchase bills, supplier by supplier, with the same rules A to G
as sales (payments out instead of receipts).

  1. a payment step 2 already linked to a Dext bill pays that bill (clear when step 2 was sure, else probable)
  2. a payment that names a supplier but has no bill for its amount is matched within that supplier (A, B, C, F, E)
  3. any other payment out that names a supplier and equals one of its open bills, or one of last year's unpaid bills,
     pays it (step 2 may have read it by a rule: a subscription paid now can be last year's bill, not this year's cost)
A bill in Dext's 'Directors Current Account' was paid by the director personally: settled, never a creditor.
Bills still open at the year end are the trade creditors. A payment with no bill at all keeps its step 2 head (the
cost is recorded directly, with no VAT claimed) and is listed as an invoice to ask for.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

from backend.app.services.bank_only.bank_sort import DIRECTOR, SUPPLIER, UNSORTED, BankSort, SortedLine, _name_matches, _words
from backend.app.services.bank_only.categories import paid_by_director
from backend.app.services.bank_only.input_files import Invoice
from backend.app.services.bank_only.sales_match import OpenItem, Receipt, _allocate, _pay, _pool, customer_key

# Heads a supplier's bill is never paid from (the director, tax, transfers)
_NOT_BILLS = {DIRECTOR, "Corporation tax paid", "VAT paid", "PAYE and NI paid", "Net wages",
              "Transfer between own accounts", "HMRC (check which tax)"}


@dataclass
class BillsMatch:
    items: List[OpenItem]
    payments: List[Receipt]                 # supplier payments matched (or tried) against bills
    no_bill: List[SortedLine]               # payments out with no bill at all: recorded directly by their head

    def outstanding(self, brought_forward: Optional[bool] = None) -> List[OpenItem]:
        return [i for i in self.items if i.outstanding > 0.005
                and (brought_forward is None or i.brought_forward == brought_forward)]

    def creditors(self) -> float:
        return round(sum(i.outstanding for i in self.outstanding()), 2)


def match_bills(bills: List[Invoice], sorted_bank: BankSort,
                brought_forward: Optional[List[Invoice]] = None) -> BillsMatch:
    items = [OpenItem(i, True) for i in (brought_forward or [])] + [OpenItem(i, False) for i in bills]
    for it in items:
        if paid_by_director(it.invoice.category):
            it.paid = it.invoice.gross          # settled by the director personally: owed to him, not a creditor
    by_bill = {id(it.invoice): it for it in items}
    by_supplier: Dict[str, List[OpenItem]] = {}
    for it in items:
        by_supplier.setdefault(customer_key(it.invoice.party), []).append(it)

    payments: List[Receipt] = []
    later: List[SortedLine] = []
    for s in sorted(sorted_bank.lines, key=lambda s: s.line.when):
        b = s.line
        if b.money_out <= 0:
            continue
        # 1. Linked to a bill in step 2
        if s.head == SUPPLIER and s.bill is not None:
            p = Receipt(b, s.bill.party)
            _pay(p, by_bill[id(s.bill)], p.amount, "B" if s.sure else "F")
            if not s.sure:
                p.note = f"matched on amount and date to the {s.bill.party} bill: please confirm"
            payments.append(p)
            continue
        # 2. Names a supplier, but no bill of this amount (a bill in another currency first: paid within days for a
        #    few per cent more or less)
        if s.head == SUPPLIER:
            supplier = s.how.split("pays ", 1)[-1].split(",")[0].strip() if "pays " in s.how else ""
            p = Receipt(b, supplier)
            open_items = [it for it in _pool(by_supplier, supplier) if it.outstanding > 0.005 and it.invoice.when <= b.when]
            if _foreign_bill(p, open_items, s):
                payments.append(p)
                continue
            _allocate(p, open_items, [])
            if p.unallocated > 0.005:
                p.note = f"£{p.unallocated:,.2f} paid to {supplier} with no bill for it: ask for the invoice"
            payments.append(p)
            continue
        later.append(s)

    # 3. Other payments out that name a supplier, or the name its payments carry on this bank (learned: Three's
    #    direct debits say 'H3G'), and equal one of its open bills (this year's or last year's): the nearest bill
    #    before the payment. Then a payment in another currency ('Card 98 USD 24.00 (Rate 0.74375)') with one bill
    #    within the exchange difference, paid within a week of it.
    aliases = _bank_names(items, [s for s in later if s.head not in _NOT_BILLS])
    no_bill: List[SortedLine] = []
    for s in later:
        b = s.line
        if s.head == DIRECTOR:
            # Paid to the director the exact amount of a bill dated within the week before: the company repaying a
            # bill he paid personally
            owed = [it for it in items if it.outstanding > 0.005 and abs(it.outstanding - b.money_out) < 0.005
                    and 0 <= (b.when - it.invoice.when).days <= 7]
            if len(owed) == 1:
                p = Receipt(b, owed[0].invoice.party)
                _pay(p, owed[0], p.amount, "F")
                p.note = f"repays the director for the {owed[0].invoice.party} bill he paid: please confirm"
                payments.append(p)
                continue
        if s.head in _NOT_BILLS:
            no_bill.append(s)
            continue
        desc = b.description.lower()
        fits = [it for it in items if it.outstanding > 0.005 and abs(it.outstanding - b.money_out) < 0.005
                and it.invoice.when <= b.when and (_name_matches(it.invoice.party, b.description)
                                                   or aliases.get(customer_key(it.invoice.party), "\0") in desc)]
        fits.sort(key=lambda it: (b.when - it.invoice.when).days)
        if fits and (len(fits) == 1 or (b.when - fits[0].invoice.when).days <= 35):
            it = fits[0]
            p = Receipt(b, it.invoice.party)
            _pay(p, it, p.amount, "B")
            p.note = ("pays last year's unpaid bill" if it.brought_forward else "pays this bill") + \
                     f" from {it.invoice.party}" + (f" (step 2 read it as {s.head})" if s.head != SUPPLIER else "")
            _now_a_bill(s, it, p.note)
            payments.append(p)
            continue
        # A payment step 2 could not read (a person's name: a small supplier paid to its owner) equal to the one
        # open bill of this amount within the month before (or a week after), and no other such payment: probable
        if s.head == UNSORTED:
            same = [it for it in items if not it.brought_forward and it.outstanding > 0.005
                    and abs(it.outstanding - b.money_out) < 0.005 and -7 <= (b.when - it.invoice.when).days <= 30]
            rivals = [x for x in later if x is not s and x.head == UNSORTED
                      and abs(x.line.money_out - b.money_out) < 0.005 and abs((x.line.when - b.when).days) <= 30]
            if len(same) == 1 and not rivals:
                it = same[0]
                p = Receipt(b, it.invoice.party)
                _pay(p, it, p.amount, "F")
                p.note = f"matched on amount and date to the {it.invoice.party} bill: please confirm"
                _now_a_bill(s, it, p.note)
                s.sure = False
                payments.append(p)
                continue
        p = Receipt(b, "")
        if FOREIGN.search(b.description) and _foreign_bill(p, [it for it in items if it.outstanding > 0.005], s,
                                                            single=True):
            payments.append(p)
            continue
        no_bill.append(s)
    return BillsMatch(items, payments, no_bill)


# A card payment in another currency, as banks write it
FOREIGN = re.compile(r"\b(usd|eur|aud|cad|chf|sek|nok|dkk|pln|inr)\b|\(rate\b|orig\.? am|non-sterling|exchange rate", re.I)
FX_SHARE, FX_DAYS = 0.04, 7


def _foreign_bill(p: Receipt, open_items: List[OpenItem], s: SortedLine, single: bool = False) -> bool:
    """A bill in another currency paid within FX_DAYS of its date for up to FX_SHARE more or less than its pounds
    amount (the card's exchange rate): the bill is paid in full and the difference is an exchange gain or loss.
    single: only when exactly one bill fits (the payment does not name the supplier)."""
    amount = p.amount
    fits = [it for it in open_items if 0 <= (p.line.when - it.invoice.when).days <= FX_DAYS
            and abs(it.outstanding - amount) <= max(0.05, FX_SHARE * amount)]
    if not fits or (single and len(fits) > 1):
        return False
    it = min(fits, key=lambda it: (abs(it.outstanding - amount), (p.line.when - it.invoice.when).days))
    owed = it.outstanding
    _pay(p, it, owed, "X")
    p.customer = it.invoice.party
    p.fx = round(amount - owed, 2)
    p.note = f"pays the {it.invoice.party} bill of £{owed:,.2f} (another currency: exchange difference £{p.fx:,.2f})"
    _now_a_bill(s, it, p.note)
    return True


def _bank_names(items: List[OpenItem], lines: List[SortedLine]) -> Dict[str, str]:
    """The word a supplier's payments carry on the bank when it is not the supplier's name (Three -> 'h3g', the bank's
    own charges -> 'charges'): the first distinctive word of payments equal to its bills, paid within 35 days, seen at
    least twice and for no other supplier."""
    seen: Dict[str, Counter] = defaultdict(Counter)
    for s in lines:
        words = _words(s.line.description)
        if not words or s.line.money_out <= 0:
            continue
        for it in items:
            if it.outstanding > 0.005 and abs(it.outstanding - s.line.money_out) < 0.005 \
                    and 0 <= (s.line.when - it.invoice.when).days <= 35:
                seen[customer_key(it.invoice.party)][words[0]] += 1
    found = {sup: w for sup, counts in seen.items() for w, n in counts.most_common(1) if n >= 2}
    taken = Counter(found.values())
    return {sup: w for sup, w in found.items() if taken[w] == 1}


def _now_a_bill(s: SortedLine, it: OpenItem, how: str) -> None:
    """The bank line is now known to pay this bill (the Books tab shows it as such)."""
    s.head, s.code, s.bill, s.how, s.sure = SUPPLIER, 5200, it.invoice, how, True
