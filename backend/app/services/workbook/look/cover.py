"""The cover (tab A) and the A0 checks summary."""

import re

from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill

from backend.app.services.workbook.look.base import *  # noqa: F401,F403 (the shared style and helpers)


SECTION_NAMES = (            # the contents' groups, in the order of SECTION_COLOURS
    "Cover, checks and notes", "Trial balance, ETB, journals and ledger", "Fixed assets", "Stock",
    "Debtors and prepayments", "Bank, cards and platforms", "Creditors, loans, DLA, payroll and VAT",
    "Tax", "Reserves and share capital", "Profit and loss", "Industry schedules")
A0 = "A0 - Checks"
COVER_CHECKS = 10          # red / amber checks listed by name on the cover; the rest are counted


def _q(title: str) -> str:
    return title.replace("'", "''")


def _cover(wb) -> None:
    """The cover (tab A) in the house style: a teal band with the client (B2, which every tab's header links to) and
    the year end (B4, the named cell YearEnd), the status in a coloured line (DRAFT / checks to explain / all checks
    agree, from A0), then the contents: every tab by section, each a link. B2, B4 and the status formulas stay in
    their cells."""
    if COVER not in wb.sheetnames:
        return
    ws = wb[COVER]
    keep = {"B2", "B4", "B9", "B10"}
    for row in ws.iter_rows(min_row=1, max_row=max(ws.max_row, 20), max_col=10):
        for c in row:
            if c.coordinate not in keep and not _merged(c):
                c.value, c.hyperlink = None, None
                c.border, c.fill = Border(), PatternFill(fill_type=None)
    for col, w in zip("ABCDEF", (3, 64, 3, 22, 3, 3)):
        ws.column_dimensions[col].width = w
    for r in range(1, 5):
        for c in ws[r][:6]:
            c.fill = BAND_FILL
    ws.row_dimensions[2].height = 30
    ws["B1"] = "LEDGERMIND  ·  YEAR-END WORKING PAPERS"
    ws["B1"].font = Font(name="Calibri", size=9, bold=True, color=TEAL_LIGHT)
    ws["B2"].font = Font(name="Calibri", size=22, bold=True, color=WHITE)
    ws["B2"].alignment = Alignment(vertical="center")
    ws["B3"] = "Year ended"
    ws["B3"].font = Font(name="Calibri", size=10, color=TEAL_LIGHT)
    ws["B4"].font = Font(name="Calibri", size=13, bold=True, color=WHITE)
    ws["B4"].alignment = Alignment(horizontal="left")
    ws["D2"] = "A"
    ws["D2"].font = Font(name="Calibri", size=22, bold=True, color=WHITE)
    ws["D2"].alignment = Alignment(horizontal="right", vertical="center")
    # The status: one line, coloured (the reasons below it)
    ws["B6"] = "STATUS"
    ws["B6"].font = Font(name="Calibri", size=11, bold=True, color=TEAL)
    ws["B6"].border = Border(bottom=TEAL_LINE)
    if A0 in wb.sheetnames:
        red, amber = f"'{_q(A0)}'!B3", f"'{_q(A0)}'!B4"
        ws["B7"] = (f'=IF({red}>0,"DRAFT: "&{red}&" red check(s) not nil",IF({amber}>0,{amber}&" amber check(s) to '
                    f'explain","All checks agree"))')
        ws["B7"].font = Font(name="Calibri", size=13, bold=True)
        ws.conditional_formatting.add("B7", FormulaRule(formula=['LEFT(B7,5)="DRAFT"'], fill=BAD_FILL, font=BAD_FONT))
        ws.conditional_formatting.add("B7", FormulaRule(formula=['ISNUMBER(SEARCH("amber",B7))'], fill=AMBER_FILL,
                                                        font=AMBER_FONT))
        ws.conditional_formatting.add("B7", FormulaRule(formula=['B7="All checks agree"'], fill=GOOD_FILL,
                                                        font=GOOD_FONT))
    for a in ("B9", "B10"):
        ws[a].font = Font(name="Calibri", size=9, color=SLATE)
    # The key figures, then the contents: every tab by section, each a link
    from backend.app.services.workbook.look.figures import cover_figures
    top = 12
    if A0 in wb.sheetnames:
        # Each red and amber check by name, linked to its cell; worked out by formula from A0, so a check cleared in
        # Excel drops off
        q = f"'{_q(A0)}'!"
        count = f"({q}B3+{q}B4)"
        head = ws.cell(row=top, column=2, value=f'=IF({count}>0,"CHECKS TO CLEAR","")')
        head.font = Font(name="Calibri", size=11, bold=True, color=TEAL)
        for k in range(1, COVER_CHECKS + 1):
            at = f"MATCH({k},{q}$F:$F,0)"
            pick = lambda col: f"INDEX({q}${col}:${col},{at})"
            cell = ws.cell(row=top + k, column=2, value=(
                f'=IFERROR(HYPERLINK("#\'"&SUBSTITUTE({pick("G")},"\'","\'\'")&"\'!"&{pick("C")},'
                f'{pick("E")}&"  "&{pick("G")}&": "&{pick("B")}),"")'))
            cell.font = Font(name="Calibri", size=10, color=INK, underline="single")
        more = ws.cell(row=top + COVER_CHECKS + 1, column=2,
                       value=f'=IF({count}>{COVER_CHECKS},"... and "&({count}-{COVER_CHECKS})&" more on A0 - Checks","")')
        more.font = Font(name="Calibri", size=9, color=SLATE)
        top += COVER_CHECKS + 3
    row = cover_figures(wb, top)
    ws.cell(row=row, column=2, value="CONTENTS").font = Font(name="Calibri", size=11, bold=True, color=TEAL)
    for c in ws[row][1:6]:
        c.border = Border(bottom=TEAL_LINE)
    groups = {i: [] for i in range(len(SECTION_COLOURS) + 1)}
    for t in wb.sheetnames:
        # the section divider tabs ('C', 'E', 'F' ...) are blank pages: not in the contents
        if t == COVER or wb[t].sheet_state != "visible" or re.fullmatch(r"[A-Z]", t.strip()):
            continue
        i = next((n for n, (pattern, _c, _t) in enumerate(SECTION_COLOURS) if pattern.search(t.strip())), len(SECTION_COLOURS))
        groups[i].append(t)
    blocks = [(i, tabs) for i, tabs in groups.items() if tabs]
    # Two columns (B, and D running into E-F) of about the same length: the section at the break carries on at the
    # top of the right column, its heading marked (continued)
    total = sum(len(t) + 2 for _i, t in blocks)
    left, right, used = [], [], 0
    for i, tabs in blocks:
        if right or used + len(tabs) + 2 <= (total + 2) / 2:
            (right if right else left).append((i, tabs, ""))
            used += len(tabs) + 2
            continue
        cut = max(0, min(len(tabs), round((total + 2) / 2 - used - 2)))
        if cut:
            left.append((i, tabs[:cut], ""))
        right.append((i, tabs[cut:], " (continued)" if cut else ""))
    for col, part in ((2, left), (4, right)):
        r = row
        for i, tabs, more in part:
            r += 2
            name = (SECTION_NAMES[i] if i < len(SECTION_NAMES) else "Other tabs") + more
            colour = SECTION_COLOURS[i][1] if i < len(SECTION_COLOURS) else SLATE
            ws.cell(row=r, column=col, value=name).font = Font(name="Calibri", size=10, bold=True, color=colour)
            for t in tabs:
                r += 1
                link = ws.cell(row=r, column=col, value=plain_name(t))
                link.hyperlink = f"#'{_q(t)}'!A1"
                link.font = Font(name="Calibri", size=10, color=INK)
                link.alignment = Alignment(indent=2 if col == 2 else 1)
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = SLATE


