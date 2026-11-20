"""Schedules laid out rather than tabled (tax computation, reserves, fixed assets), the ETB, filters, printing."""

import re
from typing import Optional

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.properties import PageSetupProperties

from backend.app.services.workbook.look.base import *  # noqa: F401,F403 (the shared style and helpers)


# FINAL_LABEL: base (the final balances, the only double lines)
GROUP_TITLE = re.compile(r"^[A-Z0-9 ,&()'/-]{6,}$")        # 'CORPORATION TAX COMPUTATION', 'TAXATION'


def _layouts(ws, skip: set) -> None:
    """Tabs laid out as a schedule, not a table (the tax computation, reserves, fixed assets): subtotals with a line
    above, the final figures with a line above and a double line below, capital-letter titles as section headings,
    a group heading row above a table (Cost / Depreciation) teal, year heading rows (2025 / 2024) as headings, CT600
    box numbers small and grey."""
    width = max(BAND_MIN, min(ws.max_column, BAND_MAX))
    heads = {h for h, _f, _l, _e in _tables(ws)}
    box_col = None
    for row in ws.iter_rows(min_row=5):
        r = row[0].row
        if r in skip:
            continue
        label = next((c for c in row[:6] if _text(c)), None)
        if label is not None and str(label.value).strip().lower() == "ct600 box":
            box_col = label.column
        cells = [c for c in row if c.value not in (None, "")]
        # A capital-letter title, with at most a short label beside it
        first = row[0] if _text(row[0]) else (row[1] if len(row) > 1 and _text(row[1]) else None)
        if first is not None and first.font is not None and first.font.b and GROUP_TITLE.match(first.value.strip()) \
                and len(cells) <= 2 and not any(_amount(c) for c in cells):
            first.font = Font(name="Calibri", size=11, bold=True, color=_dark())
            for c in row[:width]:
                if not _merged(c):
                    c.border = Border(bottom=Side(style="medium", color=_dark()))
                    c.fill = PatternFill("solid", fgColor=_tint())
            ws.row_dimensions[r].height = 20
            for c in cells:
                if c is not first and _text(c):
                    c.font = Font(name="Calibri", size=9, bold=True, color=SLATE)
            continue
        # A group heading row just above a table's heading row: teal text, a teal line
        if r + 1 in heads and cells and all(_text(c) for c in cells) and any(c.font is not None and c.font.b for c in cells):
            for c in cells:
                c.font = Font(name="Calibri", size=10, bold=True, color=_dark())
                if not _merged(c):
                    c.border = Border(bottom=Side(style="thin", color=_dark()))
            continue
        # A year heading row ('Retained earnings | =YEAR(YearEnd) | =YEAR(YearEnd)-1'): a heading
        years = [c for c in cells if _is_formula(c) and "YEAR(" in str(c.value).upper()]
        if years and label is not None and label.font is not None and label.font.b:
            # one band from the label to the last year, no gap between them
            for c in row[label.column - 1:years[-1].column]:
                if not _merged(c):
                    c.fill = PatternFill("solid", fgColor=_dark())
            for c in [label] + years:
                c.fill, c.font = PatternFill("solid", fgColor=_dark()), _font(c, bold=True, color=WHITE)
                c.alignment = Alignment(horizontal="right" if c in years else None)
            continue
        if label is None:
            continue
        amounts = [c for c in row if c.column > label.column and _amount(c)
                   and (box_col is None or c.column != box_col)]
        if FINAL_LABEL.search(label.value):
            label.font = _font(label, bold=True)
            for c in amounts:
                c.font, c.border = _font(c, bold=True), Border(top=DARK, bottom=DOUBLE)
        elif label.font is not None and label.font.b and any(str(c.value).upper().startswith("=SUM(") for c in amounts):
            for c in amounts:
                if not _has_border(c.border):
                    c.border = Border(top=DARK)
        if box_col is not None:
            box = ws.cell(row=r, column=box_col)
            if box.value not in (None, "") and not _merged(box):
                box.font = Font(name="Calibri", size=9, color=SLATE)
                box.alignment = Alignment(horizontal="center")


ETB = "B1-ETB"
SUB_HEAD_FILL = PatternFill("solid", fgColor="0D9488")      # a second heading row (Debit / Credit): lighter teal
CHECK_HEAD_FILL = PatternFill("solid", fgColor=SLATE)       # the ETB's check columns: grey, apart from the ETB itself
ETB_LAST_CORE = 14                                         # A-N: code, name, opening, movement, journals, final
FILTER_MIN_ROWS = 20                                       # a table this long gets Excel's filter buttons


