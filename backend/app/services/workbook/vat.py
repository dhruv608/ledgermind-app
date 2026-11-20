"""VAT tabs: G9 (the VAT account agreed to what the returns still owe), G9.1 (the returns and which HMRC payment paid
each), G9.3 (the VAT account's ledger lines) and G9.5 (each return against the ledger's own VAT)."""

from datetime import datetime
from functools import partial

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from backend.app.services.mapping.chart_lookup import VAT_CONTROL
from backend.app.services.reconciliation.control_accounts import vat_position
from backend.app.services.tax.vat_review import vat_review
from backend.app.services.workbook.context import BuildContext
from backend.app.services.workbook.context import rebuild_control_subledger as _rebuild_control_subledger


BASIS_LABELS = {"STANDARD": "Accrual Basis", "CASH": "Cash Basis", "FLAT_RATE": "Flat Rate Scheme",
                "FLAT_RATE_CASH": "Flat Rate Scheme - Cash Basis", "MARGIN": "Margin Scheme", "ANNUAL": "Annual Accounting"}


def add_vat_tabs(ctx: BuildContext) -> None:
    wb, engagement, db, tb_records = ctx.wb, ctx.engagement, ctx.db, ctx.tb_records
    tx_rows, tb_codes_present, report_notes = ctx.tx_rows, ctx.tb_codes_present, ctx.report_notes
    bold_font, accounting_total_border = ctx.bold_font, ctx.accounting_total_border
    remove_sheet = ctx.remove_sheet
    rebuild_control_subledger = partial(_rebuild_control_subledger, ctx)

    def build_vat_summary() -> None:
        """G9.1: the VAT returns typed on the VAT returns screen, the HMRC payments from the VAT account in the
        ledger (each matched to the oldest unpaid return), and G9: the VAT account agreed to what is still owed."""
        summary, lead = "G9-.1-VAT Summary", "G9 - VAT"
        if summary not in wb.sheetnames or lead not in wb.sheetnames:
            return
        vat_code = VAT_CONTROL
        # The returns, the HMRC payments on the VAT account and which return each paid: shared with the
        # control accounts screen (reconciliations.py)
        def ledger_line(tx):
            try:
                when = datetime.strptime(tx[0], "%d/%m/%Y").date()
            except ValueError:
                when = None
            return when, tx[1], tx[5], tx[7] - tx[8], tx[4]

        pos = vat_position(db, engagement, (ledger_line(tx) for tx in tx_rows))

        # The client's VAT basis (from the VAT summary or the setup), shown where the template said 'Accrual Basis'
        from backend.app.models.database import ClientProfile
        profile = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement.id).first() if db is not None else None
        scheme = (getattr(profile, "vat_scheme", None) or "STANDARD").upper()
        basis_label = BASIS_LABELS.get(scheme, "Accrual Basis")
        for tab in (summary, "G9.2 - Late claims"):
            if tab in wb.sheetnames:
                for row in wb[tab].iter_rows(min_row=1, max_row=6, max_col=8):
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.strip().lower() == "accrual basis":
                            cell.value = basis_label
        returns, owed, payments, allocations = pos.returns, pos.owed, pos.payments, pos.allocations
        bfwd, in_year = returns[:pos.brought_forward], returns[pos.brought_forward:]
        if not in_year:
            report_notes.append("No VAT returns entered for the year")

        # --- G9.1 VAT Summary ---
        ws = wb[summary]
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        n_cols = max(ws.max_column, 14 + len(returns))
        for row in ws.iter_rows(min_row=6, max_row=max(ws.max_row, 60), max_col=n_cols):
            for cell in row:
                cell.value = None
                cell.hyperlink = None
        for col, text in ((1, "Return"), (2, "Outputs VAT (box 3)"), (3, "Inputs VAT (box 4)"), (4, "Payable / (Refund)"),
                          (5, "Recd / Paid"), (6, "O/S"), (8, "Turnover (box 6)")):
            ws.cell(row=6, column=col, value=text).font = bold_font
        prefix = "QE-" if len(in_year) <= 4 else "ME-"
        first_row, return_rows = 8, []
        for i, r in enumerate(returns):
            row = first_row + i
            return_rows.append(row)
            if i < len(bfwd):
                ws.cell(row=row, column=1, value=f"B/fwd - {r.period_end:%b-%y}")
                ws.cell(row=row, column=4, value=round(owed[i], 2))
            else:
                ws.cell(row=row, column=1, value=f"{prefix} {r.period_end:%b %y}")
                ws.cell(row=row, column=2, value=float(r.box3_total_vat_due or 0))
                ws.cell(row=row, column=3, value=float(r.box4_vat_reclaimed or 0))
                ws.cell(row=row, column=4, value=f"=B{row}-C{row}")
                ws.cell(row=row, column=8, value=float(r.box6_total_sales_ex_vat or 0))
        if not returns:
            ws.cell(row=first_row, column=1, value="No VAT returns entered on the VAT returns screen.")
        last_row = first_row + max(len(returns), 1) - 1
        total_row = last_row + 2
        ws.cell(row=total_row, column=1, value="Total").font = bold_font
        for col in (2, 3, 4, 5, 6, 8):
            letter = get_column_letter(col)
            cell = ws.cell(row=total_row, column=col, value=f"=SUM({letter}{first_row}:{letter}{last_row})")
            cell.font = bold_font
            cell.border = accounting_total_border

        pay_title = total_row + 3
        ws.cell(row=pay_title, column=1, value=(
            "Details of VAT payments (per the client's VAT summary: what was paid on each return, and when)"
            if pos.source == "summary" else
            "Details of VAT payments (HMRC lines on the VAT account in the ledger)")).font = bold_font
        head = pay_title + 1
        alloc_col = {i: 7 + i for i in range(len(returns))}
        unmatched_col = 7 + len(returns)
        for col, text in ((1, "Date"), (2, "Description"), (4, "Amount"), (5, "Interest"), (6, "Penalty"), (unmatched_col, "Not matched")):
            ws.cell(row=head, column=col, value=text).font = bold_font
        for i, r in enumerate(returns):
            cell = ws.cell(row=head, column=alloc_col[i], value=r.period_end)
            cell.number_format = "mmm-yy"
            cell.font = bold_font
        last_alloc = get_column_letter(max(unmatched_col - 1, 6))
        for k, ((when, desc, amount), alloc) in enumerate(zip(payments, allocations)):
            row = head + 1 + k
            ws.cell(row=row, column=1, value=when).number_format = "dd/mm/yyyy"
            ws.cell(row=row, column=2, value=desc)
            ws.cell(row=row, column=4, value=amount)
            for i, value in alloc.items():
                ws.cell(row=row, column=alloc_col[i], value=value)
            ws.cell(row=row, column=unmatched_col, value=f"=ROUND(D{row}-SUM(E{row}:{last_alloc}{row}),2)")
        if not payments:
            ws.cell(row=head + 1, column=2, value="No HMRC payments found on the VAT account in the ledger.")
        pay_last = head + max(len(payments), 1)
        pay_total = pay_last + 1
        for col in range(4, unmatched_col + 1):
            letter = get_column_letter(col)
            cell = ws.cell(row=pay_total, column=col, value=f"=SUM({letter}{head + 1}:{letter}{pay_last})")
            cell.font = bold_font
            cell.border = accounting_total_border
        for i, row in enumerate(return_rows):
            ws.cell(row=row, column=5, value=f"=-{get_column_letter(alloc_col[i])}{pay_total}")
            ws.cell(row=row, column=6, value=f"=D{row}+E{row}")

        # The ledger's HMRC payments beside the summary's, and the interest / penalties on the VAT account: what HMRC
        # charged (or paid as repayment interest) is not a payment of VAT and is kept apart
        note_row = pay_total + 2
        if pos.source == "summary":
            ledger_paid = round(sum(p[2] for p in pos.ledger_payments), 2)
            summary_paid = round(sum(p[2] for p in pos.payments), 2)
            ws.cell(row=note_row, column=1, value="HMRC payments on the VAT account in the ledger")
            ws.cell(row=note_row, column=4, value=ledger_paid).number_format = "#,##0.00;(#,##0.00)"
            ws.cell(row=note_row, column=5, value=(
                "agrees with the VAT summary" if abs(ledger_paid - summary_paid) < 1 else
                f"differs from the VAT summary by {ledger_paid - summary_paid:,.2f}: a payment missing or posted elsewhere"))
            note_row += 2
        charges_title = note_row
        ws.cell(row=charges_title, column=1, value="Interest and penalties on the VAT account (not payments of VAT)").font = bold_font
        for col, text in ((1, "Date"), (2, "Description"), (4, "Amount")):
            ws.cell(row=charges_title + 1, column=col, value=text).font = bold_font
        for k, (when, desc, amount) in enumerate(pos.charges):
            row = charges_title + 2 + k
            ws.cell(row=row, column=1, value=when).number_format = "dd/mm/yyyy"
            ws.cell(row=row, column=2, value=desc)
            ws.cell(row=row, column=4, value=amount).number_format = "#,##0.00;(#,##0.00)"
        if not pos.charges:
            ws.cell(row=charges_title + 2, column=2, value="None.")
        charges_total = charges_title + 2 + max(len(pos.charges), 1)
        cell = ws.cell(row=charges_total, column=4,
                       value=f"=SUM(D{charges_title + 2}:D{charges_total - 1})" if pos.charges else 0)
        cell.font = bold_font
        cell.border = accounting_total_border
        cell.number_format = "#,##0.00;(#,##0.00)"
        for row in ws.iter_rows(min_row=first_row, max_row=pay_total, min_col=3, max_col=unmatched_col):
            for cell in row:
                if cell.row != head:
                    cell.number_format = "#,##0.00;(#,##0.00)"
        for row in ws.iter_rows(min_row=first_row, max_row=total_row, min_col=2, max_col=2):
            row[0].number_format = "#,##0.00;(#,##0.00)"

        # --- G9 lead: the VAT account, then what it should be per the returns ---
        ws = wb[lead]
        for row in ws.iter_rows(min_row=7, max_row=max(ws.max_row, 70), max_col=8):
            for cell in row:
                cell.value = None
                cell.hyperlink = None
        ws["D6"] = "£"
        ws["E6"] = "£"

        def etb(col: str) -> str:
            return f"SUMIF('B1-ETB'!$A:$A,{vat_code},'B1-ETB'!${col}:${col})"

        def ttb(col: str) -> str:
            return f"SUMIF(TTB!$A:$A,{vat_code},TTB!${col}:${col})"

        if ctx.tb_kind:
            # The VAT account as one T with its lines named, as the screen shows it: owed to HMRC +; G1 and B1-ETB
            # read its c/d and b/f
            from backend.app.services.workbook.balance_tabs.common import on_tab
            from backend.app.services.workbook.balance_tabs.t_shape import t_account
            t = t_account(ctx, ws, [vat_code], top=7, owed=True)
            lines = {"end": t["end"]}
            cf_cell, schedule_cell = t["cf_s"], on_tab(lead, t["cf_s"])
            if "G1 (LEAD)" in wb.sheetnames:
                wb["G1 (LEAD)"]["D23"] = f"={on_tab(lead, t['cf_s'])}"
                wb["G1 (LEAD)"]["E23"] = f"={on_tab(lead, t['bf_s'])}"
        else:
            # G1 lead reads E8 (b/fwd) and D17 (c/fwd), both as amounts owed to HMRC
            ws["B8"] = "Balance b/fwd"
            ws["E8"] = f"={etb('G')}-{etb('F')}"
            ws["A11"] = "TTB"
            ws["B11"] = "Movement per TTB"
            ws["E11"] = f"={ttb('G')}-{ttb('F')}"
            ws["A13"] = "B2"
            ws["B13"] = "Adjusting journals"
            ws["E13"] = f"={etb('K')}-{etb('J')}"
            ws["B17"] = "Balance c/fwd - owed to HMRC (negative = refund due)"
            ws["D17"] = "=SUM(E8:E15)"
            ws["D17"].font = bold_font
            ws["D17"].border = accounting_total_border
            cf_cell = "D17"
            schedule_cell = f"'{lead}'!D17"

        ctx.schedule_cf[vat_code] = (schedule_cell, -1)      # owed to HMRC +, for B1-ETB's schedule column

        # The VAT proof (one layout per scheme and basis): the same lines and figures as the
        # control accounts screen (tax/vat_proof.py), totalled and agreed to the VAT account above
        from backend.app.services.tax.vat_proof import vat_proof
        proof = vat_proof(engagement, tb_records, db, pos=pos) if db is not None else None
        # Below the lead, which grows with one line per adjusting journal
        p0 = max(22, lines["end"] + 3) if ctx.tb_kind else 22
        ws[f"A{p0}"] = proof["title"] if proof else "Reconciliation to the VAT returns"
        ws[f"A{p0}"].font = bold_font
        ws[f"E{p0 + 1}"] = "Link to details"
        row = first = p0 + 2
        for line in (proof["lines"] if proof else []):
            ws[f"A{row}"] = line["label"] + ("" if line["amount"] is not None or line["entered"] else " (not known)")
            ws[f"D{row}"] = line["amount"]
            ws[f"F{row}"] = line["note"]
            if line["key"] in ("outstanding", "charges"):
                ws[f"E{row}"] = "G9.1"
            elif line["key"] in ("filed_not_in_accounts", "flat_rate_surplus"):
                ws[f"E{row}"] = "G9.5"
            row += 1
        ws[f"A{row}"] = "Other differences (explain):"
        total = row + 2
        ws[f"A{total}"] = "Total"
        ws[f"D{total}"] = f"=SUM(D{first}:D{total - 1})"
        ws[f"D{total}"].border = accounting_total_border
        ws[f"A{total + 2}"] = "VAT owed per the ledger (above)"
        ws[f"D{total + 2}"] = f"={cf_cell}"
        # A check (amber: an agreement to outside evidence) only once the VAT returns are entered: before that the Data check
        # asks for them, and the difference is the whole VAT balance
        returns_in = bool(getattr(pos, "returns", None))
        # What is left is the 'Unidentified difference', kept (never forced to nil) and on the cover
        ws[f"B{total + 4}"] = ("Unidentified difference: ledger v VAT returns (must be nil)" if returns_in
                               else "Unidentified difference (no VAT returns entered yet)")
        ws[f"B{total + 4}"].font = bold_font
        ws[f"D{total + 4}"] = f"=ROUND(D{total + 2}-D{total},2)"
        ws[f"D{total + 4}"].font = bold_font
        last_row = total + 4
        # The reconciliation's amounts (the T above keeps its own format: nil shown as '-')
        for r in range(p0 if ctx.tb_kind else 8, last_row + 1):
            for c in (4, 5):
                ws.cell(row=r, column=c).number_format = "#,##0.00;(#,##0.00)"

    # 11. VAT (Section G9)
    # The VAT tabs: for a VAT registered client (a VAT account in the books, VAT returns given, or the setup says so),
    # even with no VAT account in the trial balance; never for a client the accountant confirmed as not registered
    from backend.app.models.database import ClientProfile, VAT100Record
    from backend.app.services.setup.profile_service import confirmed_fields
    profile = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement.id).first() if db is not None else None
    confirmed_no = profile is not None and not profile.is_vat_registered and "is_vat_registered" in confirmed_fields(profile)
    returns_given = db is not None and db.query(VAT100Record).filter(VAT100Record.engagement_id == engagement.id).first() is not None
    has_vat = not confirmed_no and (any(c in tb_codes_present for c in {"5300", "2200"}) or returns_given
                                    or (profile is not None and bool(profile.is_vat_registered)
                                        and "is_vat_registered" in confirmed_fields(profile)))
    if confirmed_no and any(c in tb_codes_present for c in {"5300", "2200"}):
        report_notes.append("VAT balance on a client confirmed as not VAT registered: reclassify it (review point V-B03)")
    if not has_vat:
        for s in ["G9 - VAT", "G9-.1-VAT Summary", "G9.2 - Late claims", "G9.3-VAT-NL Transactions ", "G9.4-VAT - HMRC details"]:
            remove_sheet(s)
        if "G1 (LEAD)" in wb.sheetnames:
            wb["G1 (LEAD)"]["D23"] = 0.0
    else:
        rebuild_control_subledger("G9.3-VAT-NL Transactions ", {"5300", "5700"}, "vat", "VAT Control Account")
        build_vat_summary()
        # G9.4 is where the accountant pastes HMRC's payment history: its formula columns show nil on every empty row
        # (rows of zeros), so a nil shows blank and the tab says what to paste
        if "G9.4-VAT - HMRC details" in wb.sheetnames:
            hm = wb["G9.4-VAT - HMRC details"]
            if hm["A3"].value in (None, ""):
                hm["A3"] = ("Paste the payment history from HMRC's VAT account (date, description, period, paid, "
                            "repaid) from row 5; the columns on the right fill in from it.")
            for row in hm.iter_rows(min_row=5, min_col=6, max_col=hm.max_column):
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        cell.number_format = '#,##0.00;(#,##0.00);""'
        # G9.5: each VAT return against the ledger's own VAT (VAT guide, Box_Recon and return reconciliation)
        if db is not None:
            review = vat_review(engagement, tb_records, db)
            after = next((n for n in ("G9.4-VAT - HMRC details", "G9.3-VAT-NL Transactions ", "G9 - VAT") if n in wb.sheetnames), None)
            ws = wb.create_sheet("G9.5 - VAT return review", wb.sheetnames.index(after) + 1 if after else len(wb.sheetnames))
            ws["A1"] = "=A!B2"
            ws["A2"] = "='Notes & Queries'!A2"
            ws["A4"] = "VAT returns against the ledger (VAT review guide)"
            ws["A4"].font = Font(name="Calibri", size=12, bold=True)
            ws["A5"] = ("Box 1 and Box 4 of each return compared with the VAT on the ledger lines dated in its period "
                        "(reverse charge added to both, as on the return). Late entries show as a difference on one return "
                        "and the opposite on a later one.")
            heads = ["Return", "From", "To", "Box 1", "Ledger output VAT", "Difference", "Box 4", "Ledger input VAT",
                     "Difference", "Reverse charge", "Net under / (over) declared", "Correction (V-I03)", "Box 6"]
            for c, text in enumerate(heads, 1):
                ws.cell(row=7, column=c, value=text).font = bold_font
            money = "#,##0.00;(#,##0.00);-"
            for r, rc in enumerate(review.returns, 8):
                values = [rc.label, rc.start, rc.end, rc.box1, rc.ledger_output, f"=D{r}-E{r}", rc.box4, rc.ledger_input,
                          f"=G{r}-H{r}", rc.reverse_charge, f"=(E{r}-D{r})-(H{r}-G{r})", rc.correction, rc.box6]
                for c, v in enumerate(values, 1):
                    cell = ws.cell(row=r, column=c, value=v)
                    cell.number_format = "dd/mm/yyyy" if c in (2, 3) else money
            if review.returns:
                tr = 8 + len(review.returns)
                ws.cell(row=tr, column=1, value="Total").font = bold_font
                for c in (4, 5, 6, 7, 8, 9, 10, 11, 13):
                    col = get_column_letter(c)
                    cell = ws.cell(row=tr, column=c, value=f"=SUM({col}8:{col}{tr - 1})")
                    cell.font, cell.number_format = bold_font, money
                row = tr + 2
            else:
                ws["A8"] = "No VAT returns entered for this year (VAT returns screen)."
                row = 10
            if review.returns and not review.ledger_has_vat:
                ws.cell(row=row, column=1, value="The ledger export has no VAT columns, so the ledger VAT is blank.")
                row += 1
            if review.findings:
                ws.cell(row=row + 1, column=1, value="Points to review").font = bold_font
                for i, vf in enumerate(review.findings, row + 2):
                    ws.cell(row=i, column=1, value=vf.test)
                    ws.cell(row=i, column=2, value=vf.title)
                    ws.cell(row=i, column=8, value=vf.details)
                report_notes.append(f"{len(review.findings)} VAT point(s) to review: VAT return review (G9.5)")
            ws.column_dimensions["A"].width = 14
            ws.column_dimensions["L"].width = 34
