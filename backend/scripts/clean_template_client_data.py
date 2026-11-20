"""
Remove the source client's data that was left in the master workpaper template.
Keeps every formula, label, format and the sheet layout; blanks typed-in figures, dates and names.

Run from the project root:  python backend/scripts/clean_template_client_data.py
"""

import sys
from datetime import date, datetime
from pathlib import Path

import openpyxl

TEMPLATE = Path(__file__).resolve().parent.parent / "app" / "templates" / "master_workpapers_template.xlsx"

# Sheets that are whole lists of the source client's transactions: blank every typed value below the header row
DATA_LIST_SHEETS = {
    "G9.2 - Late claims": 7,          # header row 7 (Date, Account, Reference, Details, VAT, Net)
    "G9.4-VAT - HMRC details": 4,     # header row 4 (Date, Payment Description, Period, ...)
    "D2.2 - Stock details": 6,        # precious-metal weights and spot prices
}

# Lead / summary sheets: keep labels, blank typed-in numbers and dates from the first data row down
SUMMARY_SHEETS = {
    "E3 - Prepayments": 8,
    "F2-Bank": 8,
    "G3- DLA": 8,
    "G8-Pension Payable": 7,
    "G9 - VAT": 7,
    "G9-.1-VAT Summary": 7,
    "H1-Taxation": 7,
}

# Nominal-ledger tabs: everything from row 7 down is the source client's transactions (rebuilt per client)
LEDGER_SHEETS = [
    "D2.1 - NL Transactions", "E2.1-Debtors NL ", "E3.1 NL Analysis", "F2.1-NL Transaction",
    "G2.1- Creditors NL", "G3.1 - DLA-NL Transactions", "G6.1 - NL Analysis", "G7.1 - NL Analysis",
    "G8.1 - NL Analysis", "G9.3-VAT-NL Transactions ", "G10.1 - NL Transactions",
]
LEDGER_FIRST_ROW = 7

# Whole tabs of the source client's own schedules: clear everything (values and formulas) from this row down
CLEAR_FROM_ROW = {
    "G6.2 - Payroll summary": 8,   # per-employee payroll of the source client
    "G10 - Accruals": 8,           # source client's accrual lines and transaction list
    "K": 8,                        # index of the source client's P&L tabs
    "Re-analysis": 8,
    "Notes & Queries": 5,
    "G9-.1-VAT Summary": 23,       # source client's HMRC payment lines (with its HMRC reference)
}

# More summary tabs where only typed-in figures and dates are blanked
SUMMARY_SHEETS.update({
    "G6 - Net Wages": 8,
    "G6.3 - Avg. No. of Employee": 8,
    "G7-PAYE liabilities": 7,
})

# Links to the source client's own loan tabs (those tabs are always removed)
LINK_CELLS = {"G": ["E18", "E20"], "G1 (LEAD)": ["C13", "C15"]}

# Individual cells holding the source client's names, titles or account labels
NAMED_CELLS = {
    "G3- DLA": {"G7": None, "I7": None,                                     # source client's directors
                "B12": "5400 - Directors loan account", "B13": None, "D13": None, "I13": None},
    "G9.4-VAT - HMRC details": {"A1": "=A!B2"},                             # the source client's title
    "General Ledger Detail": {"B2": "=A!B2"},
    "E2.2-A R Ageing Detail": {"A2": "=A!B2"},
    "G2.2 - A P Ageing Details": {"A2": "=A!B2"},
    "F1 (LEAD)": {"A8": "Bank"},
    "F2-Bank": {"A4": "Bank"},
    "F2.1-NL Transaction": {"A4": "Bank"},
    "G10 - Accruals": {"H6": None},                                          # note about the source client
    # ETB fixed rows named after the source client's own accounts
    "B1-ETB": {"B11": "Other cost of sales (not in firm chart)", "B47": "Bank current account (2)",
               "B58": "Other loan (not in firm chart)"},
}


def blank(cell) -> None:
    cell.value = None
    cell.hyperlink = None


def is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=")


def is_year_heading(value) -> bool:
    return isinstance(value, int) and 2000 <= value <= 2100


def main() -> None:
    wb = openpyxl.load_workbook(TEMPLATE)
    blanked = {}

    for sheet, header_row in DATA_LIST_SHEETS.items():
        ws = wb[sheet]
        n = 0
        for row in ws.iter_rows(min_row=header_row + 1):
            for cell in row:
                if cell.value is not None and not is_formula(cell.value):
                    blank(cell)
                    n += 1
        blanked[sheet] = n

    for sheet, first_row in SUMMARY_SHEETS.items():
        ws = wb[sheet]
        n = 0
        for row in ws.iter_rows(min_row=first_row):
            for cell in row:
                v = cell.value
                if isinstance(v, bool) or v is None or is_formula(v) or is_year_heading(v):
                    continue
                if isinstance(v, (int, float, datetime, date)):
                    blank(cell)
                    n += 1
        blanked[sheet] = n

    for sheet in LEDGER_SHEETS:
        ws = wb[sheet]
        n = 0
        for row in ws.iter_rows(min_row=LEDGER_FIRST_ROW):
            for cell in row:
                if cell.value is not None or cell.hyperlink is not None:
                    blank(cell)
                    n += 1
        # account names typed into the header rows beyond the standard ledger columns
        for row in ws.iter_rows(min_row=5, max_row=LEDGER_FIRST_ROW - 1, min_col=15):
            for cell in row:
                if cell.value is not None or cell.hyperlink is not None:
                    blank(cell)
                    n += 1
        blanked[sheet] = n

    for sheet, first_row in CLEAR_FROM_ROW.items():
        ws = wb[sheet]
        n = 0
        for row in ws.iter_rows(min_row=first_row):
            for cell in row:
                if cell.value is not None or cell.hyperlink is not None:
                    blank(cell)
                    n += 1
        blanked[sheet] = n

    for sheet, cells in NAMED_CELLS.items():
        for ref, new_value in cells.items():
            wb[sheet][ref] = new_value
        blanked[sheet] = blanked.get(sheet, 0) + len(cells)

    for sheet, refs in LINK_CELLS.items():
        for ref in refs:
            blank(wb[sheet][ref])
        blanked[sheet] = blanked.get(sheet, 0) + len(refs)

    # Leftover source-client adjusting journal (Dr 3000 / Cr 5330 net wages) in rows 6-8 of B2-Journals
    ws = wb["B2-Journals"]
    for r in range(6, 9):
        for c in range(1, ws.max_column + 1):
            ws.cell(row=r, column=c).value = None
    blanked["B2-Journals"] = "rows 6-8"

    # J2 prior-year column referenced an 'OBD' sheet that is not in the template
    ws = wb["J2 - Reserves"]
    for ref in ("F8", "F10"):
        if is_formula(ws[ref].value) and "OBD!" in ws[ref].value:
            ws[ref] = None
    blanked["J2 - Reserves"] = "F8, F10 (OBD references)"

    wb.save(TEMPLATE)
    for sheet, n in blanked.items():
        print(f"  {sheet:28} {n}")
    print(f"Saved {TEMPLATE}")


if __name__ == "__main__":
    sys.exit(main())
