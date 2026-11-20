"""H1.2 capital allowances: the computation per pool, as the CT computation worked it.

Pool | WDV b/f | Additions | AIA / FYA / full expensing | Disposals | Balancing charge | Balancing allowance | WDA |
WDV c/f | Note. The figures are the computation's own (tax/ct_compute.py, CTComputation.pools); the check ties the
allowances here to H1's 'Less: capital allowances' line."""

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from backend.app.services.workbook.balance_tabs import _new_sheet

CA_TAB = "H1.2 - Capital allowances"
HEADS = ["Pool", "WDV b/f", "Additions", "AIA / FYA / full expensing", "Disposals", "Balancing charge",
         "Balancing allowance", "WDA", "WDV c/f", "Note"]
KEYS = ["bf", "additions", "aia_fya", "disposals", "balancing_charge", "balancing_allowance", "wda", "cf"]
MONEY = "#,##0.00;(#,##0.00)"
BOLD = Font(name="Calibri", size=10, bold=True)


def ca_tab(ctx, comp, h1_title: str) -> None:
    pools = getattr(comp, "pools", None) or []
    if not pools or all(abs(p.get(k, 0.0)) < 0.005 for p in pools for k in KEYS):
        return                                           # no assets, no pools: nothing to show
    ws = _new_sheet(ctx, CA_TAB, [h1_title, "H"])
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    ws["J1"] = "H1.2"
    ws["A4"] = "Capital allowances by pool"
    ws["A4"].font = BOLD
    for c, head in enumerate(HEADS, 1):
        ws.cell(row=6, column=c, value=head).font = BOLD
    r = 7
    for p in pools:
        ws.cell(row=r, column=1, value=p["pool"])
        for c, key in enumerate(KEYS, 2):
            ws.cell(row=r, column=c, value=p.get(key, 0.0)).number_format = MONEY
        if p.get("note"):
            ws.cell(row=r, column=10, value=p["note"])
        r += 1
    total = r
    ws.cell(row=total, column=1, value="Total").font = BOLD
    for c in range(2, 10):
        cell = ws.cell(row=total, column=c, value=f"=SUM({get_column_letter(c)}7:{get_column_letter(c)}{total - 1})")
        cell.number_format, cell.font = MONEY, BOLD
    # The allowances here (AIA / FYA and WDA) against H1's 'Less: capital allowances' (a negative there)
    h1 = ctx.wb[h1_title] if h1_title in ctx.wb.sheetnames else None
    less = next((row for row in range(1, (h1.max_row if h1 is not None else 0) + 1)
                 if str(h1.cell(row=row, column=2).value or "").strip() == "Less: capital allowances"), None)
    if less is not None:
        ws.cell(row=total + 2, column=1, value="Check: allowances here less H1's capital allowances (must be nil)").font = BOLD
        ws.cell(row=total + 2, column=9, value=f"=ROUND(D{total}+H{total}+'{h1_title}'!D{less},2)").number_format = MONEY
    ws.column_dimensions["A"].width = 44
    for c in range(2, 10):
        ws.column_dimensions[get_column_letter(c)].width = 15
    ws.column_dimensions["J"].width = 40
