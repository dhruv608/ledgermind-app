"""The figures that matter, at a glance: a status chip in every tab's band, key figure boxes at
the top of each control and P&L tab, negative amounts red on the control tabs, a big change on a P&L tab amber, and
the cover's key figures. All by formula from the tab or the ETB, so they always agree with the workbook."""

import re
from typing import List, Optional, Tuple

from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from backend.app.services.workbook.look.base import *  # noqa: F401,F403 (the shared style and helpers)

CHIP_MAX_CHECKS = 40          # checks summed into one chip formula
VARIANCE_FLAG = 0.2           # a P&L change against last year above this (20%) is amber: a reviewer's question
TILE_COLS = (7, 9, 11)        # G, I, K: the boxes' first columns (two columns each)
RED_NEGATIVE_SECTIONS = re.compile(r"^[C-J]\d|^[C-J]$|^F-P", re.I)   # control tabs (not the TB, ETB or ledgers)
MONEY = '#,##0.00;(#,##0.00);"-"'
MONEY_RED = '#,##0.00;[Red](#,##0.00);"-"'
CHANGE_FORMAT = '"▲ "#,##0.00;"▼ "#,##0.00;"-"'


def check_refs(ws) -> List[str]:
    """The cells of the tab's checks that must be nil."""
    from backend.app.services.workbook.checks_tab import check_cells, t_blocks
    in_t = t_blocks(ws)
    out = []
    first_text = lambda row: next((c for c in row[:8] if _text(c)), None)
    for row in ws.iter_rows():
        label = first_text(row)
        is_label = lambda c, label=label: c is label and CHECK_LABEL.search(c.value)
        out += [c.coordinate for c in check_cells(in_t, row, 8, is_label)]
    return out


CHIP_GOOD, CHIP_BAD = PatternFill("solid", fgColor="15803D"), PatternFill("solid", fgColor="B91C1C")
TILE_WIDTH = 17


def chip(ws, refs: List[str]) -> None:
    """'✓ All checks agree' or '✗ n to look at' at the band's right edge, row 2, from the tab's own checks."""
    if not refs or ws["A1"].fill is None or ws["A1"].fill.fill_type != "solid":
        return
    width = max(BAND_MIN, min(ws.max_column, BAND_MAX))
    cell = ws.cell(row=2, column=width)
    if cell.value not in (None, "") or _merged(cell):
        return
    # A count, never TRUE / FALSE: with one check, (ABS(x)>=0.005) alone is a logical value and the chip would read
    # '✗ FALSE to look at'; 0+ makes it a number
    n = "0+" + "+".join(f"(ABS(N({r}))>=0.005)*1" for r in refs[:CHIP_MAX_CHECKS])
    cell.value = f'=IF(({n})=0,"✓ All checks agree","✗ "&({n})&" to look at")'
    # White on a solid green / red pill: light fills with dark text do not read on the dark band
    cell.font = Font(name="Calibri", size=10, bold=True, color=WHITE)
    cell.alignment = Alignment(horizontal="right", vertical="center")
    ref = cell.coordinate
    white = Font(color=WHITE, bold=True)
    ws.conditional_formatting.add(ref, FormulaRule(formula=[f'LEFT({ref},1)="✓"'], fill=CHIP_GOOD, font=white))
    ws.conditional_formatting.add(ref, FormulaRule(formula=[f'LEFT({ref},1)="✗"'], fill=CHIP_BAD, font=white))


def _lead_cells(ws) -> Optional[Tuple[str, str]]:
    """(balance b/fwd, balance c/fwd) amount cells of the tab's first lead schedule."""
    bf = cf = None
    for row in ws.iter_rows(min_row=5, max_row=min(ws.max_row, 60)):
        label = next((c for c in row[:4] if _text(c)), None)
        if label is None:
            continue
        amount = next((c for c in row if c.column > label.column and _amount(c)), None)
        if amount is None:
            continue
        if bf is None and LEAD_START.match(label.value):
            bf = amount.coordinate
        elif bf is not None and FINAL_LABEL.search(label.value) and label.value.lower().startswith("balance c/fwd"):
            cf = amount.coordinate
            break
    return (bf, cf) if bf and cf else None


def _free(ws, rows, cols) -> bool:
    return all(ws.cell(row=r, column=c).value in (None, "") and not _merged(ws.cell(row=r, column=c))
               for r in rows for c in cols)


def tiles(ws) -> None:
    """Three boxes at the top of a control tab: this year (c/fwd), last year (b/fwd), the change. A P&L (K) tab's own
    'This year / Last year / Variance' block is styled the same, its variance amber when over 20%."""
    if _text(ws["K3"]) and str(ws["K3"].value).lower().startswith("this year") and _text(ws["K6"]):
        _k_block(ws)
        return
    # A T account (balance_tabs/t_shape) gives its own net b/f and c/d formulas, signed as the account is read
    cells = getattr(ws, "_t_tiles", None) or _lead_cells(ws)
    if cells is None:
        return
    rows = (4, 5, 6)
    cols = range(TILE_COLS[0], TILE_COLS[-1] + 2)
    if not _free(ws, rows, cols):
        return
    bf, cf = cells
    boxes = (("THIS YEAR", f"={cf}", _dark(), MONEY), ("LAST YEAR", f"={bf}", "94A3B8", MONEY),
             ("CHANGE", f"=({cf})-({bf})", "94A3B8", CHANGE_FORMAT))
    for col, (title, formula, top, fmt) in zip(TILE_COLS, boxes):
        for c in (col, col + 1):
            ws.cell(row=4, column=c).border = Border(top=Side(style="thick", color=top))
            for r in rows:
                ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor="FFFFFF")
        head = ws.cell(row=4, column=col, value=title)
        head.font = Font(name="Calibri", size=8, bold=True, color=SLATE)
        value = ws.cell(row=5, column=col, value=formula)
        # Wide enough for a big figure ('▲ 38,818.27' at 13pt): narrower shows #####
        letter = value.column_letter
        ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0, TILE_WIDTH)
        value.font = Font(name="Calibri", size=14, bold=True, color=INK)
        value.number_format = fmt
        value.alignment = Alignment(horizontal="left")
        for c in (col, col + 1):
            ws.column_dimensions[ws.cell(row=4, column=c).column_letter].width = max(
                ws.column_dimensions[ws.cell(row=4, column=c).column_letter].width or 0, 9)
    pct = ws.cell(row=6, column=TILE_COLS[2], value=f'=IF(({bf})=0,"",(({cf})-({bf}))/ABS({bf}))')
    pct.number_format = '0%" change";-0%" change";"no change"'
    pct.font = Font(name="Calibri", size=9, color=SLATE)
    ws.row_dimensions[5].height = 22


