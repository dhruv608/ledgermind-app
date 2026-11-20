"""The review tabs from the SOPs: duplicates (G2.3), related parties (G3.2), pattern and anomaly (K0), the restaurant
review (K0.1)."""

from datetime import date
from openpyxl.styles import Font
from backend.app.services.setup.profile_service import confirmed_industry
from backend.app.services.sop.duplicates import duplicate_review
from backend.app.services.sop.pattern import PATTERN_QUESTION, pattern_review
from backend.app.services.sop.related_party import person_lenders, related_parties, related_party_review
from backend.app.services.sop.restaurant import GROSS_PROFIT_RANGE, STAFF_COST_RANGE, restaurant_review


def step_duplicates(ctx, shared) -> None:
    """Duplicates SOP (G2.3): bills / invoices entered twice, outstanding ones already paid directly, and contacts
    paid both ways. Customer and supplier sides are kept apart."""
    ageing, bold_font, db, engagement = shared.ageing, shared.bold_font, shared.db, shared.engagement
    report_notes, wb = shared.report_notes, shared.wb
    if db is not None:
        dup_flags = duplicate_review(str(engagement.id), engagement.period_end_date, db)
        after = next((n for n in ("G2.2 - A P Ageing Details", "G2 - Trade creditors", "G1 (LEAD)") if n in wb.sheetnames), None)
        ws = wb.create_sheet("G2.3 - Duplicates review",
                             wb.sheetnames.index(after) + 1 if after else len(wb.sheetnames))
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        ws["A4"] = "Duplicate transactions review"
        ws["A4"].font = Font(name="Calibri", size=12, bold=True)
        missing = [k for k, kind in (("AP", "payables"), ("AR", "receivables"))
                   if not (ageing.get(k) and ageing[k].as_at in (None, engagement.period_end_date))]
        ws["A5"] = ("Bills / invoices entered twice (or the same amount within a week), and outstanding ones with a matching direct payment / receipt. "
                    "Review only: nothing is posted."
                    + (f" No aged {' / '.join('payables' if k == 'AP' else 'receivables' for k in missing)} report at "
                       f"the year end, so that side's outstanding items could not be checked." if missing else ""))
        heads = ["Side", "Check", "Contact", "Date", "Number", "Amount", "Finding", "Detail", "Question for the client"]
        for c, text in enumerate(heads, 1):
            ws.cell(row=7, column=c, value=text).font = bold_font
        names = {"duplicate": "Entered twice", "possible": "Possible duplicate (review)",
                 "unallocated": "Paid but outstanding", "mixed": "Mixed posting (warning)"}
        for r, f in enumerate(dup_flags, 8):
            values = [f.side.title(), names[f.check], f.contact, f.when, f.number, f.amount, f.message, f.detail, f.question]
            for c, v in enumerate(values, 1):
                cell = ws.cell(row=r, column=c, value=v)
                if isinstance(v, date):
                    cell.number_format = "dd/mm/yyyy"
                elif c == 6:
                    cell.number_format = "#,##0.00"
        if not dup_flags:
            ws["A8"] = "No duplicate or unallocated items found."
        serious = sum(1 for f in dup_flags if f.check != "mixed")
        if serious:
            report_notes.append(f"{serious} possible duplicate / unallocated item(s): duplicates review (G2.3)")
        ws.column_dimensions["C"].width = 30
        ws.column_dimensions["H"].width = 60


