"""Payroll on three tabs: the report (G6.2), the ledger (G6.2.1) with the GL accounts behind each
column, and the report v the ledger (G6.2.2)."""
from openpyxl import Workbook

from backend.app.services.papers.payroll_months import by_codes
from backend.app.services.workbook.payroll.build import DIFF_TAB, LEDGER_TAB, _accounts_of, _new_tab


def test_new_tabs_sit_after_the_summary_in_order():
    wb = Workbook()
    wb.active.title = "G6.2 - Payroll summary"
    wb.create_sheet("G6.3 - Avg. No. of Employee")
    at = wb.sheetnames.index("G6.2 - Payroll summary") + 1
    _new_tab(wb, LEDGER_TAB, at, "G6.2.1")
    _new_tab(wb, DIFF_TAB, at + 1, "G6.2.2")
    assert wb.sheetnames == ["G6.2 - Payroll summary", LEDGER_TAB, DIFF_TAB, "G6.3 - Avg. No. of Employee"]
    assert wb[LEDGER_TAB]["E1"].value == "G6.2.1"
    # Built again (a rebuild of the workbook): replaced, not doubled
    _new_tab(wb, LEDGER_TAB, at, "G6.2.1")
    assert wb.sheetnames.count(LEDGER_TAB) == 1


def test_taken_from_names_each_ledger_account_once():
    rows = [("2025-01-31", "3000", None, "Gross wages"), ("2025-02-28", "3000", None, "Gross wages"),
            ("2025-02-28", "3004", None, "Casual wages"), ("2023-02-28", "3001", None, "Employers NI"),
            ("2025-02-28", "5330", None, "Net wages")]
    month_of = lambda tx: None if tx[0].startswith("2023") else tx[0][:7]
    assert _accounts_of(rows, by_codes(3000, 3004), month_of) == "3000 Gross wages; 3004 Casual wages"
    assert _accounts_of(rows, by_codes(3001, 3011), month_of) == ""      # only outside the year
