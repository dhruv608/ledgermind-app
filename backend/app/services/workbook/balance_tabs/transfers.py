"""Transfers between the client's own accounts on F2 (on their own line; a transfer that does not net to nil is
amber). Lines on the bank codes whose wording is an own-account transfer
('TRANSFER TO Fixed Fee Account', 'to savings', 'TFR', 'own account', 'sweep') are paired: money out of one bank with
the same amount into another bank within three days. The pairs are counted; a transfer with no other side is listed
(the other account's statement is missing, or the amount or date differs), and their total is an amber check."""

import re
from datetime import date, datetime
from typing import List, Optional, Tuple

from backend.app.services.workbook.balance_tabs.common import BANK_CODES, BOLD, Context, _money

OWN_TRANSFER = re.compile(r"transfer (to|from)\b.*\b(account|savings?|deposit|reserve|isa|current|a/c)\b|\btfr\b|"
                          r"own account|between accounts|internal transfer|\bsweep\b|(to|from) savings|"
                          r"fixed fee account|instant access", re.I)
DAYS = 3
RETURN_DAYS = 92          # out and back to the same account within three months
MAX_LISTED = 25


def _when(text) -> Optional[date]:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text)[:10], fmt).date()
        except ValueError:
            continue
    return None


def own_transfers(tx_rows) -> Tuple[int, float, List[Tuple[date, str, str, float]], int]:
    """(pairs matched, their total, the transfers with no other side: date, account, description, amount, and how
    many went out and came back to the same account)."""
    banks = {str(c) for c in BANK_CODES}
    lines = []
    for tx in tx_rows or []:
        if str(tx[1]) not in banks or not OWN_TRANSFER.search(f"{tx[5]} {tx[6]}"):
            continue
        when = _when(tx[0])
        amount = round(float(tx[7] or 0) - float(tx[8] or 0), 2)
        if when is not None and abs(amount) >= 0.01:
            lines.append([when, str(tx[1]), str(tx[3] or ""), str(tx[5] or "")[:60], amount, False])
    pairs, total = 0, 0.0
    outs = sorted((l for l in lines if l[4] < 0), key=lambda l: l[0])
    ins = [l for l in lines if l[4] > 0]
    for o in outs:
        match = next((i for i in ins if not i[5] and i[1] != o[1] and abs(i[4] + o[4]) < 0.01
                      and abs((i[0] - o[0]).days) <= DAYS), None)
        if match:
            o[5] = match[5] = True
            pairs += 1
            total += -o[4]
    # Out to an account not in the books and back to the same account (a fixed-term deposit): netted, not one-sided
    returned = 0
    for o in outs:
        back = next((i for i in ins if not o[5] and not i[5] and i[1] == o[1] and abs(i[4] + o[4]) < 0.01
                     and 0 <= (i[0] - o[0]).days <= RETURN_DAYS), None)
        if back:
            o[5] = back[5] = True
            returned += 1
    alone = [(l[0], l[2], l[3], l[4]) for l in sorted(lines, key=lambda l: l[0]) if not l[5]]
    return pairs, round(total, 2), alone, returned


def add_transfers(ctx: Context, ws, top: int) -> int:
    pairs, total, alone, returned = own_transfers(ctx.tx_rows)
    if not pairs and not alone and not returned:
        return top
    ws.cell(row=top, column=1, value="Transfers between the client's own accounts").font = BOLD
    ws.cell(row=top + 1, column=1, value=f"Matched (out of one account, into another within {DAYS} days): {pairs}")
    _money(ws.cell(row=top + 1, column=7, value=total))
    row = top + 2
    if returned:
        ws.cell(row=row, column=1, value=f"Out and back to the same account (an account not in the books, e.g. a "
                                         f"fixed-term deposit): {returned}")
        row += 1
    if alone:
        ws.cell(row=row, column=1, value="With no other side (the other account's statement is missing, or the "
                                         "amount or date differs):")
        for when, account, text, amount in alone[:MAX_LISTED]:
            row += 1
            ws.cell(row=row, column=1, value=when).number_format = "dd/mm/yyyy"
            ws.cell(row=row, column=2, value=f"{account[:30]}: {text}")
            _money(ws.cell(row=row, column=7, value=amount))
        if len(alone) > MAX_LISTED:
            row += 1
            ws.cell(row=row, column=2, value=f"... and {len(alone) - MAX_LISTED} more")
    row += 1
    ws.cell(row=row, column=1, value="Check: transfers with no other side, unexplained (must be nil)").font = BOLD
    _money(ws.cell(row=row, column=7, value=round(sum(a for *_x, a in alone), 2)), bold=True)
    return row + 1
