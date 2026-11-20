"""Other debtors: deposits (E4), s455 recoverable (E5) and their lines on the E1 lead."""

from typing import Optional

from backend.app.services.workbook.balance_tabs.common import (
    BOLD, Context, DEPOSIT_WORDS, on_tab, OTHER_DEBTORS, S455_CODES, TITLE, _etb, _etb_bf, _has_balance, _lines_for, _money,
    _new_sheet, _records, _write_lines
)
from backend.app.services.workbook.balance_tabs.t_shape import t_account


# ------------------------------------------------------------------------------------------------------------------
# Other debtors - deposits (E4) and s455 recoverable (E5), added to the E1 lead
# ------------------------------------------------------------------------------------------------------------------
def deposit_tab(ctx: Context) -> Optional[str]:
    records = [t for t in _records(ctx, OTHER_DEBTORS) if DEPOSIT_WORDS.search(t.raw_account_name or "")]
    codes = sorted({t.std_code for t in records})
    if not codes or not _has_balance(ctx, codes):
        return None
    ws = _new_sheet(ctx, "E4 - Deposits", ["E3.2 - Prepayment review", "E3.1 NL Analysis", "E3 - Prepayments", "E1 (LEAD)"])
    ws["E1"] = "E4"
    ws["A4"] = "Other debtors - deposits"
    ws["A4"].font = TITLE
    # The deposits as one T; the E1 lead reads its b/f and c/d
    rows = t_account(ctx, ws, codes, top=6)
    ctx.lead_rows[ws.title] = rows
    below = rows["end"] + 1
    others = [t.raw_account_name for t in _records(ctx, codes) if t not in records]
    if others:
        ws.cell(row=below, column=2, value="The code also holds: " + ", ".join(others)[:200])
    _write_lines(ws, below + 2, "Ledger lines this year", _lines_for(ctx, [t.raw_account_name for t in records]),
                 "Paid (Dr)", "Returned (Cr)")
    ws["B30" if ws.max_row < 30 else f"B{ws.max_row + 2}"] = "Check each deposit is still held (agreement or letting terms)."
    return ws.title


def s455_tab(ctx: Context) -> Optional[str]:
    if ctx.s455_tax < 0.005 and not _has_balance(ctx, S455_CODES):
        return None
    ws = _new_sheet(ctx, "E5 - s455", ["E4 - Deposits", "E3.2 - Prepayment review", "E3 - Prepayments", "E1 (LEAD)"])
    ws["E1"] = "E5"
    ws["A4"] = "s455 tax on the directors' loan - recoverable"
    ws["A4"].font = TITLE
    ws["D6"] = "Amount £"
    ws["D6"].font = BOLD
    ws["B8"] = "s455 tax per the corporation tax computation (H1)"
    _money(ws.cell(row=8, column=4, value=round(ctx.s455_tax, 2)))
    if ctx.s455_note:
        ws["B9"] = ctx.s455_note[:250]
    ws["B11"] = "s455 recoverable in the books (4450 / 4550, ETB)"
    _money(ws.cell(row=11, column=4, value=f"={_etb(S455_CODES, 'N')}"))
    ws["B12"] = "Difference: computation less the books"
    ws["B12"].font = BOLD
    _money(ws.cell(row=12, column=4, value="=ROUND(D8-D11,2)"), bold=True)
    ws["B14"] = ("The tax is repaid by HMRC 9 months after the end of the period in which the loan is repaid, "
                 "released or written off. If it is recorded: Dr 4550 Corporation tax recoverable / Cr 5310 "
                 "Corporation tax.")
    return ws.title


def _debtors_lead(ctx: Context, deposit: Optional[str], s455: Optional[str]) -> None:
    # Other debtors with a balance (not deposits, which have their own tab) get their own lead row: every balance
    # sheet code with a balance is on a lead
    deposit_records = [t for t in _records(ctx, OTHER_DEBTORS) if DEPOSIT_WORDS.search(t.raw_account_name or "")]
    other = [t for t in _records(ctx, OTHER_DEBTORS) if t not in deposit_records
             and (abs(float(t.net_amount or 0)) >= 0.005 or abs(float(t.opening_amount or 0)) >= 0.005)]
    if "E1 (LEAD)" not in ctx.wb.sheetnames or not (deposit or s455 or other):
        return
    ws = ctx.wb["E1 (LEAD)"]
    for c in "BCDE":
        ws[f"{c}12"] = None
    r = 12
    if other:
        codes = sorted({int(t.std_code) for t in other})
        ws[f"B{r}"] = "OTHER DEBTORS"
        ws[f"C{r}"] = ", ".join(str(c) for c in codes)
        # (by code; a deposit account on the same code is on E4, so only the non-deposit accounts are added)
        _money(ws[f"D{r}"]).value = round(sum(float(t.net_amount or 0) for t in other), 2) if deposit_records \
            else f"={_etb(codes, 'N')}"
        _money(ws[f"E{r}"]).value = round(sum(float(t.opening_amount or 0) for t in other), 2) if deposit_records \
            else f"={_etb_bf(codes)}"
        r += 2
    for tab, label in ((deposit, "OTHER DEBTORS - DEPOSITS"), (s455, "S455 RECOVERABLE")):
        if not tab:
            continue
        rows = ctx.lead_rows.get(tab)
        ws[f"B{r}"] = label
        ws[f"C{r}"] = tab.split(" - ")[0]
        if rows:                                   # a T tab: its own c/d and b/f
            _money(ws[f"D{r}"]).value = f"={on_tab(tab, rows['cf_s'])}"
            _money(ws[f"E{r}"]).value = f"={on_tab(tab, rows['bf_s'])}"
        else:                                      # E5 s455: the books' figure on D11
            _money(ws[f"D{r}"]).value = f"='{tab}'!D11"
            _money(ws[f"E{r}"]).value = f"=({_etb(S455_CODES, 'F')})-({_etb(S455_CODES, 'G')})"
        r += 2
    for c, col in ((4, "D"), (5, "E")):
        _money(ws.cell(row=r, column=c, value=f"=SUM({col}8:{col}{r - 1})"), bold=True, total=True)
