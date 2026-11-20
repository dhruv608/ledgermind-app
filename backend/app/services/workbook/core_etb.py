"""B1-ETB: one row per account the client uses (TB, approved journals, opening balances)."""

from typing import Any, Dict, List

from openpyxl.utils import get_column_letter

from backend.app.services.workbook.context import GL_TAB, code_sort_key, format_std_code
from backend.app.services.workbook.etb_rows import code_rows, is_pl

SPEC_COL = 24        # B1-ETB X, Y: after last year (T, U), the schedule (V) and P&L / BS (W)
OPENING_CHECK = ("Opening adjustment by code (books v last year's filed TB): unexplained, remap or explain "
                 "(must be nil)")      # amber on A0 (checks_tab.AMBER_WORDS: 'unexplained')


def _last_year_by_code(engagement, db) -> Dict[str, float]:
    """Last year's final balance by firm code (debit +), the P&L included: last year's job in the app (after its
    approved journals), else last year's closing TB in the firm's codes, else last year's TB read by account name.
    Empty when there is no last year."""
    try:
        from backend.app.services.review.opening_balances import last_year_closing
        _src, balances = last_year_closing(engagement, db)
    except Exception:
        balances = None
    if not balances:
        try:
            from backend.app.services.review.last_year import _from_files
            _src, lines = _from_files(engagement, db)
            balances = {}
            for l in lines or []:
                if l.code is not None:
                    balances[l.code] = balances.get(l.code, 0.0) + float(l.amount or 0)
        except Exception:
            balances = {}
    return {format_std_code(k): round(v, 2) for k, v in (balances or {}).items() if k is not None and abs(v) >= 0.005}


