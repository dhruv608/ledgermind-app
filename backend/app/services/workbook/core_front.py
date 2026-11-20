"""The front tabs: cover and dividers, the TB codes, TTB, B2 journals, re-analysis, Notes & Queries."""

import re
from typing import List, Set

from openpyxl.styles import Font

from backend.app.services.workbook.context import format_std_code


def step_1(ctx, s) -> None:
    """Update Cover Sheet & Core Dividers"""
    client_name, ctx, draft_note, engagement = s.client_name, s.ctx, s.draft_note, s.engagement
    journals, wb, ye_str = s.journals, s.wb, s.ye_str
    # STEP 1: Update Cover Sheet & Core Dividers
    # -------------------------------------------------------------
    if "A" in wb.sheetnames:
        ws_a = wb["A"]
        ws_a["B2"] = client_name
        ws_a["B4"] = engagement.period_end_date  # named 'YearEnd'; year headings and period dates read it
        ws_a["B4"].number_format = "d mmmm yyyy"
        ws_a["D1"] = "A"            # the template carried another file's reference here
        if draft_note:  # generated before the review was finished: say so on the cover
            ws_a["B9"] = f"DRAFT - {draft_note}"
            ws_a["B9"].font = Font(name="Calibri", size=12, bold=True, color="C00000")

    # Year headings typed into the template (2025 / 2024): this client's years
    for lead in ("D1 (LEAD)", "E1 (LEAD)"):
        if lead in wb.sheetnames:
            wb[lead]["D6"] = f"{engagement.period_end_date.year}\n£"
            wb[lead]["E6"] = f"{engagement.period_end_date.year - 1}\n£"

    # Update Section dividers
    for div in ["C", "D", "E", "F", "G", "H", "J", "K"]:
        if div in wb.sheetnames:
            ws_div = wb[div]
            ws_div["B1"] = client_name
            ws_div["B2"] = ye_str

    # Only journals approved in the app are posted
    if journals is None:
        journals = []
    ctx.journals = journals

    # -------------------------------------------------------------
    s.journals = journals


def step_2(ctx, s) -> None:
    """Gather Active Codes from Current Client TB"""
    ctx, tb_records = s.ctx, s.tb_records
    # STEP 2: Gather Active Codes from Current Client TB
    # -------------------------------------------------------------
    tb_account_list = []
    tb_codes_present: Set[str] = set()
    for tb in tb_records:
        raw_code = getattr(tb, "std_code", None)
        if raw_code is None:
            raw_code = getattr(tb, "mapped_std_code", None)
        code_str = format_std_code(raw_code)
        deb_val = float(getattr(tb, "debit_amount", None) or getattr(tb, "debit", 0.0) or 0.0)
        cred_val = float(getattr(tb, "credit_amount", None) or getattr(tb, "credit", 0.0) or 0.0)
        acc_name = tb.raw_account_name or f"Account {code_str}"
        tb_account_list.append((code_str, acc_name, deb_val, cred_val))
        tb_codes_present.add(code_str)
    ctx.tb_account_list, ctx.tb_codes_present = tb_account_list, tb_codes_present
    # The TTB is this year's movement only (no 'Brought forward' rows): a code with last year's balance and
    # no account this year has its opening on the ETB (F / G from last year's TB), so its nil line is left off here
    ttb_rows = [row for tb, row in zip(tb_records, tb_account_list)
                if not (getattr(tb, "match_source", None) == "ROLL_FORWARD" and row[2] == 0 and row[3] == 0)]
    ctx.ttb_rows = ttb_rows

    # -------------------------------------------------------------
    s.tb_codes_present, s.ttb_rows = tb_codes_present, ttb_rows


