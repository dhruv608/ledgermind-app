"""One bank line sorted by the order of strength: invoice or customer, Dext bill, director, the firm's rules,
then the fallbacks."""

from datetime import timedelta
import re
from typing import Dict, List, Optional, Tuple

from backend.app.services.bank_only.input_files import BankLine, Invoice
from backend.app.services.bank_only.bank_sort.heads import (BY_INDUSTRY, CUSTOMER, DIRECTOR, GUIDE_HEADS, HEAD_CODES, SUPPLIER, TRANSFER, TRANSFERS,
                        UNSORTED, UNSURE_HEADS, _RULES, SortedLine)
from backend.app.services.bank_only.bank_sort.names import CHANNEL_WORDS, OWN_MONEY, _name_matches, _names_director, _payer_words

# Money back on a card ('Card 98 Apple.com', '... CD 4931') or a direct debit the bank returned: not a sale
NOT_SALES_KINDS = {"Card purchase", "Internet Refund", "Charge", "Cash withdrawal"}


# The director paid as an employee ('Feb Wage John Smith'): net wages when the company runs a payroll
DIRECTOR_PAY = re.compile(r"\bwages?\b|\bpay\b|payrol|\bsalary\b|net pay", re.I)

def _sort_one(b: BankLine, numbers: Dict[str, Invoice], customers: List[str], open_bills: List[Invoice],
              surnames: List[Tuple[str, str, Tuple[str, ...]]], suppliers: List[str], payroll: bool = False,
              industry: Optional[str] = None, own: Optional[List[str]] = None, industry_from: str = "") -> SortedLine:
    desc = b.description
    money_in = b.money_in > 0
    # The firm's rules read the payee, not the bank's words for how it was paid ('VIA MOBILE', 'MOBILE-CHANNEL')
    payee = CHANNEL_WORDS.sub(" ", desc)

    if money_in:
        # 1. A sales invoice number quoted, or a customer named
        quoted = [numbers[r] for r in b.refs if r in numbers]
        if quoted:
            return SortedLine(b, CUSTOMER, None, "invoice " + ", ".join(i.number for i in quoted), True,
                              customer=quoted[0].party)
        named = next((c for c in customers if _name_matches(c, desc)), None)
        if named:
            return SortedLine(b, CUSTOMER, None, f"customer {named}", True, customer=named)
    else:
        # 2. A Dext bill for the same amount, dated up to 7 days after or 90 days before the payment; the supplier
        #    named on the line wins over a bill that only has the amount
        amount = b.money_out
        fits = [i for i in open_bills if abs(i.gross - amount) < 0.005
                and timedelta(days=-7) <= (b.when - i.when) <= timedelta(days=90)]
        if fits:
            fits.sort(key=lambda i: (not _name_matches(i.party, desc), abs((b.when - i.when).days)))
            bill = fits[0]
            named = _name_matches(bill.party, desc)
            close = [i for i in fits if abs((b.when - i.when).days) <= 3]
            if named or close:
                open_bills.remove(bill)
                # Sure when the supplier is named, or only one bill of this amount is within 3 days (rule B)
                return SortedLine(b, SUPPLIER, HEAD_CODES[SUPPLIER],
                                  f"bill {bill.number or ''} {bill.party} {bill.when:%d/%m/%Y}".replace("  ", " "),
                                  named or len(close) == 1, bill=bill)

    # 3. The director
    if _names_director(desc, surnames):
        if payroll and not money_in and DIRECTOR_PAY.search(desc):
            return SortedLine(b, "Net wages", HEAD_CODES["Net wages"], "the director's pay (the company runs a payroll)", True)
        return SortedLine(b, DIRECTOR, HEAD_CODES[DIRECTOR], "director's name on the line", True)

    # 4. The firm's starting rules
    for pattern, head, way in _RULES:
        if way != "any" and (way == "in") != money_in:
            continue
        m = pattern.search(payee)
        if m:
            # The chart keyword rules give way to one of the client's own Dext suppliers named on the line: a payment
            # to a supplier with bills but none for this amount is still that supplier's
            if not money_in and head in GUIDE_HEADS:
                supplier = next((x for x in suppliers if _name_matches(x, desc)), None)
                if supplier:
                    return SortedLine(b, SUPPLIER, HEAD_CODES[SUPPLIER], f"pays {supplier}, but no bill for this amount",
                                      False)
            sure = head not in UNSURE_HEADS
            why = f"rule: {m.group(0).strip()}"
            if head in BY_INDUSTRY:
                head, sure = BY_INDUSTRY[head](industry)
                if industry and industry_from:
                    sure = False
                    why += f" (industry: {industry}, from {industry_from}, not confirmed yet)"
                else:
                    why += f" (industry: {industry or 'not set'})"
            return SortedLine(b, head, HEAD_CODES.get(head), why, sure)

    # 5. Money in that is none of the above is a customer receipt from a customer not yet known (an
    #    unidentified receipt, never forced onto a customer); money out naming a supplier with bills but no bill
    #    for this amount is a payment whose invoice is missing
    payer = _payer_words(payee)
    if money_in and own and payer[:1] == own[:1]:
        # The client's own name as the payer: its money moved from another account it holds ('Direct Credit From
        # Example Ltd - Ref: Self Transfer'); a company whose name only starts like it ('EXAMPLE PROPERTY LIMITED' for
        # Example Developments) may be a related company - never a sale. The client's name later on the line is the
        # customer naming who it pays ('JOHN SMITH & EXAMPLE STUDIOS L'), so that stays a receipt.
        nxt = payer[1] if len(payer) > 1 else ""
        if nxt and nxt not in own and nxt not in ("ltd", "limited", "llp", "plc", "ref", "self") and \
                not OWN_MONEY.search(payee):
            return SortedLine(b, "Ask the client", HEAD_CODES["Ask the client"],
                              "money in from a company with a name like the client's: a related company?", False)
        return SortedLine(b, TRANSFER, TRANSFERS, "the client's own name: money moved from its other account", False)
    if money_in and b.kind in NOT_SALES_KINDS:
        return SortedLine(b, "Refund received", None, f"money back ({b.kind.lower()}), not a sale", False)
    if money_in and b.kind in ("Bank transfer", "Direct credit", "Faster payment", "Scheduled payment",
                               "Standing order", ""):
        return SortedLine(b, CUSTOMER, None, "money in, customer not identified", False)
    if not money_in:
        supplier = next((x for x in suppliers if _name_matches(x, desc)), None)
        if supplier:
            return SortedLine(b, SUPPLIER, HEAD_CODES[SUPPLIER], f"pays {supplier}, but no bill for this amount", False)

    # 6. Not guessed
    return SortedLine(b, UNSORTED, HEAD_CODES[UNSORTED], "no rule fits", False)
