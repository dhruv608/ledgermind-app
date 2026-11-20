"""Passes over the whole statement: transfers between the client's own accounts, refunds from payees the client
pays, payments to an unknown account, money in on a credit card, and a property company's large one-off amounts."""

import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from backend.app.services.bank_only.input_files import CARD_NAME, BankLine, RawInput
from backend.app.services.bank_only.bank_sort.heads import (CUSTOMER, DIRECTOR, HEAD_CODES, SUPPLIER, TRANSFER, TRANSFERS, UNSORTED, BankSort,
                        SortedLine)
from backend.app.services.bank_only.bank_sort.names import _words

# Money paid all year to an account named only by its number ('Internet Banking Transfer to Account 40039926'),
# none back from it, and not one of the client's statements: more likely the director's own account than the
# company's. A suggestion to check
TO_ACCOUNT = re.compile(r"\baccount\s+(?:no\.?\s*)?(\d{6,8})\b", re.I)
UNKNOWN_ACCOUNT_LINES = 3
UNKNOWN_ACCOUNT_HOW = "paid all year to account"


def _unknown_accounts(raw: RawInput, result: BankSort) -> None:
    statements = " ".join(a.name for a in raw.accounts)
    paid: Dict[str, List[SortedLine]] = {}
    back = set()
    for s in result.lines:
        m = TO_ACCOUNT.search(s.line.description)
        if not m:
            continue
        if s.line.money_in > 0:
            back.add(m.group(1))
        elif s.head == TRANSFER and s.pair is None:
            paid.setdefault(m.group(1), []).append(s)
    for number, lines in paid.items():
        if number in back or len(lines) < UNKNOWN_ACCOUNT_LINES or number in statements:
            continue
        for s in lines:
            s.head, s.code, s.sure = DIRECTOR, HEAD_CODES[DIRECTOR], False
            s.how = (f"{UNKNOWN_ACCOUNT_HOW} {number} ({len(lines)} payments, nothing back) and not one of the "
                     f"client's statements: probably the director's own account")


# A card statement's repayment line ('PAYMENT RECEIVED THANK YOU', 'Direct debit payment')
CARD_REPAYMENT = re.compile(r"payment\s*(received|-\s*thank)|thank you|repayment|direct debit|\bpayment\s*$", re.I)


def _card_money_in(raw: RawInput, result: BankSort) -> None:
    """Money in on a credit card is never a sale (card repayments are not takings). A repayment matched to the company's bank stays a transfer; one the company's
    statements do not show was paid from outside them: the director's (director's loan), to check, unless a statement
    is missing. Any other credit (a refund, a travel credit or reward) is left to check, not taken as income."""
    cards = {a.name for a in raw.accounts if a.is_card}
    if not cards:
        return
    # Payments to a card on the company's own statements that no card line pairs with (a bank paying a card in other
    # amounts than the card shows): the card's unpaired
    # repayments are that money, so they stay transfers between own accounts (the one-sided transfers asked about)
    paid_to_card = any(s.head == TRANSFER and s.pair is None and s.line.money_out > 0 and s.line.account not in cards
                       and CARD_NAME.search(s.line.description) for s in result.lines)
    for s in result.lines:
        b = s.line
        if b.account not in cards or b.money_in <= 0 or s.pair is not None:
            continue
        if s.head not in (TRANSFER, CUSTOMER, "Sales (no invoice)") and s.code != 0:
            continue
        if CARD_REPAYMENT.search(b.description) and paid_to_card:
            s.head, s.code, s.sure = TRANSFER, TRANSFERS, False
            s.how = ("a card repayment: the company's bank paid the card in other amounts than the card shows "
                     "(transfer between own accounts, check the total)")
        elif CARD_REPAYMENT.search(b.description):
            s.head, s.code, s.sure = DIRECTOR, HEAD_CODES[DIRECTOR], False
            s.how = ("a card repayment the company's bank statements do not show: paid by the director (director's "
                     "loan), or from an account whose statement is missing")
        else:
            s.head, s.code, s.sure = UNSORTED, HEAD_CODES[UNSORTED], False
            s.how = "a credit on the card (a refund, travel credit or reward), not a sale: check what it was for"


