"""The General Ledger tab and Section K (one tab per P&L account), and the last steps."""

import re
from typing import Dict, Set


from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.workbook.context import GL_TAB


def step_9(ctx, s) -> None:
    """the General Ledger tab (the ledger lines gathered before the ETB)"""
    bold_font, client_name, db, tx_rows, wb, ye_str = s.bold_font, s.client_name, s.db, s.tx_rows, s.wb, s.ye_str
    # STEP 9: the General Ledger tab (the ledger lines gathered before the ETB)
    # -------------------------------------------------------------

    if GL_TAB in wb.sheetnames:
        ws_gld = wb[GL_TAB]
        # Clear the template's rows
        for r in range(1, max(ws_gld.max_row + 1, 20)):
            for c in range(1, 17):
                ws_gld.cell(row=r, column=c).value = None

        ws_gld["A1"] = client_name
        ws_gld["A2"] = ye_str
        ws_gld["A4"] = "Complete General Ledger Population"

        # Headers
        gl_headers = ["Account Code", "Account Name", "Date", "Source", "Description", "Reference", "Debit", "Credit", "Net Amount"]
        # The ledger's VAT amount and code, when it has them (every useful GL column carried)
        has_vat = any(len(tx) > 10 and (tx[9] is not None or tx[10]) for tx in tx_rows)
        if has_vat:
            gl_headers += ["VAT", "VAT code"]
        # Lines in another currency: the currency, the ledger's rate and the line in its own currency
        has_fx = any(len(tx) > 13 and (tx[12] is not None or tx[13] is not None) for tx in tx_rows)
        fx_col = len(gl_headers) + 1
        if has_fx:
            gl_headers += ["Currency", "Exchange rate", "Foreign amount"]
        # The account's type, from the firm chart (class and section: 'Profit and Loss: Administrative expenses'), or
        # the ledger's own when the chart does not know the code. Last, so no column
        # the other tabs read moves
        chart = ChartLookup(db) if db is not None else None
        type_col = len(gl_headers) + 1
        gl_headers += ["Account type"]
        # The payee / customer and the other side of the entry, when the ledger gives them (after the
        # account type, so no column the other tabs read moves)
        has_party = any(len(tx) > 15 and (tx[14] or tx[15]) for tx in tx_rows)
        party_col = len(gl_headers) + 1
        if has_party:
            gl_headers += ["Name", "Split"]
        # The line's name on its account's T ('Bank receipts', 'Sales invoices raised' ... as on the screen,
        # services/papers/t_lines.py), last, so no column the other tabs read moves; the T tabs SUMIFS by it
        from backend.app.services.papers.t_lines import account_kind, line_name
        tline_col = len(gl_headers) + 1
        gl_headers += [T_LINE_HEAD]
        # The kind of each account (its own name, else its code's chart name and accounts), as the screen's T
        # (services/papers/rollforward.py), so both name a line the same way
        names_on: dict = {}
        for tx in tx_rows:
            names_on.setdefault(str(tx[1]), set()).add(tx[3] or "")
        kinds: dict = {}

        def kind_of(tx) -> str:
            # The account's own name first when it says what it is (a 'Shopify Capital Loan' kept on the pension code
            # 5352 is a loan, not a pension); else the code's kind
            key = (str(tx[1]), tx[3] or "")
            if key not in kinds:
                code = int(key[0]) if key[0].isdigit() else None
                own = account_kind([code] if code is not None else [], [key[1]])
                if own == "other":
                    chart_name = chart.name(code) if chart is not None and code is not None else ""
                    own = account_kind([code] if code is not None else [], [chart_name] + sorted(names_on[key[0]]))
                kinds[key] = own
            return kinds[key]

        def t_line(tx) -> str:
            return line_name(kind_of(tx), tx[4], (tx[7] or 0) - (tx[8] or 0) > 0, tx[5])

        def account_type(tx) -> str:
            c = chart.accounts.get(int(tx[1])) if chart is not None and str(tx[1]).isdigit() else None
            if c is not None:
                return f"{c.financial_class}: {c.category}" if c.financial_class and c.category else (c.category or c.financial_class or "")
            return tx[2] or ""
        for col_idx, h_text in enumerate(gl_headers, 1):
            ws_gld.cell(row=6, column=col_idx, value=h_text).font = bold_font

        for r_idx, tx in enumerate(tx_rows, 7):
            # (dt_str, acc_code, acc_type, acc, src, desc, ref, deb, cred)
            ws_gld.cell(row=r_idx, column=1, value=int(tx[1]) if str(tx[1]).isdigit() else tx[1])  # firm code (the ETB sums by it)
            ws_gld.cell(row=r_idx, column=2, value=tx[3]) # Account Name
            ws_gld.cell(row=r_idx, column=3, value=tx[0]) # Date
            ws_gld.cell(row=r_idx, column=4, value=tx[4]) # Source
            ws_gld.cell(row=r_idx, column=5, value=tx[5]) # Description
            ws_gld.cell(row=r_idx, column=6, value=tx[6]) # Reference
            ws_gld.cell(row=r_idx, column=7, value=tx[7] if tx[7] != 0 else None) # Debit
            ws_gld.cell(row=r_idx, column=8, value=tx[8] if tx[8] != 0 else None) # Credit
            ws_gld.cell(row=r_idx, column=9, value=f"=+(G{r_idx}-H{r_idx})")
            if has_vat:
                ws_gld.cell(row=r_idx, column=10, value=tx[9] if len(tx) > 9 else None)        # VAT on the line
                ws_gld.cell(row=r_idx, column=11, value=tx[10] if len(tx) > 10 else None)      # VAT code
            if has_fx and len(tx) > 13:
                for k in range(3):
                    ws_gld.cell(row=r_idx, column=fx_col + k, value=tx[11 + k])
            ws_gld.cell(row=r_idx, column=type_col, value=account_type(tx) or None)
            if has_party:
                ws_gld.cell(row=r_idx, column=party_col, value=tx[14])
                ws_gld.cell(row=r_idx, column=party_col + 1, value=tx[15])
            ws_gld.cell(row=r_idx, column=tline_col, value=t_line(tx))

        # Totals row for complete GL
        if tx_rows:
            last_gl_r = 6 + len(tx_rows)
            tot_gl_r = last_gl_r + 1
            ws_gld.cell(row=tot_gl_r, column=2, value="TOTAL GENERAL LEDGER").font = bold_font
            ws_gld.cell(row=tot_gl_r, column=7, value=f"=SUM(G7:G{last_gl_r})").font = bold_font
            ws_gld.cell(row=tot_gl_r, column=8, value=f"=SUM(H7:H{last_gl_r})").font = bold_font
            ws_gld.cell(row=tot_gl_r, column=9, value=f"=SUM(I7:I{last_gl_r})").font = bold_font

    _journal_tab(wb, s, bold_font)

    # -------------------------------------------------------------


