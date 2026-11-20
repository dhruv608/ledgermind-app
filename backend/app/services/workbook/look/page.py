"""The page: the title band, section headings, lead schedules, tables, totals, inputs and checks."""

import re

from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from backend.app.services.workbook.look.base import *  # noqa: F401,F403 (the shared style and helpers)


# ---------------------------------------------------------------------------------------------------------------------
# The title band and the section headings
# ---------------------------------------------------------------------------------------------------------------------
def _band(ws, has_cover: bool) -> None:
    """Rows 1-2 teal across the tab: the client, the year end, the reference at the right edge (a second copy of the
    reference the template left in row 1, 'K7' in K1 beside E1's 'K7', goes). The tab's title (A4) teal always."""
    a4 = ws["A4"]
    # A4 is the tab's title only when it stands alone on its row (A0's 'Amber not nil' has its count beside it)
    if _text(a4) and not _merged(a4) and not any(c.value not in (None, "") for c in ws[4][1:]):
        a4.font = Font(name="Calibri", size=13, bold=True, color=_dark())
    if ws["A1"].value in (None, "") or _merged(ws["A1"]):
        return
    width = max(BAND_MIN, min(ws.max_column, BAND_MAX))
    others = [c for r in (1, 2) for c in ws[r][:width] if c.value not in (None, "") and c.coordinate not in ("A1", "A2")]
    refs = [c for c in others if _text(c) and REF_LIKE.match(c.value.strip())]
    # Only a band over the header itself: a tab with other content in rows 1-2 keeps its own top
    if any(c not in refs and not c.hyperlink for c in others):
        return
    reference = next((c.value.strip() for c in refs if c.coordinate == "E1"), None) or         next((c.value.strip() for c in refs), None)
    for c in refs:
        if not _merged(c):
            c.value = None
    for r in (1, 2):
        for c in ws[r][:width]:
            if not _merged(c):
                c.fill = PatternFill("solid", fgColor=_dark())
                c.border = Border()
    ws.row_dimensions[1].height, ws.row_dimensions[2].height = 26, 18
    ws["A1"].font = Font(name="Calibri", size=16, bold=True, color=WHITE)
    ws["A1"].alignment = Alignment(vertical="center")
    if ws["A2"].value not in (None, "") and not _merged(ws["A2"]):
        ws["A2"].font = Font(name="Calibri", size=10, color=TEAL_LIGHT)
    if reference:
        target = ws.cell(row=1, column=width)
        if _merged(target):
            target = ws["E1"]
        target.value = reference
        target.font = Font(name="Calibri", size=16, bold=True, color=WHITE)
        target.alignment = Alignment(horizontal="right", vertical="center")


def _section_headings(ws, in_tables: set) -> None:
    """A bold line on its own below the title ('Reconciliation', 'Ledger lines this year (from the GL)'): teal, with a
    teal line under it across the tab."""
    width = max(BAND_MIN, min(ws.max_column, BAND_MAX))
    for row in ws.iter_rows(min_row=5):
        r = row[0].row
        if r in in_tables:
            continue
        filled = [c for c in row if c.value not in (None, "")]
        if len(filled) != 1:
            continue
        c = filled[0]
        text = _text(c)
        if not text or len(text) > 70 or c.font is None or not c.font.b or c.column > 2 or _merged(c) \
                or TOTAL_LABEL.match(text) or CHECK_LABEL.search(text) or LEAD_START.match(text):
            continue
        c.font = Font(name="Calibri", size=11, bold=True, color=_dark())
        for cell in row[:width]:
            if not _merged(cell):
                cell.border = Border(bottom=Side(style="medium", color=_dark()))
                cell.fill = PatternFill("solid", fgColor=_tint())
        ws.row_dimensions[r].height = 20


