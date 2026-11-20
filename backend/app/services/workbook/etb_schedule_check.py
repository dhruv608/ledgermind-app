"""B1-ETB 'final less schedule c/fwd', a check column: for each code a schedule tab covers on its own (each bank F3.n, credit card F4.n, net wages G6, PAYE G7, VAT G9, CT H1, DLA G3), the ETB final balance less the
tab's carried-forward cell (a tab showing amounts owed as positive, the payroll controls, is added instead); the
column's total sits on the ETB's 'Check (must be 0)' row, so A0 lists it."""

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

ETB = "B1-ETB"
COLUMN = 26                       # Z: after the spec final (X) and books less spec (Y)
HEAD_ROW, UNIT_ROW, FIRST = 6, 7, 8
FINAL = "N"                       # the ETB's final balance (debit +)
MONEY = "#,##0.00;(#,##0.00)"


def add_schedule_check(wb, schedule_cf: dict) -> None:
    if ETB not in wb.sheetnames or not schedule_cf:
        return
    ws = wb[ETB]
    check_row = next((r for r in range(FIRST, ws.max_row + 1)
                      if str(ws.cell(row=r, column=2).value or "").startswith("Check (must be 0)")), None)
    if check_row is None:
        return
    col = get_column_letter(COLUMN)
    ws.cell(row=HEAD_ROW, column=COLUMN, value="Final less schedule c/fwd").font = Font(name="Calibri", size=10, bold=True)
    ws.cell(row=UNIT_ROW, column=COLUMN, value="£")
    ws.column_dimensions[col].width = 16
    for r in range(FIRST, check_row):
        code = ws.cell(row=r, column=1).value
        if isinstance(code, int) and code in schedule_cf:
            cell, sign = schedule_cf[code]
            minus = "-" if sign > 0 else "+"          # a tab showing amounts owed as positive is added back
            ws.cell(row=r, column=COLUMN, value=f"=ROUND({FINAL}{r}{minus}{cell},2)").number_format = MONEY
    ws.cell(row=check_row, column=COLUMN,
            value=f"=ROUND(SUMPRODUCT(ABS({col}{FIRST}:{col}{check_row - 1})),2)").number_format = MONEY