TAB_REF = re.compile(r"^([A-Z]\d+(?:[.-]\d+)*)\s*(?:-\s*|\s+)(.+)$")
LEAD_WORD = re.compile(r"^\(lead\)$", re.I)


def plain_name(tab: str) -> str:
    """A tab as the contents list names it: its reference, then the plain name the screen uses ('F3.1 - 4800 - HSBC
    Current' -> 'F3.1   HSBC Current', 'C1 (LEAD)' -> 'C1   Lead schedule'); the tab itself keeps its name (every
    formula reads it). A tab with no reference stays as it is."""
    m = TAB_REF.match(tab.strip())
    if not m:
        return tab
    ref, rest = m.group(1), m.group(2).strip()
    rest = re.sub(r"^\d{4}\s*-\s*", "", rest)               # the firm code the reference already stands for
    if LEAD_WORD.match(rest):
        rest = "Lead schedule"
    return f"{ref}   {rest}"


def _a0_summary(wb) -> None:
    """A0's one-line summary beside its counts: all checks agree (green), or how many red and amber to look at."""
    if A0 not in wb.sheetnames:
        return
    ws = wb[A0]
    cell = ws["C3"]
    if cell.value not in (None, "") or _merged(cell):
        return
    cell.value = '=IF(B3+B4=0,"All checks agree",B3&" red and "&B4&" amber to look at")'
    cell.font = Font(name="Calibri", size=12, bold=True)
    ws.conditional_formatting.add("C3", FormulaRule(formula=["AND($B$3=0,$B$4=0)"], fill=GOOD_FILL, font=GOOD_FONT))
    ws.conditional_formatting.add("C3", FormulaRule(formula=["$B$3>0"], fill=BAD_FILL, font=BAD_FONT))
    ws.conditional_formatting.add("C3", FormulaRule(formula=["AND($B$3=0,$B$4>0)"], fill=AMBER_FILL, font=AMBER_FONT))
