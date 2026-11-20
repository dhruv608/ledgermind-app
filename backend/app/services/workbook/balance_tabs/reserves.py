"""Dividends paid against the distributable reserves (J3)."""

from typing import Optional

from backend.app.services.workbook.balance_tabs.common import (
    BOLD, Context, DIVIDEND_CODES, RESERVE_WORDS, TITLE, _etb, _lines_for, _money, _new_sheet, _records,
    _write_lines
)


SHARE_CAPITAL = range(7000, 7035)            # the firm chart's share capital codes (J1's template range)


def share_capital_tab(ctx: Context) -> Optional[str]:
    """J1 share capital as one T, its own paper apart from the director's loan: last year's balance, the shares issued
    or bought back in the year by name, the journals, the c/d, tied to B1-ETB. It replaces the template's two-line
    summary, which would carry last year's figure into this year as well."""
    if "J1 - Share Capital" not in ctx.wb.sheetnames:
        return None
    codes = sorted({int(t.std_code) for t in _records(ctx, list(SHARE_CAPITAL))})
    if not codes:
        return None
    from backend.app.services.workbook.balance_tabs.t_shape import t_account
    ws = ctx.wb["J1 - Share Capital"]
    for row in ws.iter_rows(min_row=5, max_row=max(ws.max_row, 20), max_col=8):
        for cell in row:
            if type(cell).__name__ != "MergedCell":
                cell.value = None
    ws["A4"] = "Share capital"
    ws["A4"].font = TITLE
    t = t_account(ctx, ws, codes, top=6, owed=True)
    r = t["end"] + 2
    ws.cell(row=r, column=1, value="Agree to the confirmation statement or the register of members (shares, class, "
                                   "nominal value); a change in the year to the share allotment (SH01) filed.")
    return ws.title


# ------------------------------------------------------------------------------------------------------------------
# Dividends (J3)
# ------------------------------------------------------------------------------------------------------------------
def dividend_tab(ctx: Context) -> Optional[str]:
    records = [t for t in _records(ctx, DIVIDEND_CODES)
               if abs(float(t.net_amount or 0)) >= 0.005 or abs(float(t.opening_amount or 0)) >= 0.005]
    # Also when the dividend comes only from an approved journal (a dividend declared to clear the directors' loan,
    # U-DIV-001): the tab's total reads the ETB's final, journals included
    by_journal = any(str(j.get("code")) in {str(c) for c in DIVIDEND_CODES} for j in (getattr(ctx, "journals", None) or []))
    if not records and not by_journal:
        return None
    ws = _new_sheet(ctx, "J3 - Dividends", ["J2 - Reserves", "J1 - Share Capital", "J"])
    ws["E1"] = "J3"
    ws["A4"] = "Dividends paid"
    ws["A4"].font = TITLE
    ws["D6"] = "Amount £"
    ws["D6"].font = BOLD
    # Per shareholder: what the ledger shows paid in the year (the TB balance of each account can also hold the
    # software's year-end clearing to reserves). The rest of the ETB figure is shown on its own line.
    shareholders = [t for t in records if not RESERVE_WORDS.search(t.raw_account_name or "")]
    first = 8
    total = first + len(shareholders) + 2
    for i, t in enumerate(shareholders):
        ws.cell(row=first + i, column=2, value=f"{t.raw_account_name[:60]} - paid in the year (ledger)")
    other = first + len(shareholders)
    ws.cell(row=other, column=2, value="Other entries on the dividend codes (year-end clearing to reserves, journals)"
            if shareholders else "Dividends declared by journal (B2) at the year end")
    ws.cell(row=total - 1, column=2, value=None)
    ws.cell(row=total, column=2, value="Dividends for the year (ETB 8010 / 8011)").font = BOLD
    _money(ws.cell(row=total, column=4, value=f"={_etb(DIVIDEND_CODES, 'N')}"), bold=True, total=True)
    _money(ws.cell(row=other, column=4, value=f"=D{total}-SUM(D{first}:D{other - 1})" if shareholders else f"=D{total}"))
    r = total + 2
    ws.cell(row=r, column=1, value="Reserves").font = BOLD
    r += 1
    ws.cell(row=r, column=2, value="Profit and loss reserve after dividends (J2)")
    _money(ws.cell(row=r, column=4, value="='J2 - Reserves'!E14" if "J2 - Reserves" in ctx.wb.sheetnames else None))
    r += 1
    ws.cell(row=r, column=2, value=f'=IF(D{r - 1}="","",IF(D{r - 1}<0,"Dividends are more than the profits '
                                   f'available: check they were legal (Companies Act s830) or treat as a loan to the '
                                   f'shareholder","Covered by the profits available"))').font = BOLD
    r += 2
    for i, t in enumerate(shareholders):
        # Leave out the software's clearing of last year's dividends to retained earnings (on 'Other entries')
        lines = [tx for tx in _lines_for(ctx, [t.raw_account_name]) if not RESERVE_WORDS.search(f"{tx[5]} {tx[4]}")]
        end = _write_lines(ws, r, t.raw_account_name, lines, "Paid (Dr)", "Credit")
        total_row = end - 2           # _write_lines leaves its Total two rows above the next free row
        _money(ws.cell(row=first + i, column=4, value=f"=D{total_row}-E{total_row}" if lines else 0))
        r = end
    ws["B6"] = "Dividend vouchers and board minutes: check one for each payment."
    return ws.title
