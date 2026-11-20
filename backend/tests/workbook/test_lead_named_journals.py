"""Each adjusting journal on its own line by name on a lead, read from B2 by its number, with the
total checked against the ETB's journal columns. Made-up journals."""
from types import SimpleNamespace as N

import openpyxl

from backend.app.services.workbook.balance_tabs import lead_lines


def _ws():
    return openpyxl.Workbook().active


def test_named_journal_lines_and_check():
    ctx = N(tb_kind="movement", journals=[
        {"no": 1, "narrative": "Accountancy fee accrued", "code": "5360", "debit": None, "credit": 1200.0},
        {"no": 1, "narrative": "Accountancy fee accrued", "code": "3350", "debit": 1200.0, "credit": None},
        {"no": 4, "narrative": "Last year's accrual reversed", "code": "5360", "debit": 900.0, "credit": None},
        {"no": 2, "narrative": "Depreciation", "code": "3400", "debit": 50.0, "credit": None}])
    ws = _ws()
    rows = lead_lines(ctx, ws, [5360], owed=True)
    labels = {ws.cell(row=r, column=2).value: r for r in range(8, rows["end"] + 1)}
    assert "  Journal 1: Accountancy fee accrued" in labels and "  Journal 4: Last year's accrual reversed" in labels
    assert not any("Depreciation" in str(k) for k in labels)              # not on this code
    j1 = ws.cell(row=labels["  Journal 1: Accountancy fee accrued"], column=4).value
    assert "'B2-Journals'!$A:$A,1" in j1 and "'B2-Journals'!$E:$E,5360" in j1
    total_r = labels["Adjusting journals (B2), total"]
    assert ws.cell(row=total_r, column=4).value.startswith("=SUM(D")
    assert "Check: journals by name v B1-ETB journals (must be nil)" in labels
    cf = ws.cell(row=rows["cf"], column=4).value
    assert f"D{total_r}" in cf


def test_no_journals_keeps_one_line():
    ws = _ws()
    rows = lead_lines(N(tb_kind="movement", journals=[]), ws, [5360])
    labels = [ws.cell(row=r, column=2).value for r in range(8, rows["end"] + 1)]
    assert "Adjusting journals (B2)" in labels and not any("by name" in str(l) for l in labels)