JOURNAL_TAB = "B2.1 - Journals as ledger lines"
T_LINE_HEAD = "T line"


def _journal_tab(wb, s, bold_font) -> None:
    """The adjusting journals (B2) as ledger lines (type Adjustment, journal ref, code, amount) on their own tab after
    B2, not at the foot of a ledger of thousands of rows. The General Ledger's columns, so the trail reads the same.
    No formula reads this tab: the ETB takes the journals from B2."""
    journals = [j for j in (getattr(s, "journals", None) or []) if j.get("code") not in (None, "")]
    if not journals:
        return
    at = wb.sheetnames.index("B2-Journals") + 1 if "B2-Journals" in wb.sheetnames else len(wb.sheetnames)
    ws = wb.create_sheet(JOURNAL_TAB, at)
    engagement = getattr(getattr(s, "ctx", None), "engagement", None)
    year_end = engagement.period_end_date if engagement is not None else None
    ws["A1"], ws["A2"], ws["E1"] = "=A!B2", "='Notes & Queries'!A2", "B2.1"
    ws["A4"] = "Adjusting journals as ledger lines"
    ws["A4"].font = bold_font
    ws["A5"] = "The journals on B2, one line per account, in the General Ledger's layout (the ETB adds them from B2)."
    head = 6
    for col, text in enumerate(["Account Code", "Account Name", "Date", "Type", "Narrative", "Journal", "Debit",
                                "Credit", "Net Amount"], 1):
        ws.cell(row=head, column=col, value=text).font = bold_font
    r = head
    for j in journals:
        r += 1
        code = str(j.get("code"))
        ws.cell(row=r, column=1, value=int(code) if code.isdigit() else code)
        ws.cell(row=r, column=2, value=s.account_name(int(code)) if code.isdigit() else None)
        if year_end is not None:
            ws.cell(row=r, column=3, value=year_end).number_format = "dd/mm/yyyy"
        ws.cell(row=r, column=4, value="Adjustment")
        ws.cell(row=r, column=5, value=" ".join(str(j.get("narrative") or "").split())[:200] or None)
        ws.cell(row=r, column=6, value=f"Journal {j.get('no')}" if j.get("no") is not None else None)
        ws.cell(row=r, column=7, value=float(j["debit"]) if j.get("debit") else None)
        ws.cell(row=r, column=8, value=float(j["credit"]) if j.get("credit") else None)
        ws.cell(row=r, column=9, value=f"=+(G{r}-H{r})")
    tot = r + 1
    ws.cell(row=tot, column=2, value="Total (debits = credits)").font = bold_font
    for col, letter in ((7, "G"), (8, "H"), (9, "I")):
        ws.cell(row=tot, column=col, value=f"=SUM({letter}{head + 1}:{letter}{r})").font = bold_font
    for col, width in zip("ABCDEFGHI", (12, 40, 11, 12, 60, 11, 13, 13, 13)):
        ws.column_dimensions[col].width = width