def step_related(ctx, shared) -> None:
    """Related Party SOP (G3.2): every ledger line naming a director / shareholder / their company, and every line of
    the director's loan account. Report only: nothing is reclassified."""
    bold_font, db, engagement, report_notes = shared.bold_font, shared.db, shared.engagement, shared.report_notes
    tb_records, wb = shared.tb_records, shared.wb
    if db is not None:
        parties = related_parties(engagement)
        summaries = related_party_review(engagement, tb_records, db) if parties else []
        after = next((n for n in ("G3.1 - DLA-NL Transactions", "G3- DLA", "G1 (LEAD)") if n in wb.sheetnames), None)
        ws = wb.create_sheet("G3.2 - Related parties",
                             wb.sheetnames.index(after) + 1 if after else len(wb.sheetnames))
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        ws["A4"] = "Related party transactions"
        ws["A4"].font = Font(name="Calibri", size=12, bold=True)
        ws["A5"] = ("Related parties: " + ("; ".join(f"{p.name} ({p.role}, {p.source})" for p in parties)
                                           if parties else "none in the client setup, so names could not be searched")
                    + ". Salary and pension paid to directors are left out. Report only: nothing is reclassified.")
        heads = ["Date", "Amount", "Account", "P&L or balance sheet", "Contact", "Description", "Matched name / company",
                 "Match", "Match source", "Flag"]
        for c, text in enumerate(heads, 1):
            ws.cell(row=7, column=c, value=text).font = bold_font
        rows = sorted((l for s in summaries for l in s.lines), key=lambda l: (l.party, l.when))
        for r, l in enumerate(rows, 8):
            values = [l.when, l.amount, l.account, l.side, l.contact, l.description[:250], l.party, l.match, l.source, l.message]
            for c, v in enumerate(values, 1):
                cell = ws.cell(row=r, column=c, value=v)
                if c == 1:
                    cell.number_format = "dd/mm/yyyy"
                elif c == 2:
                    cell.number_format = "#,##0.00"
        if not rows:
            ws["A8"] = "No related party transactions found." if parties else "Add the directors on the Setup tab first."
        else:
            report_notes.append(f"{len(rows)} related party transaction(s) to review and disclose: related parties (G3.2)")
        # Loans from people not on the list: a director's close family member is a related party
        # (FRS 102 s33), so who each lender is is asked (point RP-03)
        lenders = person_lenders(engagement, tb_records, db)
        if lenders:
            r = 8 + max(len(rows), 1) + 2
            ws.cell(row=r, column=1, value=("Loans from people not on the related party list: ask if each is a director, "
                                            "a shareholder or a close family member (then add them above and disclose)")).font = bold_font
            for c, text in enumerate(["Lender", "Lent £", "Repaid £", "Accounts"], 1):
                ws.cell(row=r + 1, column=c, value=text).font = bold_font
            for i, lender in enumerate(lenders, r + 2):
                ws.cell(row=i, column=1, value=lender["name"])
                ws.cell(row=i, column=2, value=lender["lent"]).number_format = "#,##0.00"
                ws.cell(row=i, column=3, value=lender["repaid"]).number_format = "#,##0.00"
                ws.cell(row=i, column=4, value=", ".join(f"{a} ({c})" for a, c in lender["accounts"].items())[:200])
            report_notes.append(f"{len(lenders)} loan(s) from a person: who is the lender? related parties (G3.2)")
        for col, width in (("C", 30), ("E", 25), ("F", 50), ("G", 28), ("J", 60)):
            ws.column_dimensions[col].width = width


def step_pattern(ctx, shared) -> None:
    """Pattern & Anomaly SOP (K0): payments that lack descriptions, look unusual or break the normal pattern."""
    bold_font, db, engagement, report_notes = shared.bold_font, shared.db, shared.engagement, shared.report_notes
    tb_records, wb = shared.tb_records, shared.wb
    # The client report: date, amount, account, description, reason. Nothing more, no conclusions.
    if db is not None:
        pattern_flags = pattern_review(str(engagement.id), engagement.period_end_date, tb_records, db)
        ws = wb.create_sheet("K0 - Pattern review",
                             wb.sheetnames.index("K") + 1 if "K" in wb.sheetnames else len(wb.sheetnames))
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        ws["A4"] = "Pattern and anomaly review"
        ws["A4"].font = Font(name="Calibri", size=12, bold=True)
        ws["A5"] = PATTERN_QUESTION
        for c, text in enumerate(["Date", "Amount", "Account", "Description", "Reason for flag"], 1):
            ws.cell(row=7, column=c, value=text).font = bold_font
        for r, f in enumerate(pattern_flags, 8):
            for c, v in enumerate([f.when, f.amount, f.account, f.description[:250], " ".join(f.reasons)], 1):
                cell = ws.cell(row=r, column=c, value=v)
                if c == 1 and v is not None:
                    cell.number_format = "dd/mm/yyyy"
                elif c == 2:
                    cell.number_format = "#,##0.00"
        if not pattern_flags:
            ws["A8"] = "No unidentified, unusual or irregular payments found."
        else:
            report_notes.append(f"{len(pattern_flags)} payment(s) to confirm with the client: pattern review (K0)")
        ws.column_dimensions["C"].width = 30
        ws.column_dimensions["D"].width = 60
        ws.column_dimensions["E"].width = 60