def _k_block(ws) -> None:
    """A P&L tab's 'This year / Last year / Variance / Variance %' (K3:L6) as boxes: labels small, figures large, a
    change over 20% amber."""
    for r in range(3, 7):
        label, value = ws.cell(row=r, column=11), ws.cell(row=r, column=12)
        label.font = Font(name="Calibri", size=8, bold=True, color=SLATE)
        value.font = Font(name="Calibri", size=13 if r == 3 else 11, bold=r in (3, 5), color=INK)
        for c in (label, value):
            c.fill = PatternFill(fill_type=None)        # clear of the ledger table's heading row it may share
            c.alignment = Alignment(horizontal="left" if c is label else "right", vertical="center")
            c.border = Border(left=Side(style="thick", color=_dark()) if c is label else None,
                              bottom=Side(style="thin", color="E2E8F0"))
    ws["L6"].number_format = "0%"
    flag = f"AND(ISNUMBER($L$6),ABS($L$6)>{VARIANCE_FLAG})"
    for ref in ("L5", "L6"):
        ws.conditional_formatting.add(ref, FormulaRule(formula=[flag], fill=AMBER_FILL, font=AMBER_FONT))


def red_negatives(ws) -> None:
    """On the control tabs a negative amount (an overdrawn bank, a debtor in credit) shows red, still in brackets."""
    if not RED_NEGATIVE_SECTIONS.search(ws.title.strip()):
        return
    for row in ws.iter_rows():
        for c in row:
            if c.number_format == MONEY:
                c.number_format = MONEY_RED
            elif c.number_format == "#,##0.00;(#,##0.00)":
                c.number_format = "#,##0.00;[Red](#,##0.00)"


def _h1(wb, words: str, value_col: int) -> Optional[str]:
    """The H1 cell holding a figure, found by its label (the tax computation's own figure)."""
    if "H1-Taxation" not in wb.sheetnames:
        return None
    ws = wb["H1-Taxation"]
    for row in ws.iter_rows(min_row=15, max_row=min(ws.max_row, 80)):
        for c in row[:6]:
            if _text(c) and c.value.lower().startswith(words):
                return f"'H1-Taxation'!{ws.cell(row=c.row, column=value_col).coordinate}"
    return None


def cover_figures(wb, top: int) -> int:
    """The cover's key figures from row top (turnover, profit before tax and the tax from H1, net assets from the
    ETB, this year and last). Returns the next free row."""
    ws = wb[COVER]
    etb = "'B1-ETB'!"
    net = lambda col: f'=SUMIFS({etb}${col}:${col},{etb}$A:$A,">=4000",{etb}$A:$A,"<7000")'
    figures = [("Turnover", _h1(wb, "turnover per accounts", 4), None),
               ("Profit before tax", _h1(wb, "profit before tax per accounts", 4), None),
               ("Corporation tax", _h1(wb, "corporation tax chargeable", 7), None),
               ("Net assets", net("N")[1:] if "B1-ETB" in wb.sheetnames else None,
                net("T")[1:] if "B1-ETB" in wb.sheetnames else None)]
    figures = [f for f in figures if f[1]]
    if not figures:
        return top
    ws.cell(row=top, column=2, value="KEY FIGURES").font = Font(name="Calibri", size=11, bold=True, color=TEAL)
    for c in ws[top][1:6]:
        c.border = Border(bottom=TEAL_LINE)
    head = top + 1
    for col, text in ((4, "This year"), (6, "Last year")):
        cell = ws.cell(row=head, column=col, value=text)
        cell.font = Font(name="Calibri", size=9, bold=True, color=SLATE)
        cell.alignment = Alignment(horizontal="right")
    ws.column_dimensions["F"].width = 18
    r = head
    for label, this, last in figures:
        r += 1
        ws.cell(row=r, column=2, value=label).font = Font(name="Calibri", size=11, color=INK)
        v = ws.cell(row=r, column=4, value=f"={this}")
        v.font, v.number_format = Font(name="Calibri", size=13, bold=True, color=INK), '£#,##0;(£#,##0);"-"'
        if last:
            p = ws.cell(row=r, column=6, value=f"={last}")
            p.font, p.number_format = Font(name="Calibri", size=11, color=SLATE), '£#,##0;(£#,##0);"-"'
        for c in ws[r][1:6]:
            c.border = Border(bottom=Side(style="thin", color="E2E8F0"))
    return r + 2
