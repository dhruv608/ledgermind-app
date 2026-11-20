"""Suspense (9999): its own control tab (suspense is nil at the year end, or every item is explained).
The lead lines (b/fwd, movement, journals by name, c/fwd, checks against the ETB), then each ledger line on the
suspense accounts with an explanation cell for the accountant to fill in."""

from typing import Optional

from backend.app.services.workbook.balance_tabs.common import (
    BOLD, INPUT_FILL, TITLE, Context, _has_balance, _lines_for, _new_sheet, _records, _write_lines
)
from backend.app.services.workbook.balance_tabs.leads import lead_lines

SUSPENSE = 9999


def suspense_tab(ctx: Context) -> Optional[str]:
    if not _has_balance(ctx, [SUSPENSE]):
        return None
    ws = _new_sheet(ctx, "B4 - Suspense", ["B3 - BS ledgers", "Re-analysis", "B2-Journals", "B1-ETB"])
    ws["E1"] = "B4"
    ws["A4"] = "Suspense (9999) - nil at the year end, or every item explained"
    ws["A4"].font = TITLE
    ws["D6"] = "Amount £"
    ws["D6"].font = BOLD
    rows = lead_lines(ctx, ws, [SUSPENSE])
    ctx.lead_rows[ws.title] = rows
    ctx.schedule_cf[SUSPENSE] = (f"'{ws.title}'!D{rows['cf']}", 1)
    names = [t.raw_account_name for t in _records(ctx, [SUSPENSE])]
    below = rows["end"] + 1
    ws.cell(row=below, column=2, value="Accounts on 9999: " + ", ".join(n or "" for n in names)[:200])
    lines = _lines_for(ctx, names)
    head = below + 2
    end = _write_lines(ws, head, "Each item on suspense this year", lines, "Debit", "Credit")
    ws.column_dimensions["F"].width = 50
    if lines:
        ws.cell(row=head + 1, column=6, value="Explanation (what it is, where it goes)").font = BOLD
        for r in range(head + 2, head + 2 + len(lines)):
            ws.cell(row=r, column=6).fill = INPUT_FILL
    ws.cell(row=end, column=2, value=("Clear each item to its proper code by journal (B2), or explain why it stays; "
                                      "a balance left at the year end is a query for the client."))
    return ws.title