# A K tab's ledger columns: Date | Type | No. | Name | Description | Split | Debit | Credit |
# VAT code | VAT amount; Name and Split only when the ledger gives them, the VAT pair only when it has VAT
K_MONEY = '#,##0.00;(#,##0.00);""'
# (K heading, the GL tab's heading it comes from, money?)
K_FIELDS = (("Date", "Date", False), ("Type", "Source", False), ("No.", "Reference", False), ("Name", "Name", False),
            ("Description", "Description", False), ("Split", "Split", False), ("Debit", "Debit", True),
            ("Credit", "Credit", True), ("VAT code", "VAT code", False), ("VAT amount", "VAT", True))


def _k_layout(gl_cols) -> Dict[str, int]:
    """{K heading: column} for this workbook's GL: the optional fields left out when the GL has none."""
    optional = {"Name": "Name", "Split": "Split", "VAT code": "VAT", "VAT amount": "VAT"}
    keep = [f for f in K_FIELDS if f[0] not in optional or optional[f[0]] in gl_cols]
    return {f[0]: i for i, f in enumerate(keep, 1)}


def _ledger_lines(ws_k, gl_rows, cols, layout) -> int:
    """One K line from row 8 per GL row of the code, each cell a formula to the General Ledger tab (the GL column by
    its heading); text as text, so an empty GL cell shows blank, not 0. Returns the last row written (7 when none)."""
    gl = "'" + GL_TAB.replace("'", "''") + "'!"
    r = 7
    for g in gl_rows:
        r += 1
        for head, source, money in K_FIELDS:
            if head not in layout or source not in cols:
                continue
            if money:
                ws_k.cell(row=r, column=layout[head], value=f"={gl}{cols[source]}{g}").number_format = K_MONEY
            else:
                ws_k.cell(row=r, column=layout[head], value=f'=""&{gl}{cols[source]}{g}')
    return r


