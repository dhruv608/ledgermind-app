"""The employment status screen for a sole trade (R-SA103-10): signs that the 'self-employment' may be employment,
each an accountant's decision, never a change to the figures:

  one customer   over 80% of the turnover from one payer
  fixed fee      the same amount from the same payer in most months (a monthly or day rate)
  employer       a payer of the trade is also the person's employer in the year (and then the £1,000 trading
                 allowance is not available on that income)"""

import re
from collections import defaultdict
from typing import Dict, List, Tuple

ONE_CUSTOMER = 0.8
MIN_TURNOVER = 5000.0
FIXED_MONTHS = 6
NOISE = {"faster", "payments", "payment", "receipt", "ref", "from", "bank", "giro", "credit", "fp", "bgc", "inv",
         "invoice", "transfer", "tfr", "online", "via", "mobile", "xfer", "ltd", "limited", "the", "and", "for", "to",
         "income", "paid", "pay", "uk", "plc", "llp"}


def payer(text: str) -> str:
    """A payer's key from a bank or sheet description: its first two meaningful words ('FASTER PAYMENTS RECEIPT
    REF.INV 12 FROM ACME HOTELS LTD' is 'acme hotels')."""
    low = (text or "").lower()
    # 'REF.JOB COMPENSATION FROM A CUSTOMER': the payer is after the last 'from', not the reference before it
    if re.search(r"\bfrom\b", low):
        low = re.split(r"\bfrom\b", low)[-1]
    words = []
    for w in re.findall(r"[a-z]{3,}", low):
        if w not in NOISE and w not in words:
            words.append(w)
    return " ".join(words[:2])


# Card machines and selling platforms pay over many customers' money: not one customer (SumUp, Stripe, Etsy)
PLATFORMS = {"sumup", "stripe", "square", "paypal", "zettle", "izettle", "worldpay", "shopify", "etsy", "ebay",
             "amazon", "dojo", "takepayments", "teya", "klarna", "gocardless", "vinted", "airbnb"}


# A sheet's own labels name no customer ('Rent received', 'Sales', 'Cash')
GENERIC = {"rent", "rental", "received", "sales", "sale", "cash", "income", "takings", "invoice", "invoices", "fees",
           "fee", "work", "job", "jobs", "misc", "sundry", "other"}


def signals(lines: List[Tuple[str, str, float]], employers: List[str], trading_allowance: bool = False,
            person: str = "") -> List[str]:
    """The status signs from a trade's income lines [(date, description, amount)] and the employers' names. Money from
    the person's own name (their own transfers) and from card machines and platforms is not a customer's."""
    own = set(re.findall(r"[a-z]{3,}", (person or "").lower())) - {"e2e", "mrs", "miss"}
    lines = [(on, d, a) for on, d, a in lines
             if not (set(payer(d).split()) & (PLATFORMS | own)) and not (set(re.findall(r"[a-z]{3,}", (d or "").lower())) & PLATFORMS)
             and not (payer(d) and set(payer(d).split()) <= GENERIC)]
    total = sum(a for _, _, a in lines if a > 0)
    if total <= 0:
        return []
    by: Dict[str, float] = defaultdict(float)
    months: Dict[str, Dict[float, set]] = defaultdict(lambda: defaultdict(set))
    payments: Dict[str, Dict[float, int]] = defaultdict(lambda: defaultdict(int))
    for on, desc, amount in lines:
        if amount <= 0:
            continue
        key = payer(desc)
        if not key:
            continue
        by[key] += amount
        payments[key][round(amount, 2)] += 1
        if on:
            months[key][round(amount, 2)].add(on[:7])
    out = []
    top, top_amount = max(by.items(), key=lambda x: x[1]) if by else ("", 0.0)
    if total >= MIN_TURNOVER and top_amount / total > ONE_CUSTOMER:
        out.append(f"{top_amount / total:.0%} of the turnover (£{top_amount:,.2f} of £{total:,.2f}) comes from one payer "
                   f"({top}).")
    for key, amounts in months.items():
        amount, seen = max(amounts.items(), key=lambda x: len(x[1]))
        if len(seen) >= FIXED_MONTHS:
            out.append(f"The same £{amount:,.2f} came from {key} in {len(seen)} months: a fixed monthly or daily fee.")
        elif payments[key][amount] >= FIXED_MONTHS:
            # A day or week rate: the same amount many times, even within a few months (a hotel's £650 a week)
            out.append(f"The same £{amount:,.2f} came from {key} {payments[key][amount]} times: a fixed daily or weekly fee.")
    emp_words = [set(re.findall(r"[a-z]{3,}", (e or "").lower())) - NOISE for e in employers]
    for key in by:
        if any(set(key.split()) & w for w in emp_words if w):
            out.append(f"{key} pays the trade and also employs the person this year"
                       + (": the £1,000 trading allowance is not available on that income." if trading_allowance else "."))
    return out
