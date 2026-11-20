"""A bank statement's own lines under the account's T and reconciliation (Unrecorded / Unmatched / Matched), when a
statement was read on the screen (services/bank_statement.statement_match). Nothing is written when no statement was
read."""

from datetime import date
from typing import Optional

from backend.app.services.workbook.balance_tabs.common import BOLD, _money

HEAD = ("Date", "Description", "Amount £")


def _day(iso: Optional[str]):
    try:
        return date.fromisoformat(iso) if iso else None
    except ValueError:
        return iso


def _list(ws, row: int, title: str, note: str, items: list) -> int:
    """One list: its title, the lines (date, description, amount money in +) and the total. Returns the next free row."""
    ws.cell(row=row, column=1, value=f"{title} ({len(items)})").font = BOLD
    ws.cell(row=row, column=3, value=note)
    row += 1
    for c, text in enumerate(HEAD, 2):
        ws.cell(row=row, column=c, value=text).font = BOLD
    first = row + 1
    for item in items:
        row += 1
        when = _day(item.get("date"))
        cell = ws.cell(row=row, column=2, value=when)
        if isinstance(when, date):
            cell.number_format = "dd/mm/yyyy"
        ws.cell(row=row, column=3, value=(item.get("description") or "")[:120])
        _money(ws.cell(row=row, column=4, value=round(float(item.get("amount") or 0), 2)))
    if not items:
        row += 1
        ws.cell(row=row, column=3, value="None")
        return row + 2
    row += 1
    ws.cell(row=row, column=3, value="Total").font = BOLD
    _money(ws.cell(row=row, column=4, value=f"=SUM(D{first}:D{row - 1})"), bold=True, total=True)
    return row + 2


def statement_lines_block(ctx, ws, code: int, row: int) -> int:
    """Write the three lists from `row`; returns the row after them (or `row` when no statement was read)."""
    match = (getattr(ctx, "statement_lines", None) or {}).get(code)
    if not match or not match.get("read"):
        return row
    span = f"{match.get('from') or '?'} to {match.get('to') or '?'}"
    ws.cell(row=row, column=1, value=f"Bank statement lines read ({span})").font = BOLD
    ws.cell(row=row + 1, column=2, value=(f"{match.get('statement_lines', 0)} statement lines against "
                                          f"{match.get('ledger_lines', 0)} ledger lines in the same dates"))
    row += 3
    row = _list(ws, row, "Unrecorded", "on the statement, not in the books: a journal to post",
                match.get("unrecorded") or [])
    row = _list(ws, row, "Unmatched", "in the books, not on the statement", match.get("unmatched") or [])
    matched = [{**m["statement"], "description": f"{m['statement'].get('description') or ''}"
                + (f" (ledger {m['days']} day{'s' if m['days'] != 1 else ''} apart)" if m.get("days") else "")}
               for m in (match.get("matched") or [])]
    return _list(ws, row, "Matched", "on the statement and in the books", matched)
