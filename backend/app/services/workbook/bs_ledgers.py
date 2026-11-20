"""B3 - Balance sheet ledgers: a supporting ledger for every balance on the balance sheet. For every balance sheet code the client uses, each of its accounts: the balance brought forward, every
ledger line of the year with a running balance, and the closing balance; then the code's total against B1-ETB (TB,
journals, final balance) and, when last year's closing is known, the balance brought forward against it. An account
with no lines this year still shows b/f -> no movement -> closing, so every balance on the balance sheet has its
support. The summary at the top lists each code with its difference to the ETB (must be nil)."""

from datetime import datetime
from typing import Dict, List, Tuple

from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import select

from backend.app.models.database import MasterCOA
from backend.app.services.sop.common import account_name_keys
from backend.app.services.workbook.context import GL_TAB, BuildContext, format_std_code
from backend.app.services.workbook.gl_links import note_gl_line

SHEET = "B3 - BS ledgers"
# The line columns written from the GL line, by the GL tab's heading
B3_FROM_GL = {1: "Date", 2: "Source", 3: "Description", 4: "Reference", 5: "Debit", 6: "Credit"}
MONEY = '#,##0.00;(#,##0.00);"-"'
HEAD_FILL = PatternFill("solid", fgColor="E2F0EE")
CHECK_FILL = PatternFill("solid", fgColor="FFF7E0")


def _date_key(text: str):
    try:
        return datetime.strptime(text, "%d/%m/%Y")
    except (TypeError, ValueError):
        return datetime.max


def _etb(code: str, cols: Tuple[str, str]) -> str:
    """A code's debit less credit in two ETB columns ('H','I': the TB; 'J','K': journals)."""
    dr, cr = cols
    return (f"SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!${dr}:${dr})"
            f"-SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!${cr}:${cr})")