def step_3(ctx, s) -> None:
    """Populate TTB Tab with Mandatory Column Totals (=SUM)"""
    accounting_total_border, bold_font, client_name = s.accounting_total_border, s.bold_font, s.client_name
    ttb_rows, wb, ye_str = s.ttb_rows, s.wb, s.ye_str
    # STEP 3: Populate TTB Tab with Mandatory Column Totals (=SUM)
    # -------------------------------------------------------------
    if "TTB" in wb.sheetnames:
        ws_ttb = wb["TTB"]
        ws_ttb["A1"] = client_name
        ws_ttb["A2"] = ye_str

        # Clear existing data rows starting from row 7
        max_ttb_r = max(ws_ttb.max_row, 30)
        for r in range(7, max_ttb_r + 2):
            for c in range(1, 12):
                ws_ttb.cell(row=r, column=c).value = None

        for i, (c_str, acc_name, deb_val, cred_val) in enumerate(ttb_rows):
            row_idx = 7 + i
            try:
                code_val = int(c_str)
            except (ValueError, TypeError):
                code_val = c_str
            ws_ttb.cell(row=row_idx, column=1, value=code_val)
            ws_ttb.cell(row=row_idx, column=2, value=acc_name)
            ws_ttb.cell(row=row_idx, column=6, value=deb_val if deb_val != 0 else None)
            ws_ttb.cell(row=row_idx, column=7, value=abs(cred_val) if cred_val != 0 else None)
            ws_ttb.cell(row=row_idx, column=8, value=f"=+(F{row_idx}-G{row_idx})")

        # A =SUM total for every amount column
        if ttb_rows:
            last_ttb_row = 6 + len(ttb_rows)
            total_ttb_row = last_ttb_row + 1

            ws_ttb.cell(row=total_ttb_row, column=2, value="TOTAL").font = bold_font

            # Column 6: Debit Total
            c6 = ws_ttb.cell(row=total_ttb_row, column=6, value=f"=SUM(F7:F{last_ttb_row})")
            c6.font = bold_font
            c6.number_format = "#,##0.00;(#,##0.00);\"-\""
            c6.border = accounting_total_border

            # Column 7: Credit Total
            c7 = ws_ttb.cell(row=total_ttb_row, column=7, value=f"=SUM(G7:G{last_ttb_row})")
            c7.font = bold_font
            c7.number_format = "#,##0.00;(#,##0.00);\"-\""
            c7.border = accounting_total_border

            # Column 8: Check / Net Difference Total (Must equal 0.00)
            c8 = ws_ttb.cell(row=total_ttb_row, column=8, value=f"=SUM(H7:H{last_ttb_row})")
            c8.font = bold_font
            c8.number_format = "#,##0.00;(#,##0.00);\"-\""
            c8.border = accounting_total_border

    # -------------------------------------------------------------