# ---------------------------------------------------------------------------------------------------------------------
# Lead schedules, tables, totals, checks, inputs
# ---------------------------------------------------------------------------------------------------------------------
def _leads(ws) -> set:
    """Each lead schedule ('Balance b/fwd' down to 'Check: B1-ETB final balance') as a clean T-account. Returns its rows."""
    done = set()
    rows = list(ws.iter_rows())
    i = 0
    while i < len(rows):
        label = next((c for c in rows[i][:4] if _text(c)), None)
        if label is None or not LEAD_START.match(label.value):
            i += 1
            continue
        j = i
        while j < len(rows) and j - i < 60:
            end_label = next((c for c in rows[j][:4] if _text(c)), None)
            if end_label is not None and LEAD_END.search(end_label.value):
                break
            j += 1
        if j >= len(rows) or j - i >= 60:
            i += 1
            continue
        t_block = bool(T_START.match(label.value))
        # A T's checks follow one another (c/d v ETB, the named lines, books v TB): all of them are the block's
        while t_block and j + 1 < len(rows):
            nxt = next((c for c in rows[j + 1][:4] if _text(c)), None)
            if nxt is None or not CHECK_LABEL.search(nxt.value):
                break
            j += 1
        for row in rows[i:j + 1]:
            done.add(row[0].row)
            if not ws.row_dimensions[row[0].row].height:
                ws.row_dimensions[row[0].row].height = LEAD_ROW_HEIGHT
            lab = next((c for c in row[:4] if _text(c)), None)
            text = lab.value if lab is not None else ""
            amounts = [c for c in row if lab is not None and c.column > lab.column and _amount(c)]
            for c in row[:8]:
                if not _merged(c) and not _is_input(c):
                    c.border = Border()
            if CHECK_LABEL.search(text):
                last = max([c.column for c in amounts] + [lab.column])
                for c in row[lab.column - 1:last]:
                    if not _merged(c):
                        c.fill = CHECK_STRIP
                lab.font = Font(name="Calibri", size=9, color=SLATE)
                for c in amounts:
                    c.font = Font(name="Calibri", size=9, color=SLATE)
            elif SUBTOTAL_LABEL.match(text):
                lab.font = _font(lab, bold=True)
                for c in amounts:
                    c.font, c.border = _font(c, bold=True), Border(top=DARK)
            elif t_block and text.strip().lower() == "balance c/d":
                lab.font = _font(lab, bold=True)          # a T's balancing line: bold, the lines go on its Total
                for c in amounts:
                    c.font = _font(c, bold=True)
            elif TOTAL_LABEL.match(text) or FINAL_LABEL.search(text):
                lab.font = _font(lab, bold=True)
                final = bool(FINAL_LABEL.search(text)) or (t_block and text.strip().lower() == "total")
                for c in amounts:
                    c.font, c.border = _font(c, bold=True), Border(top=DARK, bottom=DOUBLE if final else None)
        # The amount column's heading above the schedule ('£', 'Amount £'): no box, a light grey band across the
        # schedule's columns so each block has a visible start
        for row in rows[max(0, i - 4):i]:
            heading = any(_text(c) in ("£", "Amount £", "Amount") for c in row[:8])
            for c in row[:8]:
                if _merged(c):
                    continue
                if _text(c) in ("£", "Amount £", "Amount"):
                    c.border = Border()
                    c.font = Font(name="Calibri", size=10, bold=True, color=SLATE)
                    c.alignment = Alignment(horizontal="right")
                elif c.value in (None, ""):
                    c.border = Border()
                if heading and c.column <= LEAD_BAND_COLS:
                    c.fill = LEAD_HEAD_FILL
            if heading:
                ws.row_dimensions[row[0].row].height = 18
        i = j + 1
    return done


def _style_tables(ws) -> set:
    """Teal heading rows, a light line under each row, every other row shaded. Returns the tables' rows."""
    rows = set()
    # A row's cells read by position, not ws[r]: ws[r] works out the sheet's last column from every cell each time,
    # which on a ledger of 16,000 lines takes the build past its time limit
    width = ws.max_column

    def cells(r, a, b):
        b = min(b, width)
        return next(ws.iter_rows(min_row=r, max_row=r, min_col=a, max_col=b)) if b >= a else ()
    for head, first, last, end in _tables(ws):
        rows.update(range(head, end + 1))
        for c in cells(head, first, last):
            if _merged(c):
                continue
            c.fill = PatternFill("solid", fgColor=_dark())
            c.font = _font(c, bold=True, color=WHITE)
            c.border = Border(bottom=Side(style="thin", color=_dark()))
            c.alignment = Alignment(horizontal=c.alignment.horizontal if c.alignment else None, vertical="center",
                                    wrap_text=True)
        for n, r in enumerate(range(head + 1, end + 1)):
            # Each row's line runs from its own first filled cell to its last: no line under empty columns
            filled = [c.column for c in cells(r, first, last) if c.value not in (None, "")]
            if not filled:
                continue
            for c in cells(r, min(filled), max(filled)):
                if _merged(c) or _is_input(c):
                    continue
                if not _has_border(c.border):
                    c.border = Border(bottom=ROW_LINE)
                if n % 2 == 1 and (c.fill is None or c.fill.fill_type != "solid"):
                    c.fill = ZEBRA_FILL
    return rows


