"""Balance sheet tabs, first part: D stock (with the control-tab helpers the later parts use: the account lead, the
ageing under it, the flagged items), E debtors and E3 prepayments with its review."""

from datetime import date
from typing import Any, Dict, List, Optional
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from backend.app.services.mapping.chart_lookup import VAT_CONTROL
from backend.app.services.sop.common import gl_lines
from backend.app.services.sop.prepayments import PREPAY_QUESTION, prepayment_review
from backend.app.services.tax.open_items import (contacts_with_vat, documents_by_day, ledger_documents)
from backend.app.services.workbook.balance_tabs import lead_lines
from backend.app.services.workbook.balance_sheet import CURRENCY_LEDGER, _deals_in_precious_metals, _plain_stock_details, _stock_tabs


def step_stock(ctx, shared) -> None:
    """2. Stock / Inventories (Section D)"""
    accounting_total_border, bold_font, ctx = shared.accounting_total_border, shared.bold_font, shared.ctx
    db, engagement, rebuild_control_subledger = shared.db, shared.engagement, shared.rebuild_control_subledger
    reconcile_ageing, remove_sheet = shared.reconcile_ageing, shared.remove_sheet
    tb_codes_present, tb_records, wb = shared.tb_codes_present, shared.tb_records, shared.wb
    # 2. Stock / Inventories (Section D)
    has_stock = any(c in tb_codes_present for c in {"1000", "1010", "1020", "1910", "4300", "4301", "4302"})
    if not has_stock:
        for s in ["D", "D1 (LEAD)", "D2 - Stock Material", "D2.1 - NL Transactions", "D2.2 - Stock details"]:
            remove_sheet(s)
    else:
        rebuild_control_subledger("D2.1 - NL Transactions", {"1000", "1910", "4300", "4301"}, "stock", "Stock / Inventories")
        if "D2.2 - Stock details" in wb.sheetnames and not _deals_in_precious_metals(engagement, tb_records):
            _plain_stock_details(wb["D2.2 - Stock details"], engagement, bold_font)
        _stock_tabs(ctx)

    def write_account_lead(ws, code: int, dr: str, cr: str, rows: Dict[str, int], cf_on: str,
                           nl: Optional[str] = None, types: Optional[List[str]] = None,
                           t_only: bool = False) -> Dict[str, Any]:
        """With the ETB reading the ledger: the lead lines (balance_tabs.lead_lines) in
        one amount column from row 8, the NL tab's lines as the movement; returns {"bf", "cf": cell, "end": row}.
        Otherwise a control account as debits and credits: b/fwd (opening TB), TTB movement and approved journals each
        on both sides, then the c/fwd as the balancing figure on `cf_on`'s side, and the totals (both sides, where
        the template reads one only)."""
        if ctx.tb_kind:
            for r in range(5, rows["total"] + 5):
                for c in "ABCDE":
                    if type(ws[f"{c}{r}"]).__name__ != "MergedCell":
                        # the link goes too: a template link left on an emptied cell is written back as its target
                        # text ("'G3.1 - DLA-NL Transactions'!G1" on G3)
                        ws[f"{c}{r}"].hyperlink = None
                        ws[f"{c}{r}"] = None
            if t_only:
                # The account as one T with its lines named, as the screen shows it:
                # links read the T's own b/f and c/d, signed as the account is read (owed +: a liability)
                from backend.app.services.workbook.balance_tabs.common import on_tab
                from backend.app.services.workbook.balance_tabs.t_shape import t_account
                t = t_account(ctx, ws, [code], top=6, owed=cf_on == dr)
                return {"bf": t["bf_s"], "cf": t["cf_s"], "end": t["end"], "books": t["books_s"],
                        "bf_link": on_tab(ws.title, t["bf_s"]), "cf_link": on_tab(ws.title, t["cf_s"])}
            ws["D6"] = "£"
            lines = lead_lines(ctx, ws, [code], owed=cf_on == dr, nl=nl if nl in wb.sheetnames else None,
                               types=types if nl in wb.sheetnames else None)
            from backend.app.services.workbook.balance_tabs.common import period_start_formula
            ws[f"A{lines['bf']}"] = period_start_formula(ctx)
            ws[f"A{lines['cf']}"] = "=YearEnd"
            for r in (lines["bf"], lines["cf"]):
                ws[f"A{r}"].number_format = "dd/mm/yyyy"
            return {"bf": f"D{lines['bf']}", "cf": f"D{lines['cf']}", "end": lines["end"]}

        def etb(c: str) -> str:
            return f"SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!${c}:${c})"

        def ttb(c: str) -> str:
            return f"SUMIF(TTB!$A:$A,{code},TTB!${c}:${c})"

        first, last = rows["bf"] - 1, rows["cf"] - 1
        for r in range(first, rows["total"] + 1):
            for c in (dr, cr):
                if type(ws[f"{c}{r}"]).__name__ != "MergedCell":
                    ws[f"{c}{r}"] = None
        for key, label, (d, c) in (("bf", "Balance b/fwd", ("F", "G")),
                                   ("ttb", "Movement per GL" if ctx.tb_kind else "Movement per TTB", ("F", "G")),
                                   ("jnl", "Adjusting journals (B2)", ("J", "K"))):
            r = rows[key]
            ws[f"B{r}"] = label
            if key == "ttb" and ctx.tb_kind:
                # The ledger's movement (B1-ETB H:I) and what of the TB it does not explain (column S, to clear)
                ws[f"{dr}{r}"] = f"={etb('H')}+MAX({etb('S')},0)"
                ws[f"{cr}{r}"] = f"={etb('I')}+MAX(-{etb('S')},0)"
            elif key == "ttb":
                ws[f"{dr}{r}"], ws[f"{cr}{r}"] = f"={ttb(d)}", f"={ttb(c)}"
            elif key == "bf":
                # Last year's filed TB and the opening adjustment (books v filed)
                ws[f"{dr}{r}"], ws[f"{cr}{r}"] = f"={etb('F')}+{etb('O')}", f"={etb('G')}+{etb('P')}"
            else:
                ws[f"{dr}{r}"], ws[f"{cr}{r}"] = f"={etb(d)}", f"={etb(c)}"
        other = cr if cf_on == dr else dr
        ws[f"B{rows['cf']}"] = "Balance c/fwd"
        ws[f"{cf_on}{rows['cf']}"] = f"=SUM({other}{first}:{other}{last})-SUM({cf_on}{first}:{cf_on}{last})"
        for c in (dr, cr):
            ws[f"{c}{rows['total']}"] = f"=SUM({c}{first}:{c}{rows['total'] - 1})"
            ws[f"{c}{rows['total']}"].font = bold_font
            ws[f"{c}{rows['total']}"].border = accounting_total_border
        return {}

    def ageing_under(ws, lead: Dict[str, Any], report, kind: str, code: int, ref: str, owed: bool) -> None:
        """The aged report check under the lead lines."""
        if not lead:
            reconcile_ageing(ws.title, report, kind, code)
            return
        top = lead["end"] + 2
        ws[f"A{top}"] = f"Balance as per {'A/P' if owed else 'A/R'} Ageing Detail"
        ws[f"D{top}"] = ref
        ws[f"B{top + 1}"] = "Difference"
        ws[f"C{top + 1}"] = f"=ROUND(C{top}-({lead['cf']}),2)" if owed else f"=ROUND(({lead['cf']})-C{top},2)"
        for r in (top, top + 1):
            ws[f"C{r}"].number_format = '#,##0.00;(#,##0.00);"-"'
        reconcile_ageing(ws.title, report, kind, code, top=top)
        if report is not None and report.total is not None:
            # The difference explained item by item: the ledgers stop at the year end, so the
            # accountant types what the listing and the books differ by; what is left must be nil
            from openpyxl.styles import PatternFill
            from backend.app.services.workbook.balance_tabs import INPUT_COLOUR
            r0 = top + 4
            ws[f"A{r0}"] = "Reconciling items (type them in)"
            ws[f"A{r0}"].font = bold_font
            items = (["Bills received but not yet posted", "Payments made after the year end", "Credit notes not yet posted"]
                     if owed else ["Invoices raised but not yet posted", "Receipts after the year end", "Credit notes not yet posted"])
            # Ledgers kept in another currency: the aged report and the books differ by the exchange on them until the
            # open foreign invoices are retranslated at the year-end rate (FRS 102 s30)
            fx_ledgers = [t for t in tb_records if t.std_code == code and CURRENCY_LEDGER.search(t.raw_account_name or "")]
            if fx_ledgers:
                items.append("Foreign exchange on the currency ledgers (see below)")
            for i, text in enumerate(items + ["Other (explain)"], start=1):
                ws[f"B{r0 + i}"] = text
                ws[f"C{r0 + i}"].fill = PatternFill("solid", fgColor=INPUT_COLOUR)
                ws[f"C{r0 + i}"].number_format = '#,##0.00;(#,##0.00);"-"'
            last = r0 + len(items) + 1
            ws[f"B{last + 1}"] = "Unexplained difference (must be nil)"
            ws[f"B{last + 1}"].font = bold_font
            ws[f"C{last + 1}"] = f"=ROUND(C{top + 1}-SUM(C{r0 + 1}:C{last}),2)"
            ws[f"C{last + 1}"].font = bold_font
            ws[f"C{last + 1}"].number_format = '#,##0.00;(#,##0.00);"-"'
            if fx_ledgers:
                # The movement per ledger, so the currency ones can be seen
                r = last + 3
                own = [t for t in tb_records if t.std_code == code]
                # The TB gives the movement only where it holds this year's movements (net = movement + opening)
                moves = any(t.opening_amount is not None for t in own)
                ws[f"A{r}"] = "Movement by ledger (this year)" if moves else "Balance by ledger (year end)"
                ws[f"A{r}"].font = bold_font
                for i, t in enumerate(own, start=1):
                    ws[f"B{r + i}"] = (t.raw_account_name or "")[:60]
                    ws[f"C{r + i}"] = round(float(t.net_amount or 0) - float(t.opening_amount or 0) if moves
                                            else float(t.net_amount or 0), 2)
                    ws[f"C{r + i}"].number_format = '#,##0.00;(#,##0.00);"-"'
                note = r + len(own) + 2
                ws[f"A{note}"] = (f"{len(fx_ledgers)} ledger(s) in another currency ("
                                  + ", ".join((t.raw_account_name or "")[:30] for t in fx_ledgers[:4]) + "). Foreign "
                                  f"{'creditors' if owed else 'debtors'} are retranslated at the year-end rate (FRS 102 "
                                  f"s30): the open foreign invoices at the closing rate less the books, posted to 3562 "
                                  f"Foreign exchange gains/losses. Until then the aged report and the books differ by it.")
        if report is not None:
            flagged_items(ws, report, owed)

    documents: Dict[str, Any] = {}

    def _open_item_documents(side: str):
        """The ledger's invoices / bills by day and the contacts whose documents carry VAT;
        read once, and only for a VAT-registered client."""
        if "docs" not in documents:
            profile = getattr(engagement, "profile", None)
            documents["docs"] = (ledger_documents(gl_lines(str(engagement.id), tb_records, db), VAT_CONTROL)
                                 if db is not None and getattr(profile, "is_vat_registered", False) else {})
        docs = documents["docs"]
        return documents_by_day(docs, side), contacts_with_vat(docs, side)

    def flagged_items(ws, report, owed: bool) -> None:
        """The listing's items to look at (the 'Flag' column): more than 90 days old at the year end, and
        balances on the wrong side (a customer the company owes, a supplier who owes the company); days old from
        each item's own date."""
        from backend.app.services.ingestion.ageing_reports import outstanding_items
        ye = engagement.period_end_date
        side = "AP" if owed else "AR"
        by_day, with_vat = _open_item_documents(side)
        rows = []
        items = outstanding_items(report)
        # Next year's ledger, when uploaded: each item paid after the year end, with its date
        from backend.app.services.ingestion.next_year import next_year_lines
        from backend.app.services.review.paid_after import note_for, paid_after, paid_total
        later = [l for l in (next_year_lines(str(engagement.id), db) if db is not None else [])
                 if ye is None or (l.when - ye).days <= 183]          # the six months after
        matched = paid_after(items, later, owed) if later else {}
        paid_on = {id(items[k]): v for k, v in matched.items()}
        from backend.app.services.workbook.open_item_listing import item_flags
        for i in items:
            days = (ye - i.when).days if (i.when and ye) else None
            flags = item_flags(i, ye, owed, by_day, with_vat)        # the same flags as the E2.2 / G2.2 listing
            if flags:
                rows.append((i, days, "; ".join(flags)))
        if later and items:
            open_total, paid = paid_total(items, matched)
            top = ws.max_row + 2
            ws.cell(row=top, column=1, value=(f"Open at the year end £{open_total:,.2f}; paid in the six months after "
                                              f"(next year's ledger) £{paid:,.2f}"))
        if not rows:
            return
        top = ws.max_row + 2
        ws.cell(row=top, column=1, value=("Supplier" if owed else "Customer") + " items to look at").font = bold_font
        for c, h in enumerate(("Contact", "Number", "Date", "Amount", "Days old", "Flag", "Paid after year end"), 1):
            ws.cell(row=top + 1, column=c, value=h).font = bold_font
        for n, (i, days, flag) in enumerate(sorted(rows, key=lambda x: -abs(x[0].amount))[:40], start=top + 2):
            ws.cell(row=n, column=1, value=i.contact[:60])
            ws.cell(row=n, column=2, value=i.number or None)
            if i.when:
                ws.cell(row=n, column=3, value=i.when).number_format = "dd/mm/yyyy"
            ws.cell(row=n, column=4, value=round(i.amount, 2)).number_format = '#,##0.00;(#,##0.00);"-"'
            ws.cell(row=n, column=5, value=days)
            ws.cell(row=n, column=6, value=flag)
            if later:
                ws.cell(row=n, column=7, value=note_for(paid_on.get(id(i)), True))
        if len(rows) > 40:
            ws.cell(row=top + 42, column=1, value=f"... and {len(rows) - 40} more")
    shared.ageing_under, shared.write_account_lead = ageing_under, write_account_lead


