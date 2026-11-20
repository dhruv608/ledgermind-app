"""Open invoices and bills paid after the year end: each contact's payments in next year's ledger on the debtors
(4400, money in) or creditors (5200, money out) account, matched by the contact's name, clear that contact's open
items oldest first (a customer often pays in parts or in one sum for several invoices, so amounts are not matched one
to one). An item is paid on the date its last part was
cleared; one only partly cleared shows the part. An item over 90 days old and still not paid six months after the year
end is the one to question (bad debt, disputed, or already settled another way)."""

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

TRADE_DEBTORS, TRADE_CREDITORS = 4400, 5200
TOLERANCE = 1.0
STOP = {"ltd", "limited", "plc", "llp", "the", "and", "uk", "co", "company", "services", "group", "trading"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if w not in STOP}


def paid_after(items, lines, owed: bool) -> Dict[int, Tuple[Optional[date], float]]:
    """{index of the item: (date fully paid or None when only part paid, amount cleared)} for items next year's
    ledger shows paid in full or in part."""
    code = TRADE_CREDITORS if owed else TRADE_DEBTORS
    pays = [l for l in lines if l.code == code and (l.debit if owed else l.credit) >= 0.01]
    out: Dict[int, Tuple[Optional[date], float]] = {}
    contacts: Dict[str, List[int]] = {}
    for i, item in enumerate(items):
        if _words(item.contact) and abs(item.amount) >= TOLERANCE:
            contacts.setdefault(item.contact, []).append(i)
    used: set = set()
    for contact, idx in contacts.items():
        name = _words(contact)
        mine = [(k, l) for k, l in enumerate(pays) if k not in used and name & _words(f"{l.description} {l.reference}")]
        if not mine:
            continue
        used |= {k for k, _l in mine}
        money = [(l.when, l.debit if owed else l.credit) for _k, l in sorted(mine, key=lambda x: x[1].when)]
        order = sorted(idx, key=lambda i: (items[i].when or date.min))
        m, left = 0, money[0][1]
        for i in order:
            need, got, when = abs(items[i].amount), 0.0, None
            while m < len(money) and need - got > TOLERANCE:
                take = min(left, need - got)
                got += take
                left -= take
                when = money[m][0]
                if left < 0.005:
                    m += 1
                    left = money[m][1] if m < len(money) else 0.0
            if got >= 0.01:
                out[i] = (when if need - got <= TOLERANCE else None, round(got, 2))
            if m >= len(money):
                break
    return out


def paid_total(items, matched: Dict[int, Tuple[Optional[date], float]]) -> Tuple[float, float]:
    """(open at the year end, of which paid after it)."""
    return (round(sum(abs(i.amount) for i in items), 2), round(sum(v[1] for v in matched.values()), 2))


def note_for(matched: Optional[Tuple[Optional[date], float]], have_next_year: bool) -> str:
    if matched:
        return f"Paid {matched[0]:%d/%m/%Y}" if matched[0] else f"Part paid £{matched[1]:,.2f}"
    return "Not paid in the six months after" if have_next_year else ""
