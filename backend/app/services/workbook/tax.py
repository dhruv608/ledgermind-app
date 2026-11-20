"""The tax and checks tabs: H1 (this client's corporation tax computation, with the tax per financial year as formulas
and the check against the tax in the accounts), H2 (the CT600 boxes, ct600.py) and A1 (the general checks)."""

from openpyxl.styles import Font

from backend.app.services.tax.ct_computation import MAIN_RATE_FROM, ct_computation, final_balances, tax_parameters
from backend.app.services.review.universal_checks import general_checks
from backend.app.services.workbook.context import BuildContext


def add_tax_tab(ctx: BuildContext) -> None:
    wb, engagement, db, tb_records = ctx.wb, ctx.engagement, ctx.db, ctx.tb_records
    report_notes = ctx.report_notes
    bold_font, accounting_total_border = ctx.bold_font, ctx.accounting_total_border

    # H1 - Taxation: this client's corporation tax computation (CT600 guide, Tax_Comp). The template's rows below
    # the CT control account hold an example client's formula, so they are cleared.
    if db is not None and "H1-Taxation" in wb.sheetnames:
        comp = ct_computation(engagement, tb_records, db)
        ws = wb["H1-Taxation"]
        # The CT creditor (5310) as one T with its lines named at the top, as the screen shows it: b/f, the year's lines (tax paid, tax booked), the journals by name (this year's charge), the c/d;
        # the computation below it. G1 and B1-ETB read the T's c/d and b/f (owed to HMRC +)
        for row in ws.iter_rows(min_row=5, max_row=max(ws.max_row, 17)):
            for cell in row:
                if type(cell).__name__ != "MergedCell":
                    cell.value = None
                    cell.hyperlink = None
        for c in range(5, 14):                # the template's 'THIS YEAR' box beside the title (the tiles go there)
            if type(ws.cell(row=4, column=c)).__name__ != "MergedCell":
                ws.cell(row=4, column=c).value = None
        from backend.app.services.workbook.balance_tabs.common import on_tab
        from backend.app.services.workbook.balance_tabs.t_shape import t_account
        t = t_account(ctx, ws, [5310], top=6, owed=True)
        ctx.schedule_cf[5310] = (on_tab(ws.title, t["cf_s"]), -1)
        if "G1 (LEAD)" in wb.sheetnames:
            g1 = wb["G1 (LEAD)"]
            for row in g1.iter_rows(min_row=1, max_row=min(g1.max_row, 80), min_col=4, max_col=5):
                for cell in row:
                    v = str(cell.value or "").replace(" ", "")
                    if v in ("='H1-Taxation'!D14", "=+'H1-Taxation'!D14"):
                        cell.value = f"={on_tab(ws.title, t['cf_s'])}"
                    elif v in ("='H1-Taxation'!E8", "=+'H1-Taxation'!E8"):
                        # last year's balance with the opening adjustment, as the control's b/fwd always read
                        cell.value = f"=-({on_tab(ws.title, t['bf'] + '+' + t['adj'])})"
        money = "#,##0.00;(#,##0.00);-"
        r = max(18, t["end"] + 3)
        ws.cell(row=r, column=1, value="CORPORATION TAX COMPUTATION").font = bold_font
        ws.cell(row=r, column=6, value="CT600 box").font = bold_font
        ws.cell(row=r + 1, column=1, value=f"Accounting period {comp.period_start:%d/%m/%Y} to {comp.period_end:%d/%m/%Y} "
                                           f"({comp.days} days); associated companies: {comp.associated_companies}")
        r += 3
        chargeable_row = None
        # Linked to the accounts (every tab linked): a line worked from the final balances is a formula on
        # B1-ETB, and a total is the sum of the lines above it - each only when it gives the computation's own figure
        balances = final_balances(str(engagement.id), tb_records, db)
        block_start, written = None, {}

        def linked(line) -> object:
            # Depreciation is added back from the whole P&L depreciation range (3400-3406), always as a formula: a
            # charge posted later (the FAR journal on 3400) or on a code the computation did not hold is still added
            # back
            if line.label.startswith("Add: depreciation"):
                return ("=ROUND(SUMIFS('B1-ETB'!$N:$N,'B1-ETB'!$A:$A,\">=3400\",'B1-ETB'!$A:$A,\"<=3406\"),2)")
            if not line.codes:
                return None
            value = line.sign * sum(balances.get(code, 0.0) for code in line.codes)
            if line.floor:
                value = max(0.0, value)
            if abs(round(value, 2) - line.amount) > 0.01:
                return None
            terms = "+".join(f"SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!$N:$N)" for code in line.codes)
            # Profit before tax as two ranges (every P&L code but the tax charge, 3800-3899) instead of a SUMIF per
            # code (a formula a reviewer reads in one line), when the ranges give the same figure
            if line.label.startswith("Profit before tax") and len(line.codes) > 3:
                in_range = [c for c in balances if c < 3800 or 3900 <= c < 4000]
                ranged = line.sign * sum(balances.get(c, 0.0) for c in in_range)
                if abs(round(ranged, 2) - line.amount) <= 0.01:
                    terms = ("SUMIF('B1-ETB'!$A:$A,\"<3800\",'B1-ETB'!$N:$N)"
                             "+SUMIFS('B1-ETB'!$N:$N,'B1-ETB'!$A:$A,\">=3900\",'B1-ETB'!$A:$A,\"<4000\")")
            formula = f"-({terms})" if line.sign < 0 else terms
            return f"=ROUND(MAX(0,{formula}),2)" if line.floor else f"=ROUND({formula},2)"

        for line in comp.lines:
            if line.label.startswith("Corporation tax") or line.label.startswith(("Less: double", "s455", "Total tax")):
                continue
            total = line.label.startswith(("Adjusted", "Trading profits", "Net trading", "Profits"))
            value = linked(line)
            if line.label.startswith("Profit before tax"):
                block_start = r
            elif total and block_start is not None and r > block_start:
                above = round(sum(written.get(i, 0.0) for i in range(block_start, r)), 2)
                if abs(above - line.amount) <= 0.01:
                    value = f"=SUM(D{block_start}:D{r - 1})"
            if total:
                block_start = r            # the next total adds up from this one
            written[r] = line.amount
            ws.cell(row=r, column=2, value=line.label).font = bold_font if total else Font(name="Calibri", size=10)
            cell = ws.cell(row=r, column=4, value=value if value is not None else line.amount)
            cell.number_format = money
            if total:
                cell.font = bold_font
            ws.cell(row=r, column=6, value=line.box or None)
            ws.cell(row=r, column=7, value=line.note or None)
            if line.label.startswith("Profits chargeable"):
                chargeable_row = r
                cell.border = accounting_total_border
            r += 1

        # Tax for each financial year in the period, as formulas on the profits chargeable (edit a line, tax follows)
        r += 1
        for c, text in enumerate(["Period from", "Period to", "Days", "Profit", "Tax at rate", "Marginal relief",
                                  "Final tax", "Basis"], 1):
            ws.cell(row=r, column=c, value=text).font = bold_font
        first_slice = r + 1
        params = tax_parameters()
        small, main = params.get("P-CT-SPR", 0.19), params.get("P-CT-MAIN", 0.25)
        has_dividends = any(l.box == "620" for l in comp.lines)
        for sl in comp.rate_slices:
            r += 1
            ws.cell(row=r, column=1, value=sl["from"]).number_format = "dd/mm/yyyy"
            ws.cell(row=r, column=2, value=sl["to"]).number_format = "dd/mm/yyyy"
            ws.cell(row=r, column=3, value=sl["days"])
            ws.cell(row=r, column=4, value=f"=ROUND($D${chargeable_row}*C{r}/{comp.days},2)")
            if has_dividends:
                # Augmented profits include exempt dividends: keep the computed figures
                ws.cell(row=r, column=5, value=sl["tax_at_rate"])
                ws.cell(row=r, column=6, value=sl["marginal_relief"])
            elif sl["from"] < MAIN_RATE_FROM:
                ws.cell(row=r, column=5, value=f"=D{r}*0.19")
                ws.cell(row=r, column=6, value=0)
            else:
                low, up = sl["lower"], sl["upper"]
                ws.cell(row=r, column=5, value=f"=IF(D{r}<={low},D{r}*{small},D{r}*{main})")
                ws.cell(row=r, column=6, value=f"=IF(AND(D{r}>{low},D{r}<{up}),3/200*({up}-D{r}),0)")
            ws.cell(row=r, column=7, value=f"=E{r}-F{r}")
            ws.cell(row=r, column=8, value=f"limits £{sl['lower']:,.0f} / £{sl['upper']:,.0f}")
            for c in (4, 5, 6, 7):
                ws.cell(row=r, column=c).number_format = money
        last_slice = r
        r += 1
        for c, col in ((3, "C"), (4, "D"), (5, "E"), (6, "F"), (7, "G")):
            cell = ws.cell(row=r, column=c, value=f"=SUM({col}{first_slice}:{col}{last_slice})")
            cell.font = bold_font
            if c > 3:
                cell.number_format = money
        totals_row = r
        r += 1
        ws.cell(row=r, column=5, value="Double tax relief")
        ws.cell(row=r, column=7, value=-comp.double_tax_relief).number_format = money
        ws.cell(row=r, column=6, value="450")                  # CT600 box 450 (480 is s455)
        dtr_row = r
        r += 1
        ws.cell(row=r, column=5, value="Corporation tax chargeable").font = bold_font
        cell = ws.cell(row=r, column=7, value=f"=G{totals_row}+G{dtr_row}")
        cell.number_format, cell.font, cell.border = money, bold_font, accounting_total_border
        ct_row = r
        # The control account (the T above, from the ETB's 5310 line, owed as a credit: b/fwd, the year's payments and
        # any tax the client booked, then this year's charge once approved) ends at the books' 5310, last years'
        # unpaid tax included. The computed charge is agreed to the books below ('Tax charge in the accounts')
        if comp.s455_tax:
            r += 1
            ws.cell(row=r, column=5, value="s455 tax (CT600A)")
            ws.cell(row=r, column=7, value=comp.s455_tax).number_format = money
            ws.cell(row=r, column=8, value=comp.s455_explanation)
            r += 1
            ws.cell(row=r, column=5, value="Total tax chargeable").font = bold_font
            ws.cell(row=r, column=7, value=f"=G{ct_row}+G{r - 1}").number_format = money

        # Check against the tax in the accounts (CT600 guide: must be nil before signing)
        r += 2
        ws.cell(row=r, column=2, value="Tax charge in the accounts (ETB 3800)")
        ws.cell(row=r, column=7, value="=ROUND(SUMIF('B1-ETB'!$A:$A,3800,'B1-ETB'!$N:$N),2)").number_format = money
        ws.cell(row=r + 1, column=2, value="Difference: accounts less computation").font = bold_font
        ws.cell(row=r + 1, column=7, value=f"=G{r}-G{ct_row}").number_format = money
        r += 3

        # Capital allowances and losses memo
        ws.cell(row=r, column=1, value="Capital allowances").font = bold_font
        r += 1
        ca_first = r
        for a in comp.capital_allowances:
            ws.cell(row=r, column=2, value=a.label)
            ws.cell(row=r, column=4, value=a.amount).number_format = money
            r += 1
        # The computation's 'Less: capital allowances' line as the sum of these lines (linked, not a
        # typed figure), when they are what it was worked from
        less = next((row for row in range(1, ca_first) if str(ws.cell(row=row, column=2).value or "").strip()
                     == "Less: capital allowances"), None)
        if (less and comp.capital_allowances and isinstance(ws.cell(row=less, column=4).value, (int, float))
                and abs(-ws.cell(row=less, column=4).value - sum(a.amount for a in comp.capital_allowances)) < 0.01):
            ws.cell(row=less, column=4, value=f"=-SUM(D{ca_first}:D{r - 1})").number_format = money
        if not comp.capital_allowances:
            ws.cell(row=r, column=2, value=(
                "None worked out: the company holds fixed assets but no pool brought forward is entered. Enter last "
                "year's main and special rate pools from last year's computation (query CT-CA-003)."
                if comp.pools_missing else "None this period"))
            r += 1
        ws.cell(row=r, column=2, value="Main pool carried forward")
        ws.cell(row=r, column=4, value=comp.main_pool_cf).number_format = money
        ws.cell(row=r + 1, column=2, value="Special rate pool carried forward")
        ws.cell(row=r + 1, column=4, value=comp.special_pool_cf).number_format = money
        r += 3
        ws.cell(row=r, column=1, value="Trading losses").font = bold_font
        for i, (label, value) in enumerate((("Used this period", comp.losses_used),
                                            ("Carried forward", comp.losses_carried_forward)), 1):
            ws.cell(row=r + i, column=2, value=label)
            ws.cell(row=r + i, column=4, value=value).number_format = money
        r += 4
        if comp.notes:
            ws.cell(row=r, column=1, value="To confirm before the CT600").font = bold_font
            for i, note in enumerate(comp.notes, 1):
                ws.cell(row=r + i, column=2, value=note)
            report_notes.append(f"Corporation tax: {len(comp.notes)} point(s) to confirm (H1)")
        ws.column_dimensions["B"].width = 48
        ws.column_dimensions["G"].width = 16

        # H1.2: the capital allowances per pool
        from backend.app.services.workbook.ca_tab import ca_tab
        ca_tab(ctx, comp, "H1-Taxation")

        # H2: the CT600 boxes from this computation (the firm's CT600 guide)
        import json
        from backend.app.services.workbook.ct600 import ct600_tab
        prof = getattr(engagement, "profile", None)
        register = json.loads(prof.companies_house or "{}") if prof is not None and getattr(prof, "companies_house", None) else {}
        setup_client = (json.loads(prof.setup or "{}").get("client") or {}) if prof is not None and getattr(prof, "setup", None) else {}
        ct600_tab(wb, comp, engagement, setup_client.get("company_number") or register.get("company_number"))
        # I: deferred tax on fixed assets, the working of CT-DT-001 and its journal
        from backend.app.services.mapping.chart_lookup import ChartLookup
        from backend.app.services.workbook.deferred_tax_tab import add_deferred_tax_tab
        add_deferred_tax_tab(wb, comp, engagement, balances, ChartLookup(db).accounts)


