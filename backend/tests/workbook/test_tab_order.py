"""Tab order: core pack in the reviewers' order, extra review tabs in an appendix at the back."""

import openpyxl

from backend.app.services.workbook.tab_order import order_tabs, spec_order

BUILT = ["A", "A0 - Checks", "A1 - General checks", "A5 - Accounts & CT checklist", "COA", "Notes & Queries",
         "B1-ETB", "B2-Journals", "TTB", "PY-TB - Last year's TB", "OBD - Opening balances", "Re-analysis",
         "General Ledger Detail", "B3 - BS ledgers", "C", "C1 (LEAD)", "E3.2 - Prepayment review", "F", "F1 (LEAD)",
         "F3.1 - 4800 - Current account", "Bank notes", "G", "G2.3 - Duplicates review", "G3- DLA",
         "G3.2 - Related parties", "G10 - Accruals", "H", "H1-Taxation", "H2 - CT600 boxes", "J", "K",
         "K0 - Pattern review", "K0.2 - GL scrutiny", "K1 - Sales", "K2 - Rent"]


def test_spec_order():
    assert spec_order(BUILT) == [
        "A", "A0 - Checks", "Notes & Queries",
        "PY-TB - Last year's TB", "COA", "OBD - Opening balances",
        "General Ledger Detail", "TTB",
        "B1-ETB", "B2-Journals", "Re-analysis", "B3 - BS ledgers",
        "C", "C1 (LEAD)", "E3.2 - Prepayment review",
        "F", "F1 (LEAD)", "F3.1 - 4800 - Current account", "Bank notes",     # an unnamed tab stays where it was
        "G", "G3- DLA", "G10 - Accruals", "H", "H1-Taxation", "J", "K", "K1 - Sales", "K2 - Rent",
        "A1 - General checks", "A5 - Accounts & CT checklist", "G2.3 - Duplicates review", "G3.2 - Related parties",
        "H2 - CT600 boxes", "K0 - Pattern review", "K0.2 - GL scrutiny"]


def test_order_tabs_moves_sheets_and_opens_on_cover():
    wb = openpyxl.Workbook()
    wb.active.title = "K1 - Sales"
    for title in ["A1 - General checks", "TTB", "A", "G10 - Accruals"]:
        wb.create_sheet(title)
    wb["A"]["B2"] = "='K1 - Sales'!A1"
    wb.active = wb.sheetnames.index("G10 - Accruals")
    order_tabs(wb)
    assert wb.sheetnames == ["A", "TTB", "G10 - Accruals", "K1 - Sales", "A1 - General checks"]
    assert wb.active.title == "A"
    assert [ws.sheet_view.tabSelected for ws in wb.worksheets] == [True, False, False, False, False]
    assert wb["A"]["B2"].value == "='K1 - Sales'!A1"


def test_each_control_before_its_ledger_and_numbers_as_numbers():
    built = ["E", "E2.1-Debtors NL ", "E3.2 - Prepayment review", "E2-Trade Debtors", "E1 (LEAD)",
             "G", "G10.3 - Accruals detail", "G6.4 - Payroll notes", "G10 - Accruals", "G6 - Net Wages",
             "C1-2 - Depreciation rates", "C1-1-FA detail", "C"]
    assert spec_order(built) == ["C", "C1-1-FA detail", "C1-2 - Depreciation rates",
                                 "E", "E1 (LEAD)", "E2-Trade Debtors", "E2.1-Debtors NL ", "E3.2 - Prepayment review",
                                 "G", "G6 - Net Wages", "G6.4 - Payroll notes", "G10 - Accruals",
                                 "G10.3 - Accruals detail"]
