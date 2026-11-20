"""Formats, tab lists, small classes and the sheet helpers the bank-only workbook's parts share."""

from typing import Dict

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

from backend.app.services.bank_only.ledger import CREDITORS, DEBTORS
from backend.app.services.workbook.tidy import MONEY_FORMAT


MONEY = MONEY_FORMAT

DATE = "dd/mm/yyyy"

TITLE = Font(name="Calibri", bold=True, size=12)

BOLD = Font(name="Calibri", bold=True)

ITALIC = Font(name="Calibri", italic=True)

HEAD_FILL = PatternFill("solid", fgColor="DDEBF7")

THIN = Side(style="thin")

TOTAL_BORDER = Border(top=THIN, bottom=Side(style="double"))

WRAP = Alignment(wrap_text=True, vertical="top")

P_AND_L_END = 4000          # firm codes below this are profit and loss

# Balance tabs: (tab, title, firm codes). A tab is left out when none of its codes has a balance or a movement.
BALANCE_TABS = [
    ("Trade Debtors", "Trade Debtors", [DEBTORS]),
    ("Trade Creditors", "Trade Creditors", [CREDITORS]),
    ("Other Creditors", "Other Creditors", [5350]),
    ("Bank Loan", "Bank Loan", [5100, 5110, 5500, 5510]),
    ("Hire Purchase", "Hire Purchase", [5000, 5001, 5002]),
    ("Net Wages", "Net Wages", [5330]),
    ("PAYE & NI", "PAYE & NI", [5320]),
    ("Pension", "Pension Payable", [5351, 5352]),
    ("Accruals", "Accruals", [5360]),
    ("Director Loan Account", "Director Loan Account", list(range(5400, 5410))),
    ("Corporation Tax", "Corporation Tax", [5310]),
    ("Ordinary Shares", "Ordinary Shares", list(range(7000, 7010))),
]

NAMED_FROM_LAST_YEAR = {"Bank Loan", "Hire Purchase", "PAYE & NI", "Pension"}

SHEET_ORDER = ["Notes", "Transactions", "TB", "Trial Balance", "Journals", "Fixed Assets", "FAR", "Trade Debtors",
               "Sales Invoices", "Debtor Listing", "Bank Account", "Bank Receipts", "Bank Payments", "Trade Creditors",
               "Purchase Bills", "Duplicates Review", "Other Creditors", "Bank Loan", "Hire Purchase", "Net Wages", "PAYE & NI", "Pension",
               "Accruals", "Director Loan Account",
               "Corporation Tax", "Ordinary Shares", "Bank Statement", "App checks"]

class BooksChanged(ValueError):
    """The books on the Books tab no longer agree with the trial balance made from them."""

def ref(sheet: str, cell: str) -> str:
    return f"'{sheet}'!{cell}"

class Columns:
    """The accounts a tab spreads its lines into: one column each, in order of first use, with a unique heading
    (the head text a line carries must equal its column heading for the IF formulas)."""

    def __init__(self, first: int):
        self.first, self.keys, self.label, self.code = first, [], {}, {}

    def add(self, key, label: str, code: int) -> None:
        if key in self.label:
            return
        if label in self.label.values():
            label = f"{label} ({code})"
        self.keys.append(key)
        self.label[key], self.code[key] = label, code

    def col(self, key) -> int:
        return self.first + self.keys.index(key)

    @property
    def last(self) -> int:
        return self.first + len(self.keys) - 1


class SheetHelpers:
    """Cell helpers every tab writer uses (a title, an amount, a date, a total, column widths): the base of
    each part of BooksWorkbook."""

    @staticmethod
    def heading(ws, row: int, cols: Dict[int, str]) -> None:
        for c, text in cols.items():
            cell = ws.cell(row=row, column=c, value=text)
            cell.font, cell.fill = BOLD, HEAD_FILL
            cell.alignment = Alignment(wrap_text=True, vertical="center")

    @staticmethod
    def money(ws, row: int, col: int, value, bold: bool = False):
        cell = ws.cell(row=row, column=col, value=value)
        cell.number_format = MONEY
        if bold:
            cell.font = BOLD
        return cell

    @staticmethod
    def date(ws, row: int, col: int, value):
        cell = ws.cell(row=row, column=col, value=value)
        cell.number_format = DATE
        return cell

    @classmethod
    def total(cls, ws, row: int, col: int, first: int, last: int):
        cell = cls.money(ws, row, col, f"=SUM({L(col)}{first}:{L(col)}{max(last, first)})", bold=True)
        cell.border = TOTAL_BORDER
        return cell

    @staticmethod
    def widths(ws, **cols: float) -> None:
        for letter, w in cols.items():
            ws.column_dimensions[letter].width = w
