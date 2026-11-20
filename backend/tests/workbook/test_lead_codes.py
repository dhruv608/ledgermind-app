"""Leads from the ETB codes: a code no lead row holds gets its own row inside the lead's total, and
every code of the lead is listed with a check that the total is all of them."""

from openpyxl import Workbook

from backend.app.services.workbook.checks_tab import find_checks
from backend.app.services.workbook.lead_codes import CHECK, OTHER, add_lead_codes


def _book():
    wb = Workbook()
    etb = wb.active
    etb.title = "B1-ETB"
    for r, (code, name) in enumerate(((0, "Sales"), (4400, "Trade debtors"), (4420, "Other debtors"),
                                      (4900, "Prepayments"), (4950, "Accrued income"), (5200, "Trade creditors")), 8):
        etb.cell(row=r, column=1, value=code)
        etb.cell(row=r, column=2, value=name)
    e2 = wb.create_sheet("E2-Trade Debtors")
    e2["D16"] = 100
    lead = wb.create_sheet("E1 (LEAD)")
    lead["D6"], lead["E6"] = "2025", "2024"
    lead["B8"], lead["D8"] = "TRADE DEBTORS", "='E2-Trade Debtors'!D16"
    lead["B10"], lead["D10"] = "PREPAYMENTS", 0.0           # no prepayments schedule: the code is not held
    lead["D12"], lead["E12"] = "=SUM(D8:D10)", "=SUM(E8:E10)"
    return wb, lead


def test_codes_with_no_row_join_the_total():
    wb, lead = _book()
    assert add_lead_codes(wb) == 1
    rows = {lead.cell(row=r, column=2).value: r for r in range(1, lead.max_row + 1)}
    first = rows[OTHER] + 1
    assert [lead.cell(row=first + i, column=1).value for i in range(3)] == [4420, 4900, 4950]
    sub = rows["Other balances"]
    assert lead["D12"].value == f"=SUM(D8:D10)+D{sub}" and lead["E12"].value == f"=SUM(E8:E10)+E{sub}"
    assert lead.cell(row=first, column=4).value == f"=SUMIF('B1-ETB'!$A:$A,$A{first},'B1-ETB'!$N:$N)"
    # every code of the lead (4400 too) listed, and the check against the lead's total
    every = rows["Every B1-ETB code of this lead (final balance)"] + 2
    assert [lead.cell(row=every + i, column=1).value for i in range(4)] == [4400, 4420, 4900, 4950]
    check = rows[CHECK]
    assert lead.cell(row=check, column=4).value == f"=ROUND(D12-D{check - 1},2)"
    assert [(t, kind) for t, _c, _l, kind in find_checks(wb)] == [("E1 (LEAD)", "RED")]


def test_creditors_shown_as_credits():
    wb, _ = _book()
    g1 = wb.create_sheet("G1 (LEAD)")
    g1["D6"] = "2025"
    g1["B9"], g1["D9"] = "Trade Creditors", "='G2 - Trade creditors'!D16"
    g1["D30"] = "=SUM(D9:D29)"
    add_lead_codes(wb)
    rows = {g1.cell(row=r, column=2).value: r for r in range(1, g1.max_row + 1)}
    assert OTHER not in rows                                # 5200 is held by the trade creditors row
    every = rows["Every B1-ETB code of this lead (final balance)"] + 2
    assert g1.cell(row=every, column=4).value.startswith("=-SUMIF(")