# The general checks about one area, on that area's tab (the first the workbook has), as the screen places them
POINT_TABS = {"U-EQ-001": ["J2 - Reserves", "G3- DLA"], "U-DEB-002": ["E2-Trade Debtors"],
              "U-CRD-090": ["G2 - Trade creditors"], "U-BNK-004": ["F2-Bank", "F1 (LEAD)"],
              "U-BNK-005": ["F2-Bank", "F1 (LEAD)"]}


def add_general_checks_tab(ctx: BuildContext) -> None:
    wb, engagement, db, tb_records = ctx.wb, ctx.engagement, ctx.db, ctx.tb_records
    report_notes, bold_font = ctx.report_notes, ctx.bold_font

    # A1 - General checks: going concern, dividends against reserves, old debtors, cash in hand (every client)
    if db is not None:
        checks = general_checks(engagement, tb_records, db)
        ws = wb.create_sheet("A1 - General checks", wb.sheetnames.index("A") + 1 if "A" in wb.sheetnames else 0)
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        ws["A4"] = "General checks (Industry Query Library, every client)"
        ws["A4"].font = Font(name="Calibri", size=12, bold=True)
        ws["A5"] = ("Figures from the ETB (TB plus approved journals) and the corporation tax computation (H1).")
        row = 7
        for label, value in checks.figures.items():
            ws.cell(row=row, column=1, value=label)
            cell = ws.cell(row=row, column=3, value=value)
            cell.number_format = "#,##0.00;(#,##0.00);-"
            row += 1
        row += 1
        ws.cell(row=row, column=1, value="Points to review (the whole job)").font = bold_font
        row += 1
        # A point about one area goes on that area's tab, as on the screen (Review points: each point in its area,
        # only the whole job's here); written there at the end of the build (screen_papers.general_points_paper)
        moved, whole = [], []
        for gf in checks.findings:
            tabs = POINT_TABS.get(gf.query, [])
            tab = next((t for t in tabs if t in wb.sheetnames), None)
            (moved if tab else whole).append((tab, gf))
        ctx.general_points = moved
        if not whole:
            ws.cell(row=row, column=1, value="Nothing to raise for the whole job (going concern)." if checks.findings
                    else "Nothing to raise: no going concern, dividend, old debtor or cash issue found.")
            row += 1
        for _tab, gf in whole:
            ws.cell(row=row, column=1, value=gf.title).font = bold_font
            ws.cell(row=row + 1, column=1, value=gf.details)
            row += 3
        if moved:
            ws.cell(row=row, column=1, value="On their area's tab: " + "; ".join(
                f"{gf.title} ({tab.split(' - ')[0].split('-')[0].strip()})" for tab, gf in moved))
            row += 2
        # The debtors over 90 days are listed on E2 ('customer items to look at', from the same aged report)
        if checks.old_debtors and "E2-Trade Debtors" not in wb.sheetnames:
            ws.cell(row=row, column=1, value="Debtors more than 90 days old").font = bold_font
            for i, (name, amount) in enumerate(list(checks.old_debtors.items())[:40], row + 1):
                ws.cell(row=i, column=2, value=name)
                ws.cell(row=i, column=3, value=amount).number_format = "#,##0.00"
        if checks.findings:
            report_notes.append(f"{len(checks.findings)} general point(s) to review: general checks (A1)")
        ws.column_dimensions["A"].width = 40
        ws.column_dimensions["B"].width = 60
        ws.column_dimensions["C"].width = 16