def _etb(ws) -> None:
    """The ETB: its two heading rows (the column groups, then Debit / Credit) in two teals, the check columns (O on)
    headed grey, code and name frozen on the left with the headings, filter buttons on the second heading row."""
    head = None
    for r in range(1, 12):
        if _text(ws.cell(row=r, column=2)) and "nominal" in str(ws.cell(row=r, column=2).value).lower():
            head = r
            break
    if head is None:
        return
    sub = head + 1
    last_col = ws.max_column
    for col in range(1, last_col + 1):
        for r, fill in ((head, HEAD_FILL), (sub, SUB_HEAD_FILL)):
            c = ws.cell(row=r, column=col)
            if _merged(c) and r == sub:
                continue
            core = col <= ETB_LAST_CORE
            c.fill = fill if core else CHECK_HEAD_FILL
            c.font = Font(name="Calibri", size=10 if r == head else 9, bold=True, color=WHITE)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = Border(left=Side(style="thin", color=WHITE), right=Side(style="thin", color=WHITE))
    ws.row_dimensions[head].height = 30
    ws.freeze_panes = f"C{sub + 1}"
    from backend.app.services.workbook.etb_rows import data_rows
    end = max([sub] + [r for r in data_rows(ws) if r > sub])
    if end > sub:
        from openpyxl.utils import get_column_letter
        ws.auto_filter.ref = f"A{sub}:{get_column_letter(last_col)}{end}"
    ws.print_title_rows = f"{head}:{sub}"


def _filters(ws) -> None:
    """Excel's filter buttons on the tab's first long table (the General Ledger, the ledger tabs), once per tab."""
    if ws.auto_filter.ref:
        return
    from openpyxl.utils import get_column_letter
    for head, first, last, end in _tables(ws):
        if end - head >= FILTER_MIN_ROWS:
            ws.auto_filter.ref = f"{get_column_letter(first)}{head}:{get_column_letter(last)}{end}"
            # Room for the filter button beside each heading, so it does not sit on the text
            for c in range(first, last + 1):
                letter = get_column_letter(c)
                ws.column_dimensions[letter].width = min((ws.column_dimensions[letter].width or 9) + 2.5, 70)
            return


def _fit_header_dates(ws) -> None:
    """A date in the tab's first rows (the year end, '31 January 2025') shrinks to its column instead of showing ####
    when the column is narrow (the K index)."""
    from datetime import date, datetime
    for row in ws.iter_rows(min_row=1, max_row=8):
        for c in row:
            if isinstance(c.value, (date, datetime)) or (isinstance(c.value, str) and c.value.startswith("=")
                                                          and any(t in (c.number_format or "") for t in ("yyyy", "mmmm"))):
                width = ws.column_dimensions[c.column_letter].width or 9
                if width < 20 and not _merged(c):
                    c.alignment = Alignment(horizontal=c.alignment.horizontal if c.alignment else None,
                                            vertical=c.alignment.vertical if c.alignment else None, shrink_to_fit=True)


def _colour(title: str) -> Optional[str]:
    return next((d for pattern, d, _t in SECTION_COLOURS if pattern.search(title.strip())), None)


FREEZE_MAX_ROW = 10
WRAP_TABS = re.compile(r"^A0\b|review|scrutiny|pattern|duplicates|^Notes", re.I)


def _print_and_freeze(ws) -> None:
    # The cover is a front page read top to bottom: no freeze (Excel draws a freeze as a line across the whole sheet,
    # and the cover's band is four rows tall, so a freeze after row 2 would cut through it)
    cover = ws.title == COVER
    head = _heading_row(ws)
    # Only a heading near the top is frozen: frozen above a table 40 rows down, the tab cannot scroll and seems to
    # jump back to the top
    if head is not None and head > FREEZE_MAX_ROW:
        head = None
    if cover:
        ws.freeze_panes = None
    elif head is not None and ws.max_row > LONG_TAB and not ws.freeze_panes:
        ws.freeze_panes = f"A{head + 1}"
    elif ws.max_row > LONG_TAB and not ws.freeze_panes and ws["A1"].fill is not None \
            and ws["A1"].fill.fill_type == "solid":
        # No table heading (a lead sheet, the tax computation): the title band stays in view
        ws.freeze_panes = "A3"
    # Long notes on the review tabs wrap rather than run under the next cell (the ledger keeps one line a row)
    if WRAP_TABS.search(ws.title):
        for row in ws.iter_rows(min_row=5):
            for c in row:
                if _text(c) and len(c.value) > 40 and not _merged(c):
                    right = ws.cell(row=c.row, column=c.column + 1).value
                    width = ws.column_dimensions[c.column_letter].width or 8.43
                    if right not in (None, "") and len(c.value) > width * 1.2:
                        c.alignment = Alignment(wrap_text=True, vertical="top", horizontal=c.alignment.horizontal,
                                                indent=c.alignment.indent)
    if ws.max_row > 1:
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.orientation = "landscape" if ws.max_column > WIDE_TAB else "portrait"
        ws.sheet_properties.pageSetUpPr = ws.sheet_properties.pageSetUpPr or PageSetupProperties()
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        if head is not None:
            ws.print_title_rows = f"{head}:{head}"
