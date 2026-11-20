"""Last year's accrual against the bill that settled it, so the over- or under-accrual shows.

For an accrual reversed this year: the first cost in the first four months on the account it was set against whose
description shares a word with the accrual's ('Rent - Quarter of Jun-2024' -> a 'Rent' line), or whose amount is the
amount accrued. None when no such line is found: the schedule says so, nothing is guessed."""

import re
from datetime import date, datetime
from typing import Optional, Tuple

WINDOW_DAYS = 123            # about four months: a quarterly bill in arrears arrives within it
STOP = {"accrual", "accrued", "accruals", "reverse", "reversed", "last", "year", "years", "final", "for", "the", "and",
        "quarter", "month", "months", "with", "from", "this", "that", "bill", "bills", "cost", "costs", "paid", "payment",
        "limited", "ltd", "invoice", "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
        "oct", "nov", "dec"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in STOP}


def _when(text) -> Optional[date]:
    if isinstance(text, (date, datetime)):
        return text if isinstance(text, date) and not isinstance(text, datetime) else text.date()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text)[:10], fmt).date()
        except ValueError:
            continue
    return None


def accrued_for(narrative: str) -> str:
    """What the accrual was for, from its journal's narrative: "Reverse last year's accrual: Rent - Quarter of Jun-2024
    (last year's final WP)" -> "Rent - Quarter of Jun-2024"."""
    text = narrative.split(":", 1)[1] if ":" in narrative else narrative
    return re.sub(r"\([^)]*\)", "", text).strip()


def first_bill(tx_rows, code: str, narrative: str, year_start: date,
               accrued: float = 0.0) -> Optional[Tuple[date, float, str]]:
    """(date, amount, description) of the first cost on `code` in the window that is the accrual's bill: its own
    description shares a word with the accrual's (the account's name words do not count: every line on the account
    has them), or its amount is the amount accrued (within £1)."""
    wanted = _words(accrued_for(narrative))
    found = []
    for tx in tx_rows or []:
        if str(tx[1]) != str(code):
            continue
        when = _when(tx[0])
        if when is None or not (year_start <= when <= date.fromordinal(year_start.toordinal() + WINDOW_DAYS)):
            continue
        amount = float(tx[7] or 0) - float(tx[8] or 0)
        if amount <= 0.005 or re.search(r"revers|accru|opening balance", f"{tx[4]} {tx[5]}", re.I):
            continue
        own = _words(f"{tx[5]} {tx[6]}") - _words(str(tx[3] or ""))
        if (wanted & own) or (accrued >= 1 and abs(amount - accrued) <= 1):
            found.append((when, round(amount, 2), str(tx[5] or tx[3] or "")[:80]))
    return min(found) if found else None