def step_4(ctx, s) -> None:
    """Populate B2-Journals Tab"""
    bold_font, journals, wb = s.bold_font, s.journals, s.wb
    # STEP 4: Populate B2-Journals Tab
    # -------------------------------------------------------------
    if "B2-Journals" in wb.sheetnames and journals:
        ws_jnl = wb["B2-Journals"]
        ws_jnl["A1"] = "=A!B2"
        ws_jnl["A2"] = "='Notes & Queries'!A2"
        # Columns: No | Date | Code | Account | Dr | Cr | Narrative | Source | Status. The ETB and the leads read
        # A (number) and E-G (code, Dr, Cr), so the date and account go in C and D, the source and status after the Check
        year_end = ctx.engagement.period_end_date
        from backend.app.services.workbook.context import short_chart_names
        firm_names = short_chart_names(ctx.db) if ctx.db is not None else {}
        for col, text in ((3, "Date"), (4, "Account"), (9, "Source"), (10, "Status")):
            ws_jnl.cell(row=4, column=col, value=text).font = bold_font
        ws_jnl.column_dimensions["D"].width = 30
        ws_jnl.column_dimensions["I"].width = 24

        # Each journal as a block: its number and narrative, its lines, the Check (debit less credit, 0 when it
        # balances) on its last line, then a blank row. The ETB sums the codes in E, so the narrative
        # rows (no code) change no figure
        blocks: List[List[dict]] = []
        for i, j in enumerate(journals):
            no = j.get("no", i + 1)
            if not blocks or blocks[-1][0].get("no", None) != no:
                blocks.append([])
            blocks[-1].append(dict(j, no=no))
        row_idx = 8
        for block in blocks:
            head = ws_jnl.cell(row=row_idx, column=1, value=block[0]["no"])
            head.font = bold_font
            ws_jnl.cell(row=row_idx, column=2, value=block[0].get("narrative", "")).font = bold_font
            if block[0].get("source"):
                ws_jnl.cell(row=row_idx, column=9, value=block[0]["source"])
            if block[0].get("status"):
                ws_jnl.cell(row=row_idx, column=10, value=block[0]["status"])
            first = row_idx + 1
            for j in block:
                row_idx += 1
                try:
                    c_code = int(format_std_code(j.get("code", "1999")))
                except:
                    c_code = format_std_code(j.get("code", "1999"))
                if j.get("narrative") and j.get("narrative") != block[0].get("narrative"):
                    ws_jnl.cell(row=row_idx, column=2, value=j.get("narrative"))
                # The journal's number on each of its lines: the leads and K tabs pick each journal out by it
                ws_jnl.cell(row=row_idx, column=1, value=block[0]["no"]).font = Font(color="808080")
                ws_jnl.cell(row=row_idx, column=5, value=c_code)
                if year_end is not None:
                    ws_jnl.cell(row=row_idx, column=3, value=year_end).number_format = "dd/mm/yyyy"
                if isinstance(c_code, int):
                    ws_jnl.cell(row=row_idx, column=4, value=firm_names.get(c_code) or ctx.account_name(c_code))
                deb = j.get("debit")
                cred = j.get("credit")
                ws_jnl.cell(row=row_idx, column=6, value=deb if deb else None)
                ws_jnl.cell(row=row_idx, column=7, value=cred if cred else None)
            ws_jnl.cell(row=row_idx, column=8, value=f"=ROUND(SUM(F{first}:F{row_idx})-SUM(G{first}:G{row_idx}),2)")
            row_idx += 2

        last_jnl_row = row_idx - 2
        tot_jnl_row = last_jnl_row + 1
        ws_jnl.cell(row=tot_jnl_row, column=2, value="TOTAL").font = bold_font
        ws_jnl.cell(row=tot_jnl_row, column=6, value=f"=SUM(F8:F{last_jnl_row})").font = bold_font
        ws_jnl.cell(row=tot_jnl_row, column=7, value=f"=SUM(G8:G{last_jnl_row})").font = bold_font

    # -------------------------------------------------------------


def step_5(ctx, s) -> None:
    """Re-analysis tab: the approved journals that move a line from one account to another."""
    bold_font, client_name, wb, ye_str = s.bold_font, s.client_name, s.wb, s.ye_str
    # STEP 5: Re-analysis tab, cleared, then each re-analysis journal listed (misposted lines move by a named
    # re-analysis journal and are listed here)
    # -------------------------------------------------------------
    if "Re-analysis" in wb.sheetnames:
        ws_re = wb["Re-analysis"]
        # Clear every value and formula the template holds
        for r in range(1, max(ws_re.max_row + 1, 80)):
            for c in range(1, max(ws_re.max_column + 1, 15)):
                ws_re.cell(row=r, column=c).value = None

        # Set standard clean header for post-audit adjustments
        ws_re["A1"] = client_name
        ws_re["A2"] = ye_str
        ws_re["A4"] = "Re-Analysis / Post-Audit Adjustments Schedule"
        ws_re["A5"] = "(Reserved for post-audit reclassification and approved adjustments)"
        headers = ["Date", "Nominal Code", "Source", "Description", "Debit", "Credit", "Re-analyse To", "Audit Reference"]
        for col_idx, h_text in enumerate(headers, 1):
            cell = ws_re.cell(row=7, column=col_idx, value=h_text)
            cell.font = bold_font
        _reanalysis_rows(ctx, ws_re, s.journals or [])

    # -------------------------------------------------------------