def step_restaurant(ctx, shared) -> None:
    """Restaurant SOP (K0.1), only when the accountant has confirmed the client is a restaurant."""
    bold_font, db, engagement, report_notes = shared.bold_font, shared.db, shared.engagement, shared.report_notes
    tb_records, wb = shared.tb_records, shared.wb
    if db is not None and confirmed_industry(getattr(engagement, "profile", None)) == "RES":
        review = restaurant_review(str(engagement.id), engagement.period_end_date, tb_records, db)
        after = "K0 - Pattern review" if "K0 - Pattern review" in wb.sheetnames else "K"
        ws = wb.create_sheet("K0.1 - Restaurant review",
                             wb.sheetnames.index(after) + 1 if after in wb.sheetnames else len(wb.sheetnames))
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        ws["A4"] = "Restaurant review"
        ws["A4"].font = Font(name="Calibri", size=12, bold=True)
        ws["A5"] = ("Sales recorded gross, food through cost of sales, staff through payroll. The other restaurant checks are "
                    "on the payroll (G6.2), accruals (G10.2), prepayments (E3.2) and capital (C1.2) reviews.")
        figures = [("Sales", review.sales, None), ("Cost of sales", review.cost_of_sales, None),
                   ("Gross profit %", review.gross_profit_pct, f"usual {GROSS_PROFIT_RANGE[0]:.0f}-{GROSS_PROFIT_RANGE[1]:.0f}%"),
                   ("Staff costs", review.staff_costs, None),
                   ("Staff costs % of sales", review.staff_cost_pct, f"usual {STAFF_COST_RANGE[0]:.0f}-{STAFF_COST_RANGE[1]:.0f}%")]
        for r, (label, value, note) in enumerate(figures, 7):
            ws.cell(row=r, column=1, value=label).font = bold_font
            ws.cell(row=r, column=2, value=value).number_format = "#,##0.00"
            if note:
                ws.cell(row=r, column=3, value=note)
        row = 7 + len(figures) + 1
        for note in review.sense_checks():
            ws.cell(row=row, column=1, value=note)
            row += 1
        row += 1
        for c, text in enumerate(["Rule", "Date", "Account", "Description", "Amount", "Reason for flag"], 1):
            ws.cell(row=row, column=c, value=text).font = bold_font
        for r, f in enumerate(review.flags, row + 1):
            for c, v in enumerate([f.rule, f.when, f.account, f.description[:250], f.amount, f.reason], 1):
                cell = ws.cell(row=r, column=c, value=v)
                if c == 2 and v is not None:
                    cell.number_format = "dd/mm/yyyy"
                elif c == 5:
                    cell.number_format = "#,##0.00"
        if not review.flags:
            ws.cell(row=row + 1, column=1, value="No restaurant recognition issues found.")
        if review.flags or review.sense_checks():
            report_notes.append(f"{len(review.flags)} restaurant item(s) to review: restaurant review (K0.1)")
        ws.column_dimensions["A"].width = 24
        ws.column_dimensions["C"].width = 30
        ws.column_dimensions["D"].width = 60
        ws.column_dimensions["F"].width = 60
