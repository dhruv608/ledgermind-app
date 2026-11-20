"""Ledger lines on the other tabs pulled from the General Ledger tab by formula, so every movement has one source.

The tabs write their lines as values first (their own steps read them: which columns to keep, the running
balance), and note each line here with the GL line it came from. Once every tab is written, link_to_gl turns each
noted cell into a formula to that line's cell on the GL tab, where it holds the GL's own value (an empty cell, a text
cut short, a figure rounded stay as written). No step moves rows, so the GL rows stay where step 9 wrote them."""

from typing import Dict

from backend.app.services.workbook.context import GL_TAB

GL_FIRST = 7            # the GL tab's first line (step 9 writes tx_rows from row 7, in order)


def note_gl_line(ctx, ws, row: int, tx, cols: Dict[int, str]) -> None:
    """A tab's line from the GL: {column on ws: the GL tab's heading} for the cells written from tx."""
    links = getattr(ctx, "gl_links", None)
    if links is None:
        links = ctx.gl_links = []
    links.append((ws, row, tx, cols))


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.005
    return str(a) == str(b)


def link_to_gl(ctx) -> int:
    """Each noted cell as a formula to the GL tab. Returns how many cells were linked."""
    wb, links = ctx.wb, getattr(ctx, "gl_links", None) or []
    if not links or GL_TAB not in wb.sheetnames:
        return 0
    gl = wb[GL_TAB]
    heads = {str(c.value): c.column_letter for c in gl[6] if c.value}
    row_of = {id(tx): GL_FIRST + i for i, tx in enumerate(ctx.tx_rows or [])}
    sheets = {id(ws) for ws in wb.worksheets}
    ref = "'" + GL_TAB.replace("'", "''") + "'!"
    linked = 0
    for ws, r, tx, cols in links:
        g = row_of.get(id(tx))
        if g is None or id(ws) not in sheets:
            continue
        for col, head in cols.items():
            cell = ws.cell(row=r, column=col)
            letter = heads.get(head)
            if letter is None or cell.value in (None, "") or isinstance(cell.value, str) and cell.value.startswith("="):
                continue
            source = gl[f"{letter}{g}"].value
            if source in (None, "") or not _same(cell.value, source):
                continue
            cell.value = f"={ref}{letter}{g}"
            linked += 1
    return linked
