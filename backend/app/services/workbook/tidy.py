"""One look for every tab of a built workbook (footer, number formats, column widths, font)."""

import re
from typing import Dict

from openpyxl.styles import Alignment, Border, Font, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.dimensions import ColumnDimension

from backend.app.services.workbook.balance_tabs import INPUT_COLOUR

MONEY_HEADING = re.compile(r"debit|credit|amount|balance|\bnet\b|\bvat\b|gross|total|£|\btax\b|paid|owed|cost|"
                           r"\bnbv\b|depreciation|prepayment|accrual|movement|charge|check|difference|value|"
                           r"profit|turnover|box\s*\d", re.I)
NOT_MONEY_HEADING = re.compile(r"code|\bno\b|\bref|rate|%|days|months|date|number|qty|name|account$|type|"
                               r"description|source|employees|period|year", re.I)
MONEY_FORMAT = '#,##0.00;(#,##0.00);"-"'
TEXT_WIDTH_MAX = 60     # a column widened for its text stops here (a longer narration is cut, not a page-wide column)
WIDTH_MAX = 60          # no column wider than this; longer text in it wraps
MONEY_WIDTH_MIN = 13


def _split_column_ranges(ws) -> None:
    """One width per column. A template stores widths as ranges ('D:E 22.9', 'J to the last column 49.3'): a column
    inside a range cannot be widened on its own, and every empty column right of the data takes the range's odd
    width. Each range is split into its columns up to the last used one; past it the sheet's normal width applies
    (a hidden range, the template's own way of hiding unused columns, stays as it is)."""
    from copy import copy
    last = max(ws.max_column, 1)
    for key, dim in list(ws.column_dimensions.items()):
        lo = dim.min or column_index_from_string(key)
        hi = dim.max or lo
        if hi <= lo:
            continue
        for col in range(lo + 1, min(hi, last) + 1):
            letter = get_column_letter(col)
            if letter in ws.column_dimensions and ws.column_dimensions[letter].min == col:
                continue
            new = ColumnDimension(ws, index=letter, width=dim.width, hidden=dim.hidden,
                                  customWidth=dim.customWidth, outlineLevel=dim.outlineLevel)
            new._style = copy(dim._style)
            new.min = new.max = col
            ws.column_dimensions[letter] = new
        if dim.hidden and hi > last:
            letter = get_column_letter(last + 1)
            if lo <= last:
                rest = ColumnDimension(ws, index=letter, width=dim.width, hidden=True, customWidth=dim.customWidth)
                rest.min, rest.max = last + 1, hi
                ws.column_dimensions[letter] = rest
            else:
                continue                      # the whole range is past the data and hidden: keep it
        if lo > last:
            del ws.column_dimensions[key]     # past the data: the sheet's normal width
            continue
        dim.min = dim.max = lo

# A section tab's reference from its name ('G2.1- Creditors NL' is G2.1; 'C1-1-FA detail' and 'G9-.1-VAT' have none)
REF_TAB = re.compile(r"^([C-K]\d+(?:\.\d+)?)(?=[\s(]|-(?![\d.])|$)")


# A tab's reference for its header: also the hyphenated ones ('C1-1', 'G9-.1' -> 'G9.1')
HEADER_REF = re.compile(r"^([C-K]\d+(?:[.-]\.?\d+)*)")
REF_LIKE = re.compile(r"^[A-K]\d+(?:[.-]\d+)*$")
CLIENT_LINK, YEAR_END_LINK = "=A!B2", "='Notes & Queries'!A2"