def add_bs_ledgers_tab(ctx: BuildContext) -> None:
    wb, db = ctx.wb, ctx.db
    if db is None or "B1-ETB" not in wb.sheetnames:
        return
    bs_codes = {c.std_code for c in db.execute(select(MasterCOA).where(MasterCOA.financial_class == "Balance Sheet")).scalars()}

    # The client's accounts on each balance sheet code (debit + as on the TB), in the TB's order
    accounts: Dict[int, List[Tuple[str, float]]] = {}
    for t in ctx.tb_records:
        if t.std_code in bs_codes:
            net = float(t.net_amount or 0)          # the closing balance (a movement TB: opening + movement)
            accounts.setdefault(t.std_code, []).append((t.raw_account_name or f"Account {t.std_code}", round(net, 2)))
    if not accounts:
        return

    # Each ledger line to the TB account it belongs to: by account name, else by code (one account on the code)
    name_keys = {k: (code, name) for code, accs in accounts.items() for name, _ in accs for k in account_name_keys(name)}
    lines: Dict[Tuple[int, str], list] = {}
    for tx in ctx.tx_rows:
        # (date 'dd/mm/yyyy', code, type, account, source, description, ref, debit, credit)
        hit = next((name_keys[k] for k in account_name_keys(tx[3] or "") if k in name_keys), None)
        if hit is None and str(tx[1]).isdigit() and int(tx[1]) in accounts and len(accounts[int(tx[1])]) == 1:
            hit = (int(tx[1]), accounts[int(tx[1])][0][0])
        if hit is not None and (tx[7] or tx[8]):
            lines.setdefault(hit, []).append(tx)

    if SHEET in wb.sheetnames:
        del wb[SHEET]
    after = GL_TAB if GL_TAB in wb.sheetnames else "B2-Journals"
    ws = wb.create_sheet(SHEET, wb.sheetnames.index(after) + 1 if after in wb.sheetnames else None)
    bold, italic = Font(bold=True), Font(italic=True, color="475569")
    ws["A1"], ws["A2"] = "=A!B2", "='Notes & Queries'!A2"
    ws["A4"] = "Balance sheet ledgers: every balance sheet account, brought forward + this year's lines = the TB"
    ws["A4"].font = Font(bold=True, size=12)
    for col, w in zip("ABCDEFGHI", (12, 18, 46, 16, 14, 14, 15, 15, 15)):
        ws.column_dimensions[col].width = w

    codes = sorted(accounts)
    # Summary first (filled once each block's rows are known)
    ws["A6"] = "Summary"
    ws["A6"].font = bold
    for j, h in enumerate(("Code", "Account", "", "", "Per ledger", "Per TB (B1-ETB)", "Difference", "Final (B1-ETB)", "Go to"), 1):
        c = ws.cell(row=7, column=j, value=h or None)
        c.font, c.fill = bold, HEAD_FILL
    summary_row = {code: 8 + i for i, code in enumerate(codes)}
    r = 8 + len(codes) + 1
    ws.cell(row=r, column=1, value="Check: total difference (must be 0)").font = bold
    total_check_row = r
    r += 3

    for code in codes:
        code_s = format_std_code(code)
        block_top = r
        ws.cell(row=r, column=1, value=code).font = bold
        ws.cell(row=r, column=2, value=ctx.account_name(code)).font = bold
        for col in range(1, 10):
            ws.cell(row=r, column=col).fill = HEAD_FILL
        r += 1
        for j, h in enumerate(("Date", "Type", "Description", "Reference", "Debit", "Credit", "Balance"), 1):
            ws.cell(row=r, column=j, value=h).font = bold
        r += 1
        closing_cells, bf_cells = [], []
        for name, net in accounts[code]:
            ws.cell(row=r, column=1, value=f"Account: {name}").font = italic
            r += 1
            txs = sorted(lines.get((code, name), []), key=lambda t: _date_key(t[0]))
            movement = round(sum(t[7] - t[8] for t in txs), 2)
            bf_row = r
            bf_cells.append(f"G{r}")
            ws.cell(row=r, column=3, value="Balance brought forward" + ("" if txs else " (no ledger lines this year)"))
            ws.cell(row=r, column=7, value=round(net - movement, 2)).number_format = MONEY
            r += 1
            first = r
            for t in txs:
                ws.cell(row=r, column=1, value=t[0])
                ws.cell(row=r, column=2, value=(t[4] or "")[:30])
                ws.cell(row=r, column=3, value=(t[5] or "")[:120])
                ws.cell(row=r, column=4, value=(t[6] or "")[:30])
                for col, v in ((5, t[7]), (6, t[8])):
                    if v:
                        ws.cell(row=r, column=col, value=round(v, 2)).number_format = MONEY
                note_gl_line(ctx, ws, r, t, B3_FROM_GL)
                ws.cell(row=r, column=7, value=f"=G{r - 1}+E{r}-F{r}").number_format = MONEY
                r += 1
            ws.cell(row=r, column=3, value="Closing balance per ledger").font = bold
            if txs:
                ws.cell(row=r, column=5, value=f"=SUM(E{first}:E{r - 1})").number_format = MONEY
                ws.cell(row=r, column=6, value=f"=SUM(F{first}:F{r - 1})").number_format = MONEY
            ws.cell(row=r, column=7, value=f"=G{bf_row}+E{r}-F{r}").number_format = MONEY
            ws.cell(row=r, column=7).font = bold
            closing_cells.append(f"G{r}")
            r += 2
        # The code against the ETB
        rows = [("Total per ledger", "=" + "+".join(closing_cells)),
                ("Per TB (B1-ETB)", "=" + _etb(code_s, ("F", "G")) + "+" + _etb(code_s, ("O", "P")) + "+"
                 + _etb(code_s, ("H", "I")) + f"+SUMIF('B1-ETB'!$A:$A,{code_s},'B1-ETB'!$S:$S)"),
                ("Difference (must be 0)", None),
                ("Journals (B2)", "=" + _etb(code_s, ("J", "K"))),
                ("Final balance (B1-ETB)", f"=SUMIF('B1-ETB'!$A:$A,{code_s},'B1-ETB'!$N:$N)")]
        start = r
        for i, (label, formula) in enumerate(rows):
            ws.cell(row=r, column=3, value=label).font = bold
            if label.startswith("Difference"):
                formula = f"=ROUND(G{start}-G{start + 1},2)"
                ws.cell(row=r, column=7).fill = CHECK_FILL
            ws.cell(row=r, column=7, value=formula).number_format = MONEY
            r += 1
        if code_s in ctx.opening_by_code:
            # The balance brought forward against the ETB's opening balance (last year's closing): a difference
            # means this year's ledger lines do not add up to the TB's movement on the code
            ws.cell(row=r, column=3, value="Opening balance per B1-ETB (last year's filed TB and the opening adjustment)")
            ws.cell(row=r, column=7, value="=" + _etb(code_s, ("F", "G")) + "+" + _etb(code_s, ("O", "P"))).number_format = MONEY
            ws.cell(row=r + 1, column=3, value="Brought forward less the ETB opening (should be 0)").font = bold
            ws.cell(row=r + 1, column=7, value=f"=ROUND({'+'.join(bf_cells)}-G{r},2)").number_format = MONEY
            ws.cell(row=r + 1, column=7).fill = CHECK_FILL
            r += 2
        # Summary line for this code, linked to the block
        s = summary_row[code]
        ws.cell(row=s, column=1, value=code)
        ws.cell(row=s, column=2, value=ctx.account_name(code))
        ws.cell(row=s, column=5, value=f"=G{start}").number_format = MONEY
        ws.cell(row=s, column=6, value=f"=G{start + 1}").number_format = MONEY
        ws.cell(row=s, column=7, value=f"=G{start + 2}").number_format = MONEY
        ws.cell(row=s, column=8, value=f"=G{start + 4}").number_format = MONEY
        link = ws.cell(row=s, column=9, value="Ledger")
        link.hyperlink = f"#'{SHEET}'!A{block_top}"
        link.font = Font(color="0F766E", underline="single")
        r += 2

    ws.cell(row=total_check_row, column=7, value=f"=ROUND(SUM(G8:G{7 + len(codes)}),2)").number_format = MONEY
    ws.cell(row=total_check_row, column=7).fill = CHECK_FILL
    ws.freeze_panes = "A8"
    ws["A5"] = (f"{len(codes)} balance sheet code(s); the ledger lines come from the client's general ledger. A balance "
                f"brought forward is the TB balance less this year's lines.")
    ws["A5"].alignment = Alignment(wrap_text=False)