def step_8(ctx, s) -> None:
    """B1-ETB - one row per account this client uses (TB, approved journals, opening balances)"""
    account_name, accounting_total_border, bold_font = s.account_name, s.accounting_total_border, s.bold_font
    ctx, db, engagement, journals, report_notes = s.ctx, s.db, s.engagement, s.journals, s.report_notes
    tb_codes_present, tb_records, tx_rows, wb = s.tb_codes_present, s.tb_records, s.tx_rows, s.wb
    # STEP 8: B1-ETB - one row per account this client uses (TB, approved journals, opening balances)
    # -------------------------------------------------------------
    etb_codes: List[Any] = []
    opening_by_code: Dict[str, float] = {}
    if "B1-ETB" in wb.sheetnames:
        ws_etb = wb["B1-ETB"]
        ws_etb["A1"] = "=A!B2"
        ws_etb["A2"] = "='Notes & Queries'!A2"
        # The client's own software, not the template's 'Xero'
        software = {"XERO": "Xero", "QUICKBOOKS": "QuickBooks", "SAGE": "Sage", "FREEAGENT": "FreeAgent"}.get(
            (engagement.source_system or "").upper(), "Client")
        ws_etb["H6"] = f"{software} TTB"

        # Opening balances (only for clients whose TB holds this year's movements) by firm code
        for tb in tb_records:
            if getattr(tb, "opening_amount", None) is not None:
                key = format_std_code(tb.std_code)
                opening_by_code[key] = opening_by_code.get(key, 0.0) + float(tb.opening_amount)
        books = False
        if db is not None:
            from backend.app.services.bank_only.books import is_books_client
            books = is_books_client(engagement)
        # The extraction rule: b/fwd is last year's filed TB, the movement is the ledger's (a live
        # SUMIFS on the General Ledger tab) and the client's TB only checks them. It needs a ledger: a books
        # client (its TB is built from last year's closing TB and the bank) and a client with no ledger keep the TB's
        # own figures
        by_gl = bool(tx_rows) and db is not None and not books
        filed: Dict[str, float] = {}
        adjust: Dict[str, float] = {}
        not_in_gl: Dict[str, float] = {}
        movement_tb = False
        if by_gl:
            from backend.app.services.review.extraction import ledger_tie
            gl_move: Dict[str, float] = {}
            for tx in tx_rows:
                if tx[1]:
                    key = format_std_code(tx[1])
                    gl_move[key] = gl_move.get(key, 0.0) + tx[7] - tx[8]
            tie = ledger_tie(engagement, tb_records, db, gl_move=gl_move)
            filed, opening_by_code, adjust, not_in_gl = tie.filed, tie.opening, tie.adjust, tie.not_in_gl
            votes, movement_tb = tie.votes, tie.kind == "movement"
            ctx.tb_kind = tie.kind
            told = votes["movement"] + votes["closing"] + votes["neither"]
            if "Notes & Queries" in wb.sheetnames:
                ws_nq = wb["Notes & Queries"]
                ws_nq.cell(row=14, column=1, value=5)
                ws_nq.cell(row=14, column=2, value="Opening and movement").font = bold_font
                ws_nq.cell(row=14, column=4, value=(
                    f"The client's TB is a {'movement' if movement_tb else 'closing'} TB"
                    + (f" ({max(votes['movement'], votes['closing'])} of {told} balance sheet accounts agree)" if told else "")
                    + ". B1-ETB: opening from last year's filed TB (balance sheet codes; last year's profit in reserves), "
                      "movement from the general ledger, the TB as the check; the opening adjustment is the books' "
                      "opening less last year's filed TB."))
            big = sorted(((k, v) for k, v in not_in_gl.items() if abs(v) >= 1), key=lambda kv: -abs(kv[1]))
            if big:
                report_notes.append(
                    f"GL and TB differ on {len(big)} account(s) (B1-ETB column S, must be nil): "
                    + "; ".join(f"{k} {v:,.2f}" for k, v in big[:8])
                    + ". Missing GL transactions, a wrong TB date or a mapping error: the WP stays draft until explained")
        elif not opening_by_code and db is not None:
            # No opening lines in the ledger: last year's closing TB in the firm's codes gives them, unless this TB
            # already holds them (a closing TB repeats last year's unchanged balances, share capital say, to the penny)
            from backend.app.services.review.last_year import prior_balances_by_code
            prior = prior_balances_by_code(engagement, db)
            this_year: Dict[int, float] = {}
            for tb in tb_records:
                if tb.std_code is not None:
                    this_year[tb.std_code] = this_year.get(tb.std_code, 0.0) + float(tb.net_amount or 0.0)
            repeated = sum(1 for c, v in prior.items() if abs(v) >= 1 and abs(this_year.get(c, 0.0) - v) < 0.01)
            if prior and repeated < 2:
                opening_by_code = {format_std_code(c): v for c, v in prior.items() if abs(v) >= 0.005}
            elif prior:
                report_notes.append("Last year's TB not used for opening balances: this TB already includes them")

        codes = set(tb_codes_present) | {format_std_code(j.get("code")) for j in journals} | set(opening_by_code)
        if by_gl:
            codes |= set(filed) | {format_std_code(tx[1]) for tx in tx_rows if tx[1]}
        # Last year's figure for every code, the P&L too (the comparatives): every code in last year's TB keeps a line,
        # so a cost with nothing this year still shows, with its K tab
        last_year = _last_year_by_code(engagement, db) if db is not None else {}
        codes |= {k for k, v in last_year.items() if abs(v) >= 1}
        ctx.last_year_by_code = last_year
        etb_codes = [int(c) if str(c).isdigit() else c for c in sorted(codes, key=code_sort_key)]

        # Clear the template's rows below the headers
        for r in range(8, max(ws_etb.max_row, 80) + 1):
            for c in range(1, 22):
                ws_etb.cell(row=r, column=c).value = None
        ly_col, var_col = 20, 21                    # T, U: after the books / TB check columns
        if last_year:
            for col, head, sub in ((ly_col, "Last year (B1-ETB final)", "£"), (var_col, "Variance", "£")):
                ws_etb.cell(row=6, column=col, value=head).font = bold_font
                ws_etb.cell(row=7, column=col, value=sub).font = bold_font
                ws_etb.column_dimensions[get_column_letter(col)].width = 14

        def money(cell):
            cell.number_format = "#,##0.00;(#,##0.00);\"-\""
            return cell

        if by_gl:
            gld = f"'{GL_TAB}'"
            ws_etb["F6"] = "Opening (last year's filed TB)"
            ws_etb["H6"] = "Movement per GL"
            ws_etb["O6"] = "Opening adjustment (books v filed)"
            ws_etb["Q6"] = f"{software} TB (check)"
            ws_etb["R6"] = "Closing per books"
            ws_etb["S6"] = "TB not in GL (must be nil)"
            ws_etb.cell(row=6, column=SPEC_COL, value="Final worked out (opening + ledger + journals)")
            ws_etb.cell(row=6, column=SPEC_COL + 1, value="Books final less the worked-out final")
            for col in (SPEC_COL, SPEC_COL + 1):
                ws_etb.cell(row=6, column=col).font = bold_font
                ws_etb.cell(row=7, column=col, value="£").font = bold_font
                ws_etb.column_dimensions[get_column_letter(col)].width = 16
            for col, head in (("O", "Debit £"), ("P", "Credit £"), ("Q", "£"), ("R", "£"), ("S", "£")):
                ws_etb[f"{col}7"] = head
            for col in ("O", "P", "Q", "R", "S"):
                ws_etb[f"{col}6"].font = ws_etb[f"{col}7"].font = bold_font
                ws_etb.column_dimensions[col].width = 14

        from backend.app.services.mapping.chart_lookup import ChartLookup as _CL
        etb_chart = _CL(db) if db is not None else None
        ws_etb.cell(row=6, column=23, value="P&L / BS").font = bold_font
        client_names: Dict[str, List[str]] = {}
        for t in tb_records:
            if t.std_code is not None and (t.raw_account_name or "").strip():
                names = client_names.setdefault(format_std_code(t.std_code), [])
                if t.raw_account_name.strip() not in names:
                    names.append(t.raw_account_name.strip())
        # One blank row between the P&L and the balance sheet codes
        etb_rows = code_rows(etb_codes)
        for r, code in zip(etb_rows, etb_codes):
            key = format_std_code(code)
            ws_etb.cell(row=r, column=1, value=code)
            # The client's own account name where one account maps to the code, else the chart's
            own = client_names.get(key) or []
            ws_etb.cell(row=r, column=2, value=own[0] if len(own) == 1 else account_name(code))
            # P&L or balance sheet, from the firm chart
            klass = etb_chart.accounts.get(code).financial_class if (etb_chart is not None and isinstance(code, int)
                                                                       and code in etb_chart.accounts) else ""
            ws_etb.cell(row=r, column=23, value={"Profit and Loss": "P&L", "Balance Sheet": "BS"}.get(klass, klass or None))
            bal = filed.get(key, 0.0) if by_gl else opening_by_code.get(key, 0.0)
            ws_etb.cell(row=r, column=6, value=round(bal, 2) if bal > 0.005 else None)
            ws_etb.cell(row=r, column=7, value=round(-bal, 2) if bal < -0.005 else None)
            if by_gl:
                ws_etb.cell(row=r, column=8, value=f"=SUMIFS({gld}!$G:$G,{gld}!$A:$A,$A{r})")
                ws_etb.cell(row=r, column=9, value=f"=SUMIFS({gld}!$H:$H,{gld}!$A:$A,$A{r})")
            else:
                ws_etb.cell(row=r, column=8, value=f"=+SUMIFS(TTB!$F:$F,TTB!$A:$A,A{r})")
                ws_etb.cell(row=r, column=9, value=f"=+SUMIFS(TTB!$G:$G,TTB!$A:$A,A{r})")
            ws_etb.cell(row=r, column=10, value=f"=SUMIF('B2-Journals'!E:E,A{r},'B2-Journals'!F:F)")
            ws_etb.cell(row=r, column=11, value=f"=SUMIF('B2-Journals'!E:E,A{r},'B2-Journals'!G:G)")
            if by_gl:
                adj = adjust.get(key, 0.0)
                money(ws_etb.cell(row=r, column=15, value=round(adj, 2) if adj > 0.005 else None))
                money(ws_etb.cell(row=r, column=16, value=round(-adj, 2) if adj < -0.005 else None))
                money(ws_etb.cell(row=r, column=17, value=f"=SUMIFS(TTB!$H:$H,TTB!$A:$A,$A{r})"))
                money(ws_etb.cell(row=r, column=18, value=f"=F{r}-G{r}+O{r}-P{r}+H{r}-I{r}"))
                gap = not_in_gl.get(key, 0.0)
                money(ws_etb.cell(row=r, column=19, value=round(gap, 2) if gap else None))
                # The final balance is the books' closing, the TB's figure the GL does not explain (column S, to
                # clear) and the journals: the TB's balance plus journals, as the app's own figures
                net = f"F{r}+H{r}+J{r}+O{r}-G{r}-I{r}-K{r}-P{r}+S{r}"
            else:
                net = f"F{r}+H{r}+J{r}-G{r}-I{r}-K{r}"
            ws_etb.cell(row=r, column=12, value=f"=IF(({net})<0,0,({net}))")
            ws_etb.cell(row=r, column=13, value=f"=IF(({net})>0,0,-({net}))")
            ws_etb.cell(row=r, column=14, value=f"=+L{r}-M{r}")
            if by_gl:
                # The spec final (opening + movement + journals) beside the books' and what
                # separates them: the opening adjustment and the TB not in the GL
                money(ws_etb.cell(row=r, column=SPEC_COL, value=f"=F{r}-G{r}+H{r}-I{r}+J{r}-K{r}"))
                money(ws_etb.cell(row=r, column=SPEC_COL + 1, value=f"=ROUND(N{r}-{get_column_letter(SPEC_COL)}{r},2)"))
            if last_year:
                ly = last_year.get(key, 0.0)
                money(ws_etb.cell(row=r, column=ly_col, value=round(ly, 2) if abs(ly) >= 0.005 else None))
                money(ws_etb.cell(row=r, column=var_col,
                                  value=f"=N{r}-{get_column_letter(ly_col)}{r}"))

        last_data_row = etb_rows[-1] if etb_rows else 7
        tot_row = last_data_row + 2
        ws_etb.cell(row=tot_row, column=2, value="TOTAL").font = bold_font
        total_cols = list(range(6, 20 if by_gl else 15)) + ([20, 21] if last_year else [])
        for col in total_cols:
            letter = get_column_letter(col)
            cell = money(ws_etb.cell(row=tot_row, column=col, value=f"=SUM({letter}8:{letter}{last_data_row})"))
            cell.font = bold_font
            cell.border = accounting_total_border
        chk_row = tot_row + 1
        ws_etb.cell(row=chk_row, column=2, value="Check (must be 0)")
        ws_etb.cell(row=chk_row, column=6, value=f"=F{tot_row}-G{tot_row}")
        ws_etb.cell(row=chk_row, column=8, value=f"=H{tot_row}-I{tot_row}")
        ws_etb.cell(row=chk_row, column=10, value=f"=J{tot_row}-K{tot_row}")
        ws_etb.cell(row=chk_row, column=12, value=f"=L{tot_row}-M{tot_row}")
        if by_gl:
            ws_etb.cell(row=chk_row, column=15, value=f"=O{tot_row}-P{tot_row}")
            for col in (SPEC_COL, SPEC_COL + 1):
                letter = get_column_letter(col)
                cell = money(ws_etb.cell(row=tot_row, column=col, value=f"=SUM({letter}8:{letter}{last_data_row})"))
                cell.font, cell.border = bold_font, accounting_total_border
            # An opening on another code than last year's filed TB (fixed by remapping the account, never
            # by a journal): every code's adjustment, so two that offset still show. Amber, to explain: money the GL does
            # not explain is the TTB's red check
            ws_etb.cell(row=chk_row + 3, column=2, value=OPENING_CHECK)
            money(ws_etb.cell(row=chk_row + 3, column=SPEC_COL + 1,
                              value=f"=ROUND(SUMPRODUCT(ABS(O8:O{last_data_row}-P8:P{last_data_row})),2)"))
        # The profit on the ETB itself, not only on the taxation tab, below the totals and checks (a row inside the codes would be counted in the totals): the P&L codes' final
        # balances turned round, a credit balance being a profit
        pl_rows = [r for r, code in zip(etb_rows, etb_codes) if is_pl(code)]
        if pl_rows:
            profit_row = chk_row + 5
            ws_etb.cell(row=profit_row, column=2,
                        value="Profit / (loss) for the year, after tax (the P&L codes above)").font = bold_font
            last_pl = pl_rows[-1]
            for col, formula in ((12, f"=MAX(0,SUM(N8:N{last_pl}))"), (13, f"=MAX(0,-SUM(N8:N{last_pl}))"),
                                 (14, f"=-SUM(N8:N{last_pl})")):
                cell = money(ws_etb.cell(row=profit_row, column=col, value=formula))
                cell.font = bold_font
            # Before tax too, to tie to the taxation tab's 'Profit before tax per accounts': every P&L code but the
            # tax charge (3800-3899)
            pbt = (f"-(SUMIFS(N8:N{last_pl},A8:A{last_pl},\"<3800\")"
                   f"+SUMIFS(N8:N{last_pl},A8:A{last_pl},\">=3900\"))")
            ws_etb.cell(row=profit_row + 1, column=2, value="Profit / (loss) before tax (as the taxation tab, H1)")
            for col, formula in ((12, f"=MAX(0,-({pbt}))"), (13, f"=MAX(0,{pbt})"), (14, f"={pbt}")):
                money(ws_etb.cell(row=profit_row + 1, column=col, value=formula))
        # Suspense at the year end: nil, or each item explained (amber)
        if 9999 in etb_codes:
            ws_etb.cell(row=chk_row + 2, column=2, value="Suspense 9999 at the year end: unexplained difference (must be nil)")
            money(ws_etb.cell(row=chk_row + 2, column=14, value="=ROUND(SUMIF($A:$A,9999,$N:$N),2)"))

    ctx.etb_codes, ctx.opening_by_code = etb_codes, opening_by_code

    # -------------------------------------------------------------
    s.etb_codes = etb_codes