def _place_reference(ws, client: str = "", year_end: str = "") -> None:
    """One header on every section tab (the same layout, fonts and reference position on every C to K tab): A1 the
    client linked to the cover, A2 the year end linked to Notes & Queries (the template types both as text), E1 the
    tab's reference, bold and right (moved there from wherever the template had it in the first rows, or corrected
    where it is short, such as 'E3' on E3.1), A4's title bold. A cell holding anything else is
    left as it is."""
    m = HEADER_REF.match(ws.title)
    if not m:
        return
    ref = m.group(1).replace("-.", ".")
    # A template header merged across row 1 from A (G9.4: A1:E1) would hide E1: the merge goes, A1 keeps its value
    for rng in list(ws.merged_cells.ranges):
        if rng.min_row == rng.max_row == 1 and rng.min_col == 1 and rng.max_col >= 5:
            ws.unmerge_cells(str(rng))
    for addr, link, words in (("A1", CLIENT_LINK, client), ("A2", YEAR_END_LINK, year_end)):
        cell = ws[addr]
        if type(cell).__name__ != "MergedCell" and (cell.value in (None, "", link) or (words and str(cell.value).strip() == words)):
            cell.value = link
            cell.font = Font(name="Calibri", bold=True, size=10)
    a4 = ws["A4"]
    if type(a4).__name__ != "MergedCell" and isinstance(a4.value, str) and a4.value.strip() and not a4.value.startswith("="):
        a4.font = Font(name="Calibri", bold=True, size=12)
    e1 = ws["E1"]
    if type(e1).__name__ == "MergedCell" or not (e1.value in (None, "") or (isinstance(e1.value, str) and REF_LIKE.match(e1.value.strip()))):
        return
    for row in ws.iter_rows(min_row=1, max_row=3, max_col=10):
        for c in row:
            text = str(c.value or "").strip()
            # the reference elsewhere in the first rows, or another tab's left on row 1 (G9.4 showed 'G9.3' in G1)
            if c.coordinate != "E1" and type(c).__name__ != "MergedCell" and (
                    text in (ref, m.group(1)) or (c.row == 1 and REF_LIKE.match(text))):
                c.value = None
    e1.value = ref
    e1.font = Font(name="Calibri", bold=True, size=11)
    e1.alignment = Alignment(horizontal="right")


# The template's short labels in plain English
LABEL_FIXES = {"Charge drg the yr": "Charge for the year", "Deprn. Rate": "Depreciation rate", "Deprn. rate": "Depreciation rate",
               "Deprn": "Depreciation", "B/Fwd": "Brought forward", "C/Fwd": "Carried forward"}


def _code_columns(wb) -> None:
    """The ETB and TTB code column as codes, not money (4800, not 4,800.00), left-aligned; the TTB's codes in the
    firm's style, red and bold."""
    for name, red in (("B1-ETB", False), ("TTB", True)):
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        for (c,) in ws.iter_rows(min_row=8, min_col=1, max_col=1):
            if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                c.number_format = "0"
                c.alignment = Alignment(horizontal="left")
                if red:
                    c.font = Font(name="Calibri", bold=True, color="FFC00000")


