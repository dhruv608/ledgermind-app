"""The pack's look and dates: fonts and fills, the year end and filing deadlines, and the Sheet writer every
schedule uses."""

from datetime import date, datetime
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


FINAL, DRAFT = "FINAL", "DRAFT"
MONEY = '#,##0.00;[Red]-#,##0.00'
TEAL = PatternFill("solid", fgColor="EEF7F7")
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=12, color="0E3B3A")
RED = Font(bold=True, color="B91C1C")
GREY = Font(color="64748B", size=9)
FIRM_QUERIES = ("Money Laundering ID all in place?", "Letter of engagement?")    # the firm's own rows on every Queries sheet


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def year_end_words(tax_year: str) -> str:
    return f"{_ordinal(5)} April {int(tax_year[:4]) + 1}"


def deadlines(tax_year: str) -> List[List]:
    """The deadlines P-DL-01..03 for the year: paper and online returns, payments, coding out."""
    from backend.app.sa.engine.calc import rates_for
    y = int(tax_year[:4]) + 1
    d = rates_for(tax_year).get("deadlines") or {"paper": [0, 10, 31], "coding_out": [0, 12, 30], "online": [1, 1, 31],
                                                 "second_poa": [1, 7, 31]}
    on = lambda k: date(y + d[k][0], d[k][1], d[k][2])
    return [["Paper return", on("paper")], ["Tax code collection (online return by)", on("coding_out")],
            ["Online return, balancing payment and first payment on account", on("online")],
            ["Second payment on account", on("second_poa")]]


class Sheet:
    """A sheet in the firm's style: the client and year end on row 1, the sheet's title on row 2, a DRAFT line if so."""

    def __init__(self, wb: Workbook, title: str, d: Dict, widths=(34, 16, 16, 16, 16, 30)):
        self.ws = wb.create_sheet("".join(" " if ch in '[]:*?/\\' else ch for ch in title)[:31])
        self.ws.append([f"Clients Name: {d['person']}", None, None, f"Year ending: {d['year_end']}"])
        self.ws["A1"].font = BOLD
        self.ws["D1"].font = BOLD
        self.ws.append([title])
        self.ws["A2"].font = TITLE
        if d["kind"] == DRAFT:
            self.ws.append([f"DRAFT version {d['version']}: {d['blocks']} block(s) open. Not for filing."])
            self.ws.cell(self.ws.max_row, 1).font = RED
        self.ws.append([])
        for i, w in enumerate(widths, start=1):
            self.ws.column_dimensions[get_column_letter(i)].width = w

    def head(self, *cols):
        self.ws.append(list(cols))
        for c in self.ws[self.ws.max_row]:
            c.font = BOLD
            c.fill = TEAL
            c.alignment = Alignment(wrap_text=True, vertical="top")

    def row(self, *vals, bold=False, note=False):
        self.ws.append(list(vals))
        for c in self.ws[self.ws.max_row]:
            if isinstance(c.value, float):          # money; whole numbers (counts, numbering) stay plain
                c.number_format = MONEY
            if isinstance(c.value, (date, datetime)):
                c.number_format = "dd/mm/yyyy"
            if bold:
                c.font = BOLD
            if note:
                c.font = GREY
            if isinstance(c.value, str) and len(c.value) > 40:
                c.alignment = Alignment(wrap_text=True, vertical="top")

    def gap(self):
        self.ws.append([])


def _money(v) -> Optional[float]:
    return None if v is None else round(float(v), 2)
