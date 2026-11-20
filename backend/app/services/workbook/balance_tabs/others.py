"""Other debtors (E6) and other creditors (G5): their own control tab, each item named. Each account on those codes that has no tab of its own (deposits E4, credit cards F4, loans G4,
pension G8, the director's loan G3) is listed by name with its closing balance per the books and a cell for the
evidence that supports it; the list is tied to the books. When the codes hold only these accounts the standard lead
lines (b/fwd, movement, journals by name, c/fwd, ETB checks) come first."""

import re
from typing import List, Optional

from backend.app.services.workbook.balance_tabs.cards import card_codes
from backend.app.services.workbook.balance_tabs.common import (
    BOLD, DEPOSIT_WORDS, INPUT_FILL, OTHER_DEBTORS, TITLE, Context, on_tab, _lines_for, _money, _new_sheet, _records,
    _write_lines)
from backend.app.services.workbook.balance_tabs.t_shape import t_account
from backend.app.services.workbook.balance_tabs.loans import LOAN_NAME, NOT_A_LOAN

PENSION_CODE = 5352                 # the firm's pension code: the G8 tab takes every account on it, whatever its name
OTHER_CREDITORS = [c for c in range(5350, 5360) if c != PENSION_CODE]
OWN_TAB_CREDITOR = re.compile(r"pension|\bnest\b|director|\bdla\b", re.I)     # G8 pension, G3 director's loan
MIN = 0.005


def _has(t) -> bool:
    return abs(float(t.net_amount or 0)) >= MIN or abs(float(t.opening_amount or 0)) >= MIN


def _other_creditor(t, cards) -> bool:
    name = t.raw_account_name or ""
    return t.std_code not in cards and not OWN_TAB_CREDITOR.search(name) and \
        not (LOAN_NAME.search(name) and not NOT_A_LOAN.search(name))


def other_debtors_tab(ctx: Context) -> Optional[str]:
    records = [t for t in _records(ctx, OTHER_DEBTORS) if not DEPOSIT_WORDS.search(t.raw_account_name or "") and _has(t)]
    return _tab(ctx, records, "E6 - Other debtors", "E6", "Other debtors - each item named", owed=False,
                after=["E5 - s455", "E4 - Deposits", "E3.2 - Prepayment review", "E3 - Prepayments", "E1 (LEAD)"])


def other_creditors_tab(ctx: Context) -> Optional[str]:
    cards = set(card_codes(ctx))
    records = [t for t in _records(ctx, OTHER_CREDITORS) if _other_creditor(t, cards) and _has(t)]
    return _tab(ctx, records, "G5 - Other creditors", "G5", "Other creditors - each item named", owed=True,
                after=["G4 - Loans & HP", "G3.1 - DLA-NL Transactions", "G3- DLA", "G2 - Trade creditors", "G1 (LEAD)"])


def _tab(ctx: Context, records: list, title: str, ref: str, heading: str, owed: bool, after: List[str]) -> Optional[str]:
    if not records:
        return None
    sign = -1 if owed else 1
    codes = sorted({int(t.std_code) for t in records})
    others = [t for t in _records(ctx, codes) if t not in records and _has(t)]
    ws = _new_sheet(ctx, title, after)
    ws["E1"] = ref
    ws["A4"] = heading
    ws["A4"].font = TITLE
    row = 8
    lead = None
    if not others:
        # The codes are these accounts alone: one T ties them to the ETB
        lead = t_account(ctx, ws, codes, top=6, owed=owed)
        ctx.lead_rows[ws.title] = lead
        if len(codes) == 1:
            ctx.schedule_cf[codes[0]] = (on_tab(ws.title, lead["cf"]), 1)       # debit +
        row = lead["end"] + 2
    else:
        ws["D6"] = "Amount £"
        ws["D6"].font = BOLD
    ws.cell(row=row, column=1, value="Each account").font = BOLD
    row += 1
    for c, text in enumerate(["Account", "Code", "", "Closing per books £", "", "Evidence (what it is, the document "
                                                                                 "that supports it)"], 1):
        if text:
            ws.cell(row=row, column=c, value=text).font = BOLD
    ws.column_dimensions["F"].width = 55
    first = row + 1
    for t in records:
        row += 1
        ws.cell(row=row, column=1, value=(t.raw_account_name or "")[:60])
        ws.cell(row=row, column=2, value=int(t.std_code))
        _money(ws.cell(row=row, column=4, value=round(sign * float(t.net_amount or 0), 2)))
        ws.cell(row=row, column=6).fill = INPUT_FILL
    row += 1
    ws.cell(row=row, column=1, value="Total").font = BOLD
    _money(ws.cell(row=row, column=4, value=f"=SUM(D{first}:D{row - 1})"), bold=True, total=True)
    if lead:
        target = f"({lead['books_s']})"          # closing per the books and the TB, before the adjusting journals
        row += 1
        ws.cell(row=row, column=2, value="Check: accounts listed v closing per books (must be nil)").font = BOLD
        _money(ws.cell(row=row, column=4, value=f"=ROUND(D{row - 1}-{target},2)"), bold=True)
    else:
        row += 1
        ws.cell(row=row, column=1, value=("The codes also hold accounts with their own tab: "
                                          + ", ".join(f"{t.raw_account_name} ({t.std_code})" for t in others))[:250])
    _write_lines(ws, row + 2, "Ledger lines this year", _lines_for(ctx, [t.raw_account_name for t in records]),
                 "Debit", "Credit")
    return ws.title