def _code_colour(ws) -> None:
    """The code column (A) of the TB tabs in one colour: the first row the builder wrote black, the rest red."""
    if not re.match(r"^(TTB|B1-ETB|CY-TB|PY-TB)", ws.title):
        return
    cells = [c for (c,) in ws.iter_rows(min_row=5, min_col=1, max_col=1)
             if isinstance(c.value, int) and not isinstance(c.value, bool)]
    if not cells:
        return
    colours = [str(c.font.color.rgb) if c.font is not None and c.font.color is not None else "" for c in cells]
    main = max(set(colours), key=colours.count)
    if not main:
        return
    ref = cells[colours.index(main)].font
    for c, colour in zip(cells, colours):
        if colour != main:
            c.font = Font(name="Calibri", size=ref.sz or 10, bold=ref.b, color=main)


def _clear_lines(ws) -> None:
    """Every line already on the tab goes (the template's grids, boxes and lines on empty columns; the builders'
    double lines on rows that are not totals): the house style then draws its own, so no line is left with no start
    and no end."""
    for row in ws.iter_rows():
        for c in row:
            if not _merged(c) and _has_border(c.border):
                c.border = Border()


def _band_total(row) -> None:
    """A table total: a light grey band over the row's own cells (first filled to last filled), bold amounts, one
    thin line above; no double line."""
    filled = [c for c in row if c.value not in (None, "")]
    if not filled:
        return
    for c in row[filled[0].column - 1:filled[-1].column]:
        if _merged(c):
            continue
        c.fill = TOTAL_FILL
        c.border = Border(top=DARK)
        if _amount(c) or _text(c):
            c.font = _font(c, bold=True)


def _final_total(row, label) -> None:
    """A final balance (Balance c/fwd, profits chargeable, total tax): the line above and the double line below on its
    amounts only."""
    label.font = _font(label, bold=True)
    for c in row:
        if c.column > label.column and not _merged(c) and _amount(c):
            c.font = _font(c, bold=True)
            c.fill = PatternFill(fill_type=None)
            c.border = Border(top=DARK, bottom=DOUBLE)


def _style_totals(ws, skip: set) -> None:
    """Totals outside the lead schedules: a final balance with its double line, any other total as a grey band. A row
    with no label whose bold amounts are sums (the tax control's and reserves' totals) is a total too."""
    for row in ws.iter_rows():
        if row[0].row in skip:
            continue
        label = next((c for c in row[:6] if _text(c)), None)
        if label is None:
            if any(not _merged(c) and _is_formula(c) and str(c.value).upper().startswith("=SUM(")
                   and c.font is not None and c.font.b for c in row):
                _band_total(row)
            continue
        if FINAL_LABEL.search(label.value):
            _final_total(row, label)
        elif TOTAL_LABEL.match(label.value):
            _band_total(row)


def _inputs(ws) -> None:
    """Cells for the accountant to type in: their yellow, with a dashed amber border."""
    for row in ws.iter_rows():
        for c in row:
            if _is_input(c) and not _merged(c):
                c.border = Border(left=DASHED, right=DASHED, top=DASHED, bottom=DASHED)


def _check_colours(ws) -> None:
    """A check that must be nil: green when it is, red when it is not (a text answer such as 'not entered' stays
    plain). A0's status column: RED red, AMBER amber, ok green."""
    if ws.title == "A0 - Checks":
        status = f"E6:E{max(ws.max_row, 6)}"
        ws.conditional_formatting.add(status, FormulaRule(formula=['E6="RED"'], fill=BAD_FILL, font=BAD_FONT))
        ws.conditional_formatting.add(status, FormulaRule(formula=['E6="AMBER"'], fill=AMBER_FILL, font=AMBER_FONT))
        ws.conditional_formatting.add(status, FormulaRule(formula=['E6="ok"'], fill=GOOD_FILL, font=GOOD_FONT))
        return
    for row in ws.iter_rows():
        label = next((c for c in row[:8] if _text(c)), None)
        if label is None or not CHECK_LABEL.search(label.value):
            continue
        for c in row:
            if c.column <= label.column or not _is_formula(c):
                continue
            ref = c.coordinate
            ws.conditional_formatting.add(ref, FormulaRule(formula=[f"AND(ISNUMBER({ref}),ABS({ref})<0.005)"],
                                                           fill=GOOD_FILL, font=GOOD_FONT))
            ws.conditional_formatting.add(ref, FormulaRule(formula=[f"AND(ISNUMBER({ref}),ABS({ref})>=0.005)"],
                                                           fill=BAD_FILL, font=BAD_FONT))
