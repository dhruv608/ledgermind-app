"""G10.3 accrual schedule: one row per accrual journal, its basis, the total checked to the ETB.
Made-up journals."""
import os
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import openpyxl
from openpyxl.styles import Font

from backend.app.services.workbook.balance_sheet import _accrual_schedule


def test_schedule_rows_basis_and_check():
    wb = openpyxl.Workbook()
    wb.active.title = "A"
    wb.create_sheet("G10 - Accruals")
    journals = [
        {"no": 3, "narrative": "Reverse last year's accrual: Rent", "code": "5360", "debit": 900.0, "credit": None},
        {"no": 3, "narrative": "Reverse last year's accrual: Rent", "code": "3100", "debit": None, "credit": 900.0},
        {"no": 5, "narrative": "Accountancy fee accrued", "code": "3350", "debit": 1200.0, "credit": None},
        {"no": 5, "narrative": "Accountancy fee accrued", "code": "5360", "debit": None, "credit": 1200.0},
        {"no": 6, "narrative": "Depreciation", "code": "3400", "debit": 50.0, "credit": None}]
    _accrual_schedule(N(wb=wb, journals=journals, bold_font=Font(bold=True)))
    ws = wb["G10.3 - Accrual schedule"]
    got = {ws.cell(row=r, column=1).value: (ws.cell(row=r, column=4).value, ws.cell(row=r, column=5).value)
           for r in range(7, 9)}
    assert got == {3: ("Last year's accrual reversed", -900.0), 5: ("Fixed fee", 1200.0)}
    labels = [ws.cell(row=r, column=2).value for r in range(7, 14)]
    assert "Check: schedule v B1-ETB journals (must be nil)" in labels


def test_no_accrual_journals_no_tab():
    wb = openpyxl.Workbook()
    wb.create_sheet("G10 - Accruals")
    _accrual_schedule(N(wb=wb, journals=[{"no": 1, "narrative": "Depreciation", "code": "3400", "debit": 5.0}],
                        bold_font=Font(bold=True)))
    assert "G10.3 - Accrual schedule" not in wb.sheetnames