def tidy_workbook(wb, client_name: str, ye_str: str) -> None:
    """One look for every tab, whatever the template carried: the same page footer (client, tab, page; no
    file path or another preparer's initials), no printed gridlines, no leftover colour blocks on empty cells,
    amounts as 1,234.00, columns wide enough that text is not cut off by the cell beside it, one font."""
    from copy import copy
    footer_name = f"{client_name} - {ye_str}".replace("&", "&&")
    _code_columns(wb)
    year_end = str(wb["Notes & Queries"]["A2"].value or "").strip() if "Notes & Queries" in wb.sheetnames else ""
    for ws in wb.worksheets:
        _place_reference(ws, client_name.strip(), year_end)
        # Pictures pasted into the template are screenshots of another client's records (bank statement,
        # HMRC pages, VAT workings): never in this client's file
        ws._images = []
        for hf in (ws.oddHeader, ws.evenHeader, ws.firstHeader, ws.oddFooter, ws.evenFooter, ws.firstFooter):
            for part in (hf.left, hf.center, hf.right):
                part.text = None
        for footer in (ws.oddFooter, ws.evenFooter, ws.firstFooter):
            footer.left.text, footer.center.text, footer.right.text = footer_name, "&A", "Page &P of &N"
            for part in (footer.left, footer.center, footer.right):
                part.size, part.font = 8, "Calibri"
        ws.print_options.gridLines = False
        _split_column_ranges(ws)

        merged = {c for rng in ws.merged_cells.ranges for row in ws.iter_rows(
            min_row=rng.min_row, max_row=rng.max_row, min_col=rng.min_col, max_col=rng.max_col) for c in row}
        # Amount columns: a money heading in the first rows (and not a code / date / rate heading)
        money_cols: Dict[int, int] = {}
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 12)):
            for c in row:
                if isinstance(c.value, str) and not c.value.startswith("="):
                    text = c.value.strip()
                    if NOT_MONEY_HEADING.search(text):
                        money_cols.pop(c.column, None)
                    elif MONEY_HEADING.search(text) and len(text) <= 30:
                        money_cols.setdefault(c.column, c.row)
        widths: Dict[str, float] = {}
        # A section tab's rows left with nothing in them (the template's example lines): no empty bordered boxes;
        # cells shaded for the accountant to fill in keep theirs
        section = bool(REF_TAB.match(ws.title))
        for row in ws.iter_rows():
            blank_row = section and row and row[0].row > 6 and all(c.value in (None, "") for c in row)
            for c in row:
                v = c.value
                if v is None or v == "":
                    input_cell = str(getattr(c.fill.fgColor, "rgb", "") or "").endswith(INPUT_COLOUR) if c.fill else False
                    # Leftover colour blocks go; cells for the accountant to fill in keep their shading
                    if (c.fill is not None and c.fill.fill_type == "solid" and c not in merged and not input_cell):
                        c.fill = PatternFill(fill_type=None)
                    if blank_row and c not in merged and not input_cell and c.has_style and c.border is not None and any(
                            getattr(c.border, side).style for side in ("left", "right", "top", "bottom")):
                        c.border = Border()
                    continue
                if isinstance(v, str) and not v.startswith("=") and v.strip() in LABEL_FIXES:
                    c.value = v = LABEL_FIXES[v.strip()]
                if c.font is not None and c.font.name != "Calibri":
                    f = copy(c.font)
                    f.name = "Calibri"
                    c.font = f
                is_number = isinstance(v, (int, float)) and not isinstance(v, bool)
                is_formula = isinstance(v, str) and v.startswith("=")
                if (c.number_format == "General" and c.row > money_cols.get(c.column, 10 ** 9)
                        and (is_number or is_formula)):
                    c.number_format = MONEY_FORMAT
                elif c.number_format == "General" and isinstance(v, float) and v != int(v) and c.row > 6:
                    c.number_format = MONEY_FORMAT
                # Text cut off by a filled cell to its right: widen the column (up to a limit)
                if isinstance(v, str) and not is_formula and c not in merged:
                    right = ws.cell(row=c.row, column=c.column + 1).value
                    if right not in (None, ""):
                        longest = max(len(line) for line in v.split("\n"))
                        need = min(longest * 1.1 + 2, TEXT_WIDTH_MAX)
                        letter = c.column_letter
                        widths[letter] = max(widths.get(letter, 0), need)
                elif c.number_format == MONEY_FORMAT:
                    # wide enough for the amount, or Excel shows ####
                    shown = len(f"{abs(v):,.2f}") + 4 if is_number else 0
                    widths[c.column_letter] = max(widths.get(c.column_letter, 0), MONEY_WIDTH_MIN, shown)
        default = ws.sheet_format.defaultColWidth or 8.43
        for letter, need in widths.items():
            current = ws.column_dimensions[letter].width or default
            if current < need:
                ws.column_dimensions[letter].width = round(need, 1)
        # No page-wide columns: past the limit the column is narrowed and its long text wraps
        for letter, dim in list(ws.column_dimensions.items()):
            if dim.width and dim.width > WIDTH_MAX and not dim.hidden:
                dim.width = WIDTH_MAX
                for (cell,) in ws.iter_rows(min_col=dim.min or 1, max_col=dim.min or 1):
                    if isinstance(cell.value, str) and len(cell.value) > WIDTH_MAX and not cell.value.startswith("="):
                        cell.alignment = Alignment(wrap_text=True, vertical=cell.alignment.vertical or "top",
                                                   horizontal=cell.alignment.horizontal, indent=cell.alignment.indent)