def step_10(ctx, s) -> None:
    """Section K - one tab per P&L account this client uses, plus the K index"""
    account_name, bold_font, ctx, etb_codes, journals = s.account_name, s.bold_font, s.ctx, s.etb_codes, s.journals
    remove_sheet, tx_rows, wb = s.remove_sheet, s.tx_rows, s.wb
    # STEP 10: Section K - one tab per P&L account this client uses, plus the K index
    # -------------------------------------------------------------
    if "K_TEMPLATE" in wb.sheetnames:
        ws_ktemp = wb["K_TEMPLATE"]
        ws_kidx = wb["K"] if "K" in wb.sheetnames else None
        pl_codes = [c for c in etb_codes if isinstance(c, int) and c < 4000]
        # The lines come from the General Ledger tab by formula: its columns by heading, and the
        # GL rows of each code (the GL tab writes tx_rows from row 7, in order)
        gl_cols = {str(c.value): c.column_letter for c in wb[GL_TAB][6] if c.value} if GL_TAB in wb.sheetnames else {}
        gl_rows_of: Dict[str, list] = {}
        for i, t in enumerate(tx_rows):
            gl_rows_of.setdefault(t[1], []).append(7 + i)
        layout = _k_layout(gl_cols)
        from openpyxl.utils import get_column_letter
        lab, dr, cr = layout["Description"], layout["Debit"], layout["Credit"]       # labels, and the figures column
        DR, CR = get_column_letter(dr), get_column_letter(cr)
        used_titles: Set[str] = set(wb.sheetnames)

        for k_num, code in enumerate(pl_codes, 1):
            name = account_name(code)
            base = re.sub(r"[:/\\?*\[\]]", "", f"K{k_num} - {name}")[:31].strip()
            title = base if base not in used_titles else f"K{k_num} - {code}"
            used_titles.add(title)

            ws_k = wb.copy_worksheet(ws_ktemp)
            ws_k.title = title
            from backend.app.services.workbook.balance_tabs import note_schedule
            note_schedule(ws_k, [code])
            ws_k["A1"] = "=A!B2"
            ws_k["A2"] = "='Notes & Queries'!A2"
            ws_k["K1"] = f"K{k_num}"
            ws_k["A4"] = name
            for c_idx in range(1, 11):
                ws_k.cell(row=6, column=c_idx).value = None
            for h_text, c_idx in layout.items():
                ws_k.cell(row=6, column=c_idx, value=h_text).font = bold_font
            ws_k.cell(row=7, column=1, value=f"{code:04d} - {name}").font = bold_font
            # Header: this year, last year, the variance and its % (from B1-ETB N and T)
            if getattr(ctx, "last_year_by_code", None):
                for i, (label, formula) in enumerate((
                        ("This year (B1-ETB final)", f"=SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!$N:$N)"),
                        ("Last year", f"=SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!$T:$T)"),
                        ("Variance", "=L3-L4"),
                        ("Variance %", '=IF(L4=0,"",L5/ABS(L4))')), 3):
                    ws_k.cell(row=i, column=11, value=label).font = bold_font
                    cell = ws_k.cell(row=i, column=12, value=formula)
                    cell.number_format = "0.0%" if label.endswith("%") else "#,##0.00;(#,##0.00);\"-\""

            k_rows = gl_rows_of.get(str(code), []) if gl_cols else []
            last_r = _ledger_lines(ws_k, k_rows, gl_cols, layout)
            tot_r = last_r + 1
            # Labels in the description column, figures in the credit column (the totals: debits and credits)
            ws_k.cell(row=tot_r, column=lab, value="Total").font = bold_font
            ws_k.cell(row=tot_r, column=dr, value=f"=SUM({DR}8:{DR}{last_r})" if k_rows else 0).font = bold_font
            ws_k.cell(row=tot_r, column=cr, value=f"=SUM({CR}8:{CR}{last_r})" if k_rows else 0).font = bold_font
            ws_k.cell(row=tot_r + 2, column=lab, value="Net per ledger")
            ws_k.cell(row=tot_r + 2, column=cr, value=f"={DR}{tot_r}-{CR}{tot_r}")
            ws_k.cell(row=tot_r + 3, column=lab, value="Balance per TTB")
            ws_k.cell(row=tot_r + 3, column=cr, value=f"=SUMIF(TTB!$A:$A,{code},TTB!$F:$F)-SUMIF(TTB!$A:$A,{code},TTB!$G:$G)")
            # The ledger against the TB for this code (red): a check like the ETB's column S
            ws_k.cell(row=tot_r + 4, column=lab, value="Difference: ledger v TB (must be nil)").font = bold_font
            ws_k.cell(row=tot_r + 4, column=cr, value=f"={CR}{tot_r + 2}-{CR}{tot_r + 3}").font = bold_font
            # The total per ledger against the ETB's movement for the code, where the ETB reads the GL
            gap = 0
            if k_rows:
                gap = 1
                ws_k.cell(row=tot_r + 5, column=lab, value="Check: ledger total v B1-ETB movement (must be nil)")
                ws_k.cell(row=tot_r + 5, column=cr, value=f"=ROUND({CR}{tot_r + 2}-(SUMIF('B1-ETB'!$A:$A,{code},"
                                                          f"'B1-ETB'!$H:$H)-SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!$I:$I)),2)")
            # On to the final figure: the TTB plus the approved journals is the ETB's final balance (linked). Each
            # journal on its own line by name, from B2 by its number, then their total
            etb_jnl = (f"SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!$J:$J)-SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!$K:$K)")
            on_code: Dict[int, str] = {}
            for j in journals or []:
                if str(j.get("code")) == str(code) and j.get("no") is not None:
                    on_code.setdefault(int(j["no"]), " ".join(str(j.get("narrative") or "").split()))
            r = tot_r + 5 + gap
            if on_code and len(on_code) <= 15:
                first_j = r
                for no, text in sorted(on_code.items()):
                    ws_k.cell(row=r, column=lab, value=f"  Journal {no}: {text}"[:120])
                    ws_k.cell(row=r, column=cr, value=f"=SUMIFS('B2-Journals'!$F:$F,'B2-Journals'!$A:$A,{no},"
                                                     f"'B2-Journals'!$E:$E,{code})-SUMIFS('B2-Journals'!$G:$G,"
                                                     f"'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{code})")
                    r += 1
                ws_k.cell(row=r, column=lab, value="Journals (B2), total")
                ws_k.cell(row=r, column=cr, value=f"=SUM({CR}{first_j}:{CR}{r - 1})")
                ws_k.cell(row=r + 1, column=lab, value="Check: journals by name v B1-ETB journals (must be nil)")
                ws_k.cell(row=r + 1, column=cr, value=f"=ROUND({CR}{r}-({etb_jnl}),2)")
                jnl_r, r = r, r + 2
            else:
                ws_k.cell(row=r, column=lab, value="Journals (B2)")
                ws_k.cell(row=r, column=cr, value=f"={etb_jnl}")
                jnl_r, r = r, r + 1
            ws_k.cell(row=r, column=lab, value="Final balance (B1-ETB)").font = bold_font
            ws_k.cell(row=r, column=cr, value=f"=SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!$N:$N)").font = bold_font
            ws_k.cell(row=r + 1, column=lab, value="Check: TTB + journals - final (must be 0)")
            ws_k.cell(row=r + 1, column=cr, value=f"=ROUND({CR}{tot_r + 3}+{CR}{jnl_r}-{CR}{r},2)")

            if ws_kidx is not None:
                idx_row = 8 + (k_num - 1) * 2
                ws_kidx.cell(row=idx_row, column=2, value=name)
                link = ws_kidx.cell(row=idx_row, column=5, value=f"K{k_num}")
                link.hyperlink = f"#'{title}'!A1"

        remove_sheet("K_TEMPLATE")

    # -------------------------------------------------------------


def step_11(ctx, s) -> None:
    """Nothing to do here: the sub-ledger and E3 / G10 summary helpers are in services/workbook/context.py."""
    # STEP 11: the sub-ledger and E3 / G10 summary helpers are in services/workbook/context.py
    # -------------------------------------------------------------

    # -------------------------------------------------------------


def step_12(ctx, s) -> None:
    """Control account tabs for the codes the TB holds; the tabs this client does not use are removed."""
    client_name, wb, ye_str = s.client_name, s.wb, s.ye_str
    # STEP 12: control accounts, and unused tabs removed
    # -------------------------------------------------------------

    if "G1 (LEAD)" in wb.sheetnames:
        ws_g1 = wb["G1 (LEAD)"]
        ws_g1["A1"] = client_name
        ws_g1["A2"] = ye_str