def _refunds(raw: RawInput, result: BankSort) -> None:
    """Money in from a payee the client pays (Uber, Amazon, Asda) is a refund of those payments: the same head, as
    the accountant posts it. For a bank-only client (no invoices or bills to match) any such receipt; with Dext lists
    only a line the bank calls a refund, so no customer's receipt is taken for one."""
    from backend.app.services.bank_only.books import payee_key
    bank_only = raw.bank_only
    from collections import Counter
    paid: Dict[str, Counter] = {}
    # The client's own name first on a line ('Examplefoods John Smith', 'Examplefoods Ltd Jane Doe') is the bank
    # naming the account, not the payee: never a payee's first word
    own = set(_words(raw.client_name or "")) | {"".join(_words(raw.client_name or ""))}

    def first(word: str) -> bool:
        return len(word) >= 4 and word not in own
    for s in result.lines:
        if s.line.money_out and s.code is not None and s.head not in (UNSORTED, TRANSFER, SUPPLIER):
            key = payee_key(s.line.description)
            if not key:
                continue
            word = key.split(" ")[0]
            for k in ({key, "first:" + word} if first(word) else {key}):
                paid.setdefault(k, Counter())[(s.head, s.code)] += 1

    def usual(k: str) -> Optional[Tuple[str, Optional[int]]]:
        """The head most of a payee's payments have (Asda: the shop, not its petrol station), if clearly most."""
        c = paid.get(k)
        if not c:
            return None
        head, n = c.most_common(1)[0]
        return head if n / sum(c.values()) >= 0.7 else None
    for i, s in enumerate(result.lines):
        b = s.line
        if not b.money_in or s.head not in ("Sales (no invoice)", "Refund received", CUSTOMER, UNSORTED) \
                or (s.head == CUSTOMER and s.customer):
            continue
        if not bank_only and s.head != "Refund received":
            continue
        key = payee_key(b.description)
        if not key:
            continue            # no payee name on the line ('BCARD1758579 BW 200000'): nothing to match it to
        word = key.split(" ")[0]
        hit = usual(key) or (usual("first:" + word) if first(word) else None)
        if hit:
            result.lines[i] = SortedLine(b, hit[0], hit[1], f"refund: money back from a payee the client pays "
                                                            f"({hit[0].lower()})", False)


# A property company's one-off money of this much, read as sales or purchases (money from a buyer or to the builder
# written as 'Sales' or 'Asset purchase'), may be a property sold or bought, a deposit or
# development costs: the accountant decides, by the property's model (rental: fixed asset; trading: stock)
PROPERTY_LARGE = 10000.0
PROPERTY_HOW = "property company: a large one-off amount, the accountant decides"


def _property_money(s: SortedLine) -> bool:
    b = s.line
    if max(b.money_in, b.money_out) < PROPERTY_LARGE:
        return False
    if b.money_in > 0:
        return s.head in (UNSORTED, CUSTOMER, "Sales (no invoice)") or (s.code is not None and 0 <= s.code < 1000)
    return s.head == UNSORTED or (s.code is not None and 1000 <= s.code < 2000)


def own_transfers(raw: RawInput) -> Dict[int, BankLine]:
    """Money out of one of the client's accounts and the same amount into another within 3 days, where either line
    looks like a transfer (says transfer, savings or own account, or names the other account or the company): each
    line -> its pair. Closest dates first; a line pairs once."""
    if len(raw.accounts) < 2:
        return {}
    own = {w for a in raw.accounts for w in _words(a.name)} | set(_words(raw.client_name)[:1])
    # The last four digits of a card or account in its name ('Natwest Card 3092'): the bank line paying the card
    # quotes its whole number ('NW BUSINESS CREDIT 5473679045813092')
    digits = {m for a in raw.accounts for m in re.findall(r"(?<!\d)(\d{4})(?!\d)", a.name)}

    def looks_like(b: BankLine) -> bool:
        text = b.description.lower()
        return bool(re.search(r"transfer|saving|own account|internal|\bpot\b|\bisa\b|payment,? (received,? )?thank you",
                              text)) or \
            any(re.search(rf"\b{re.escape(w)}\b", text) for w in own) or \
            any(re.search(rf"\d*{d}\b", text) for d in digits)

    outs = [b for b in raw.bank if b.money_out > 0]
    ins = [b for b in raw.bank if b.money_in > 0]
    found = [(o, i) for o in outs for i in ins if o.account != i.account and abs(o.money_out - i.money_in) < 0.005
             and abs((i.when - o.when).days) <= 3 and (looks_like(o) or looks_like(i))]
    # Lines with fewer possible pairs go first: money moved on through three accounts the same day (saver -> Tide ->
    # Monzo, the same amount) pairs saver with Tide and Tide with Monzo, not saver with Monzo
    choices = Counter(id(x) for pair in found for x in pair)
    candidates = sorted(((abs((i.when - o.when).days), choices[id(o)] + choices[id(i)], n, o, i)
                         for n, (o, i) in enumerate(found)), key=lambda c: c[:3])
    pairs: Dict[int, BankLine] = {}
    for _, _, _, o, i in candidates:
        if id(o) not in pairs and id(i) not in pairs:
            pairs[id(o)], pairs[id(i)] = i, o
    return pairs
