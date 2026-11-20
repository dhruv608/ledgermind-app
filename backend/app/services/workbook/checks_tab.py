"""A0 - Checks: every check the workbook makes, in one place, and the stop rule: a red check stops the workbook from
being marked final; an amber check keeps it a draft with the reason on the cover.

The check rows are the ones the tabs label as checks: 'Check: ... (must be nil)', 'Unexplained difference (must be
nil)'. Each is listed with a link to its tab, its value by formula and its status, so the list is right in Excel after
any edit too:
  RED     a lead, schedule or ETB check (the figures do not tie)
  AMBER   an agreement to outside evidence not yet explained (an aged report, a statement, a register)
The cover's draft line reads the count of red ones. After the formulas are worked out, failed() reads the statuses
back, so the build can name the file a draft and list them."""

import re
from typing import List, Optional, Tuple

from openpyxl.styles import Font

SHEET = "A0 - Checks"
# Every check the tabs write says so ('(must be nil)', '(must be 0)'); a ledger line of an account named 'Check 6790
# (US $)' is not one
LABEL = re.compile(r"must be (nil|0)\b|unexplained difference", re.I)
# Agreements to outside evidence: amber until explained
AMBER_WORDS = re.compile(r"unexplained|ageing|aged|statement|register|listing|report|returns", re.I)
FIRST = 6
T_HEAD = "T-account"                # the header of a T-account block (balance_tabs.leads.t_account)
T_CHECK = "Check: T-account"
T_ROWS = 12
TOL = 0.01


def t_blocks(ws):
    """A T-account beside a lead (balance_tabs.leads.t_account) shares the lead's rows: its figures are not the lead's
    checks, its own check line is one. Returns in_t(cell): the block a cell sits in, or None. (Only the cells the tab
    has: iter_rows with max_col would create empty cells and widen every tab.)"""
    heads = [(c.row, c.column) for c in ws._cells.values() if c.value == T_HEAD]

    def in_t(cell) -> Optional[Tuple[int, int]]:
        return next(((r, c) for r, c in heads if r <= cell.row <= r + T_ROWS and c <= cell.column <= c + 2), None)
    return in_t


def check_cells(in_t, row, label_columns: int, is_label) -> list:
    """The check formulas on a row: after a 'must be nil' label among the first label_columns cells (not in a
    T-account), else after a T-account's own check label; never another block's cells. in_t: t_blocks(ws)."""
    lab = next((c for c in row[:label_columns] if is_label(c) and not in_t(c)), None)
    if lab is None:
        lab = next((c for c in row if isinstance(c.value, str) and c.value.startswith(T_CHECK) and in_t(c)), None)
    if lab is None:
        return []
    block = in_t(lab)
    return [c for c in row if c.column > lab.column and isinstance(c.value, str) and c.value.startswith("=")
            and in_t(c) == block]


