"""Loan month by month, from the ledger lines on the loan tab."""

from datetime import date

import openpyxl

from backend.app.services.workbook.balance_tabs.loans import _monthly_table


def test_months_from_the_ledger_lines():
    ws = openpyxl.Workbook().active
    ws["D8"] = 10000
    # (date, account, ..., debit index 7, credit index 8)
    lines = [("15/04/2025", "", "", "Loan", "", "Repayment", "", 500.0, 0.0),
             ("15/05/2025", "", "", "Loan", "", "Repayment", "", 500.0, 0.0),
             ("31/05/2025", "", "", "Loan", "", "Interest", "", 0.0, 40.0),
             ("02/02/2024", "", "", "Loan", "", "Old line", "", 0.0, 7.0)]
    _monthly_table(ws, 40, lines, date(2026, 3, 31))
    assert ws["A40"].value == "Month by month"
    assert ws["A42"].value == date(2025, 4, 30) and ws["B42"].value == "=D8" and ws["C42"].value == 500.0
    assert ws["B43"].value == "=F42" and ws["E43"].value == 40.0 and ws["F43"].value == "=B43-C43+E43"
    assert ws["A54"].value == "Other dates" and ws["E54"].value == 7.0
    assert ws["F55"].value == "=ROUND((D10)-F54,2)"