def step_debtors(ctx, shared) -> None:
    """3. Trade Debtors (Section E)"""
    ageing, ageing_under, client_name = shared.ageing, shared.ageing_under, shared.client_name
    rebuild_control_subledger, remove_sheet = shared.rebuild_control_subledger, shared.remove_sheet
    tb_codes_present, wb, write_account_lead = shared.tb_codes_present, shared.wb, shared.write_account_lead
    write_ageing_report, ye_str = shared.write_ageing_report, shared.ye_str
    # 3. Trade Debtors (Section E)
    has_debtors = any(c in tb_codes_present for c in {"4400", "1100"})
    if not has_debtors:
        for s in ["E", "E1 (LEAD)", "E2-Trade Debtors", "E2.1-Debtors NL ", "E2.2-A R Ageing Detail"]:
            remove_sheet(s)
    else:
        # The debtors NL is rebuilt from this client's GL only
        rebuild_control_subledger("E2.1-Debtors NL ", {"4400", "4500"}, "debtor", "Trade Debtors")
        if "E2-Trade Debtors" in wb.sheetnames:
            ws_e2 = wb["E2-Trade Debtors"]
            ws_e2["A1"] = client_name
            ws_e2["A2"] = ye_str
            # Debit balance: c/fwd on the credit side; E1 reads the net b/fwd and the c/fwd
            lead = write_account_lead(ws_e2, 4400, "C", "D", {"bf": 8, "ttb": 10, "jnl": 11, "cf": 12, "total": 14}, "D",
                                      nl="E2.1-Debtors NL ", t_only=True)
            if "E1 (LEAD)" in wb.sheetnames:
                wb["E1 (LEAD)"]["E8"] = "='E2-Trade Debtors'!C8-'E2-Trade Debtors'!D8"
                if lead:
                    wb["E1 (LEAD)"]["D8"] = f"={lead['cf_link']}"
                    wb["E1 (LEAD)"]["E8"] = f"={lead['bf_link']}"
            ageing_under(ws_e2, lead, ageing.get("AR"), "receivables", 4400, "E2.2", owed=False)
        write_ageing_report("E2.2-A R Ageing Detail", ageing.get("AR"), "Aged Receivables", "E2.2")


