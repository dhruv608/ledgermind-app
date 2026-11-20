"""I - Deferred tax: fixed asset NBV less tax WDV, times the rate.

The working of CT-DT-001 (workbook/ct600.py deferred_tax_working): net book value from the ETB, the tax value (pools
carried forward), the difference at the rate expected when it reverses, against what the books hold; the movement is
the journal the review proposes, for the accountant to approve or reject. A micro-entity has
none (FRS 105 para 24.7): the tab says so. Only for a company with fixed assets."""

from openpyxl.styles import Font

from backend.app.services.workbook.ct600 import deferred_tax_working

SHEET = "I - Deferred tax"
MONEY = '#,##0.00;(#,##0.00);"-"'
ETB = "'B1-ETB'!"


def add_deferred_tax_tab(wb, comp, engagement, balances, chart) -> None:
    nbv = round(sum(v for code, v in balances.items() if 4120 <= code <= 4199), 2)     # no land and property
    if nbv < 1 or "B1-ETB" not in wb.sheetnames:
        return
    after = next((n for n in ("H2 - CT600", "H1-Taxation") if n in wb.sheetnames), None)
    ws = wb.create_sheet(SHEET, wb.sheetnames.index(after) + 1 if after else None)
    bold = Font(name="Calibri", size=10, bold=True)
    ws["A1"], ws["A2"], ws["E1"] = "=A!B2", "='Notes & Queries'!A2", "I"
    ws["A4"] = "Deferred tax on fixed assets"
    ws["A4"].font = bold
    dt = deferred_tax_working(engagement, comp, balances, chart)
    if dt is None:
        ws["A6"] = ("No deferred tax: the company is a micro-entity (FRS 105 para 24.7, or within two of the three "
                    "micro limits, CA 2006 s384A).")
        ws.column_dimensions["A"].width = 60
        return
    rows = [
        ("Net book value of fixed assets that get capital allowances (B1-ETB final, 4120-4199; land and property left "
         "out: no allowances, a permanent difference, FRS 102 29.8 / 29.10)",
         f'=SUMIFS({ETB}$N:$N,{ETB}$A:$A,">=4120",{ETB}$A:$A,"<=4199")'),
        ("Tax written-down value (pools carried forward)" + (
            " - last year's, from its working paper (pools not entered)" if dt.get("wdv_source") == "last_year_wp"
            else " - pools not entered, taken as nil" if comp.pools_missing else ""), dt["wdv"]),
        ("Allowances given ahead of depreciation", "=MAX(B6-B7,0)"),
        ("Rate expected when it reverses", dt["rate"]),
        ("Deferred tax needed (FRS 102 s29)", "=ROUND(B8*B9,2)"),
        ("Deferred tax in the books (B1-ETB final, 6100-6199)",
         f'=-SUMIFS({ETB}$N:$N,{ETB}$A:$A,">=6100",{ETB}$A:$A,"<=6199")'),
        ("Movement to provide (proposed journal Dr 3801 / Cr 6100; approve or reject it)", "=B10-B11"),
    ]
    for i, (label, value) in enumerate(rows, start=6):
        ws.cell(row=i, column=1, value=label)
        cell = ws.cell(row=i, column=2, value=value)
        cell.number_format = "0.0%" if "Rate" in label else MONEY
    ws["A12"].font = ws["B12"].font = bold
    ws["A14"] = ("Small companies show it in the notes (FRS 102 1AC). Once the journal is approved the books hold the "
                 "provision and the movement is nil; rejected, the provision is not made (the accountant's choice).")
    ws.column_dimensions["A"].width = 72
    ws.column_dimensions["B"].width = 16