def step_6(ctx, s) -> None:
    """Notes & Queries: the template's notes cleared, this client's notes written."""
    bold_font, client_name, db, engagement, ttb_rows = s.bold_font, s.client_name, s.db, s.engagement, s.ttb_rows
    wb, ye_str = s.wb, s.ye_str
    # STEP 6: Notes & Queries
    # -------------------------------------------------------------
    if "Notes & Queries" in wb.sheetnames:
        ws_nq = wb["Notes & Queries"]
        ws_nq["A1"] = client_name
        ws_nq["A2"] = ye_str

        # Clear the template's hand-typed notes
        for r in range(5, max(ws_nq.max_row + 1, 95)):
            for c in range(1, max(ws_nq.max_column + 1, 35)):
                cell = ws_nq.cell(row=r, column=c)
                cell.value = None
                cell.hyperlink = None

        # Populate clean, dynamic engagement notes
        ws_nq.cell(row=4, column=1, value="Sr").font = bold_font
        ws_nq.cell(row=4, column=2, value="ENGAGEMENT AUDIT NOTES & QUERIES").font = bold_font

        framework = {"FRS105": "FRS 105", "FRS102_1A": "FRS 102 (Section 1A)", "FULL_FRS102": "FRS 102"}.get(
            getattr(getattr(engagement, "profile", None), "accounting_framework", None) or "", "the framework on the client setup")
        open_points = 0
        if db is not None:
            from backend.app.models.database import AuditFinding
            open_points = db.query(AuditFinding).filter(AuditFinding.engagement_id == engagement.id,
                                                        AuditFinding.status == "OPEN").count()
        clean_notes = [
            (1, "Preparation", f"Prepared from the {engagement.source_system or 'accounting software'} general ledger and trial balance, under {framework}."),
            (2, "Method", "Working papers built from the client's ledger and trial balance; each schedule links back to the ETB."),
            (3, "Trial Balance", f"Populated {len(ttb_rows)} trial balance accounts into the TTB schedule with dynamic column totals."),
            (4, "Review points", f"{open_points} open point(s) from the review to clear (see the review list in the app)."),
        ]
        for idx, (sr, title, note_text) in enumerate(clean_notes):
            row_n = 6 + (idx * 2)
            ws_nq.cell(row=row_n, column=1, value=sr)
            ws_nq.cell(row=row_n, column=2, value=title).font = bold_font
            ws_nq.cell(row=row_n, column=4, value=note_text)

    # -------------------------------------------------------------


# A journal that moves a line to the right account: both sides in the P&L, or worded as a move (the review's 'moved
# from', 're-analysed', 'reclassified' journals: PAYE paid booked as salary, revenue costs on asset codes)
MOVE_WORDS = re.compile(r"\bmoved?\b|re-?analys|reclass|wrong(ly)? (code|account)|posted to", re.I)


def _reanalysis_rows(ctx, ws, journals) -> None:
    """One row per line moved: date, the account it moved from, the journal's source, the narrative, the amount, the
    account it moved to and the journal's number (B2)."""
    from backend.app.services.mapping.chart_lookup import ChartLookup
    chart = ChartLookup(ctx.db) if ctx.db is not None else None
    by_no: dict = {}
    for j in journals:
        by_no.setdefault(j.get("no"), []).append(j)
    year_end = ctx.engagement.period_end_date
    r = 8
    for no, lines in by_no.items():
        codes = [int(x["code"]) for x in lines if str(x.get("code", "")).isdigit()]
        narrative = lines[0].get("narrative") or ""
        all_pl = chart is not None and codes and all(chart.is_pl(c) for c in codes) and len(codes) >= 2
        if not (all_pl or MOVE_WORDS.search(narrative)):
            continue
        debits = [x for x in lines if x.get("debit")]
        credits = [x for x in lines if x.get("credit")]
        to_code = debits[0]["code"] if len(debits) == 1 else "several"
        for x in credits:
            if year_end is not None:
                ws.cell(row=r, column=1, value=year_end).number_format = "dd/mm/yyyy"
            ws.cell(row=r, column=2, value=int(x["code"]) if str(x["code"]).isdigit() else x["code"])
            ws.cell(row=r, column=3, value=x.get("source") or "")
            ws.cell(row=r, column=4, value=narrative[:200])
            ws.cell(row=r, column=6, value=x["credit"]).number_format = "#,##0.00;(#,##0.00)"
            ws.cell(row=r, column=7, value=int(to_code) if str(to_code).isdigit() else to_code)
            ws.cell(row=r, column=8, value=f"B2 journal {no}")
            r += 1
    if r == 8:
        ws.cell(row=8, column=1, value="No re-analysis journals approved this year.")