def _quoted(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


LABEL_COLUMNS = 6          # a check's label sits in columns A-F (the K tabs write theirs in F)


def find_checks(wb) -> List[Tuple[str, str, str, str]]:
    """(tab, cell, label, RED / AMBER) for each check formula on a labelled row. A row can hold several checks (the
    ETB's 'Check (must be 0)' row: opening, movement, journals, final and opening adjustment columns), so every formula after the label is one."""
    out = []
    for ws in wb.worksheets:
        if ws.title == SHEET:
            continue
        in_t = t_blocks(ws)

        for row in ws.iter_rows():
            lab = next((c for c in row[:LABEL_COLUMNS] if isinstance(c.value, str) and LABEL.search(c.value)
                        and not in_t(c)), None)
            if lab is None:
                lab = next((c for c in row if isinstance(c.value, str) and c.value.startswith(T_CHECK) and in_t(c)),
                           None)
            if lab is None:
                continue
            block = in_t(lab)
            f = [c for c in row if c.column > lab.column and isinstance(c.value, str) and c.value.startswith("=")
                 and in_t(c) == block]
            if not f:
                continue
            kind = "AMBER" if AMBER_WORDS.search(lab.value) else "RED"
            label = " ".join(lab.value.split())[:120]
            many = len(f) > 1
            for c in f:
                head = ws.cell(row=_heading_row(ws, c.column), column=c.column).value if many else None
                said = f"{label} - {' '.join(str(head).split())[:40]}" if many and head else (
                    f"{label} - column {c.column_letter}" if many else label)
                out.append((ws.title, c.coordinate, said, kind))
    return out


def _heading_row(ws, column: int) -> int:
    """The row of a column's heading above the data (the ETB's is row 6): the first of rows 1-8 with text there."""
    for r in range(6, 0, -1):
        if isinstance(ws.cell(row=r, column=column).value, str):
            return r
    return 1


def add_checks_tab(wb, draft_note: Optional[str]) -> int:
    """Writes A0 - Checks after the cover and the cover's draft line by formula. Returns how many checks it lists."""
    checks = find_checks(wb)
    if SHEET in wb.sheetnames:
        del wb[SHEET]
    ws = wb.create_sheet(SHEET, index=(wb.sheetnames.index("A") + 1) if "A" in wb.sheetnames else 0)
    bold = Font(name="Calibri", size=11, bold=True)
    ws["A1"], ws["A1"].font = "Workbook checks (each must be nil)", Font(name="Calibri", size=13, bold=True)
    ws["A2"] = ("RED: the figures do not tie (a lead, schedule or ETB check): the workbook stays a draft. AMBER: an "
                "agreement to outside evidence not yet explained: a draft until it is.")
    last = FIRST + max(len(checks), 1) - 1
    ws["A3"], ws["B3"] = "Red not nil", f'=COUNTIF(E{FIRST}:E{last},"RED")'
    ws["A4"], ws["B4"] = "Amber not nil", f'=COUNTIF(E{FIRST}:E{last},"AMBER")'
    for c in ("A3", "A4", "B3", "B4"):
        ws[c].font = bold
    for col, head in zip("ABCDE", ("Tab", "Check", "Cell", "Value", "Status")):
        ws[f"{col}{FIRST - 1}"], ws[f"{col}{FIRST - 1}"].font = head, bold
    for i, (tab, cell, label, kind) in enumerate(checks):
        r = FIRST + i
        ws[f"A{r}"] = f'=HYPERLINK("#{_quoted(tab)}!{cell}","{tab[:40]}")'
        ws[f"B{r}"], ws[f"C{r}"] = label, cell
        # A check still waiting for its figure shows its own words ('Statement balance not entered'), not #VALUE!
        src = f"{_quoted(tab)}!{cell}"
        ws[f"D{r}"] = f'=IF(ISNUMBER({src}),ROUND({src},2),IF({src}="",0,{src}))'
        ws[f"D{r}"].number_format = '#,##0.00;(#,##0.00);"-"'
        ws[f"E{r}"] = f'=IF(ISNUMBER(D{r}),IF(ABS(D{r})>{TOL},"{kind}","ok"),"not entered")'
        if kind == "RED":
            ws[f"E{r}"].font = Font(name="Calibri", size=11, bold=True, color="C00000")
        # For the cover's list of each red and amber item, linked: the number of this check among those not nil, and
        # its tab's plain name
        ws[f"F{r}"] = (f'=IF(OR(E{r}="RED",E{r}="AMBER"),COUNTIF(E${FIRST}:E{r},"RED")+COUNTIF(E${FIRST}:E{r},'
                       f'"AMBER"),"")')
        ws[f"G{r}"] = tab
    if checks:
        ws[f"F{FIRST - 1}"], ws[f"G{FIRST - 1}"] = "Not nil no.", "Tab name"
        ws.column_dimensions["F"].hidden = ws.column_dimensions["G"].hidden = True
    if not checks:
        ws[f"A{FIRST}"] = "No labelled checks in this workbook."
    for col, w in zip("ABCDE", (34, 70, 8, 14, 9)):
        ws.column_dimensions[col].width = w
    ws.sheet_properties.tabColor = "C00000"
    # The cover's draft line: a red check not nil keeps the workbook a draft (with the review's own reasons, if any)
    if "A" in wb.sheetnames:
        a = wb["A"]
        note = (draft_note or "").replace('"', "'")[:150]
        extra = f"; {note}" if note else ""
        otherwise = f"DRAFT - {note}" if note else ""
        red = f"{_quoted(SHEET)}!B3"
        a["B9"] = f'=IF({red}>0,"DRAFT - "&{red}&" red check(s) not nil, see A0 - Checks{extra}","{otherwise}")'
        a["B9"].font = Font(name="Calibri", size=12, bold=True, color="C00000")
        # The amber ones on the cover too, with their count; the list with links is on A0
        amber = f"{_quoted(SHEET)}!B4"
        a["B10"] = (f'=IF({amber}>0,{amber}&" amber check(s) to explain (agreements to outside evidence: register, '
                    f'statements, aged lists), see A0 - Checks","")')
        a["B10"].font = Font(name="Calibri", size=11, bold=True, color="9C5700")
    return len(checks)


def failed(path) -> Optional[List[Tuple[str, str, str, float]]]:
    """After the formulas are worked out: (status, tab, check, value) for each check not nil; None when the file holds
    no worked-out values (the formulas could not be calculated here)."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    try:
        if SHEET not in wb.sheetnames:
            return None
        out, any_value = [], False
        for row in wb[SHEET].iter_rows(min_row=FIRST, values_only=True):
            tab, label, _, value, status = (list(row) + [None] * 5)[:5]
            if value is not None or status is not None:
                any_value = True
            if status in ("RED", "AMBER"):
                out.append((status, str(tab or ""), str(label or ""), float(value or 0)))
        return out if any_value else None
    finally:
        wb.close()                  # read-only mode keeps the file open (Windows cannot remove it otherwise)
