"""One tab per credit card (F4.n), as for each bank (one control tab per bank account, credit card, PayPal, Shopify
and cash). Cards on the bank codes (48xx) already have their bank tab; this is for cards on the
creditor codes (5350-5359: 'Credit card' 5351 in the firm chart; clients put cards on 5352 / 5353 too). Those codes also
hold pensions, loans, vouchers and the director's account on some clients, so a code gets a card tab only when every
account on it is named as a card. The card's balance stays in the creditors lead (G1); the tab is its statement
check, starting from the balance typed for its code on the control accounts screen (key 'code:5351')."""

import re
from typing import List

from backend.app.services.workbook.balance_tabs.bank import _account_tab
from backend.app.services.workbook.balance_tabs.common import Context, _records

CARD_CODES = list(range(5350, 5360))
CARD_NAME = re.compile(r"credit ?cards?|\bamex\b|american express|mastercard|barclaycard|commercial card|"
                       r"capital on tap|\bvisa\b", re.I)
NOT_A_CARD = re.compile(r"\bloans?\b|fees?|charges?|interest|director|personal|pension|accrual|voucher", re.I)


def card_codes(ctx: Context) -> List[int]:
    """The creditor codes whose accounts are all credit cards (and that hold something)."""
    out = []
    for code in CARD_CODES:
        records = _records(ctx, [code])
        names = [t.raw_account_name or "" for t in records]
        if names and all(CARD_NAME.search(n) and not NOT_A_CARD.search(n) for n in names) and \
                any(abs(float(t.net_amount or 0)) >= 0.005 or abs(float(t.opening_amount or 0)) >= 0.005 for t in records):
            out.append(code)
    return out


def card_tabs(ctx: Context, after: List[str]) -> List[str]:
    made = []
    for i, code in enumerate(card_codes(ctx), 1):
        names = [t.raw_account_name for t in _records(ctx, [code])]
        made.append(_account_tab(ctx, code, f"F4.{i}", names, after, "Balance c/fwd (negative = owed on the card)",
                                 statement="card statement (owed as a negative)", key="code"))
        after = [made[-1][0]]
    if made:
        ctx.notes.append(f"{len(made)} credit card tab(s) (F4): enter each card statement balance to reconcile")
    return [m[0] for m in made]