def step_prepayments(ctx, shared) -> None:
    """4. Prepayments (Section E3)"""
    bold_font, db, engagement = shared.bold_font, shared.db, shared.engagement
    rebuild_control_subledger, remove_sheet = shared.rebuild_control_subledger, shared.remove_sheet
    report_notes, tb_codes_present, tb_records = shared.report_notes, shared.tb_codes_present, shared.tb_records
    wb, write_balance_summary = shared.wb, shared.write_balance_summary
    # 4. Prepayments (Section E3)
    has_prepayments = any(c in tb_codes_present for c in {"4900", "1150"})
    if not has_prepayments:
        for s in ["E3 - Prepayments", "E3.1 NL Analysis"]:
            remove_sheet(s)
        if "E1 (LEAD)" in wb.sheetnames:
            wb["E1 (LEAD)"]["D10"] = 0.0
    else:
        rebuild_control_subledger("E3.1 NL Analysis", {"4900"}, "prepayment", "Prepayments")
        write_balance_summary("E3 - Prepayments", ["4900", "1150"], credit=False, detail_rows=[19, 20] + list(range(24, 31)))

    # Prepayments SOP (E3.2): expenses whose description shows a period beyond the year end.
    # Shown even without a prepayments account: a missing prepayment is exactly the case to catch.
    if db is not None:
        prepay_flags = prepayment_review(str(engagement.id), engagement.period_end_date, tb_records, db)
        after = next((n for n in ("E3.1 NL Analysis", "E3 - Prepayments", "E2.2-A R Ageing Detail") if n in wb.sheetnames), None)
        ws = wb.create_sheet("E3.2 - Prepayment review",
                             wb.sheetnames.index(after) + 1 if after else
                             (wb.sheetnames.index("F") if "F" in wb.sheetnames else len(wb.sheetnames)))
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        ws["A4"] = "Prepayment review"
        ws["A4"].font = Font(name="Calibri", size=12, bold=True)
        ws["A5"] = ("Expenses whose description shows a period running past the year end. The prepaid part is a "
                    "straight-line estimate for review only: nothing is posted.")
        # One row per invoice: supplier, the period, months used this year and left, this year's
        # charge and the prepaid part (Charge this year + Prepaid = Amount)
        heads = ["Date", "Account", "Code", "Supplier", "Description", "Amount", "Period from", "Period to",
                 "Months in period", "Months used this year", "Months after year end", "Charge this year",
                 "Estimated prepayment", "How the period was found", "Question for the client"]
        col = {h: i for i, h in enumerate(heads, 1)}
        money_cols = {col["Amount"], col["Charge this year"], col["Estimated prepayment"]}
        for c, text in enumerate(heads, 1):
            ws.cell(row=7, column=c, value=text).font = bold_font
        for r, f in enumerate(prepay_flags, 8):
            supplier = f.description.split(" - ", 1)[0].strip() if " - " in f.description else ""
            # A single payment taken as a yearly plan states no period: a question, with no prepayment estimated
            # (a prepayment needs the period on the invoice or memo)
            if f.guessed and "yearly plan" in f.basis:
                values = [f.when, f.account, f.code, supplier, f.description[:250], f.amount, f.start, None, None, None,
                          None, None, None, f"Period not stated ({f.basis.split(':')[0]}): not estimated",
                          "What period does this payment cover? Please send the invoice."]
            else:
                used = max(int(f.total_months or 0) - int(f.months_after or 0), 0)
                values = [f.when, f.account, f.code, supplier, f.description[:250], f.amount, f.start, f.end,
                          f.total_months, used, f.months_after, round(f.amount - f.prepaid, 2), f.prepaid, f.basis,
                          PREPAY_QUESTION]
            for c, v in enumerate(values, 1):
                cell = ws.cell(row=r, column=c, value=v)
                if isinstance(v, date):
                    cell.number_format = "dd/mm/yyyy"
                elif c in money_cols:
                    cell.number_format = "#,##0.00"
        total_row = 8 + len(prepay_flags) + 1
        p_col = get_column_letter(col["Estimated prepayment"])
        if prepay_flags:
            ws.cell(row=total_row, column=col["Estimated prepayment"] - 1, value="Total").font = bold_font
            cell = ws.cell(row=total_row, column=col["Estimated prepayment"], value=f"=SUM({p_col}8:{p_col}{total_row - 2})")
            cell.font = bold_font
            cell.number_format = "#,##0.00"
        else:
            ws["A8"] = "No expense description shows a period beyond the year end."
        books = sum(float(t.net_amount or 0) for t in tb_records if t.std_code == 4900)
        ws.cell(row=total_row + 1, column=col["Estimated prepayment"] - 1, value="Prepayments in the books (4900)")
        ws.cell(row=total_row + 1, column=col["Estimated prepayment"], value=round(books, 2)).number_format = "#,##0.00"
        ws.column_dimensions["B"].width = 30
        ws.column_dimensions["D"].width = 50
        if prepay_flags:
            report_notes.append(f"{len(prepay_flags)} expense(s) may need a prepayment: prepayment review (E3.2)")
