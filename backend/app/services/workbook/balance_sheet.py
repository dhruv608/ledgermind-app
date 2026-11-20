"""Balance sheet tabs: D stock, E debtors (with the aged list), E3 prepayments (+ E3.2 prepayment review), F bank,
G2 creditors (+ G2.3 duplicates review), G3 DLA (+ G3.2 related parties), the K0 pattern and K0.1 restaurant reviews,
G10 accruals (+ G10.2 accrual review) and J2 reserves. Payroll and VAT (G6-G9) run between the DLA and the accruals,
so these come as three steps."""

from types import SimpleNamespace
from functools import partial
import re
from typing import Any, Dict

from openpyxl.styles import Alignment, Font, PatternFill

from backend.app.services.sop.accruals import accrual_review
from backend.app.services.workbook.context import GL_TAB, BuildContext
from backend.app.services.workbook.context import (rebuild_control_subledger as _rebuild_control_subledger,
                                                   reconcile_ageing as _reconcile_ageing,
                                                   write_ageing_report as _write_ageing_report,
                                                   write_balance_summary as _write_balance_summary)


# A debtor or creditor ledger kept in another currency (QuickBooks multi-currency: 'Debtors - EUR', 'Creditors - JPY')
CURRENCY_LEDGER = re.compile(r"\b(EUR|USD|JPY|CHF|AUD|CAD|NZD|SEK|NOK|DKK|PLN|INR|CNY|HKD|SGD|AED)\b|[€$¥]", re.I)


def add_balance_sheet_tabs(ctx: BuildContext) -> None:
    """D stock to G3 DLA, with their review tabs."""
    wb, engagement, db, tb_records = ctx.wb, ctx.engagement, ctx.db, ctx.tb_records
    tb_codes_present, report_notes, ageing = ctx.tb_codes_present, ctx.report_notes, ctx.ageing
    client_name, ye_str = ctx.client_name, ctx.ye_str
    bold_font, accounting_total_border = ctx.bold_font, ctx.accounting_total_border
    remove_sheet = ctx.remove_sheet
    rebuild_control_subledger = partial(_rebuild_control_subledger, ctx)
    write_balance_summary = partial(_write_balance_summary, ctx)
    reconcile_ageing = partial(_reconcile_ageing, ctx)
    write_ageing_report = partial(_write_ageing_report, ctx)
    from backend.app.services.workbook import bs_bank_creditors, bs_dla, bs_sops, bs_stock_debtors   # here: they import from this module
    shared = SimpleNamespace(**{k: v for k, v in locals().items() if k != 'shared'})
    bs_stock_debtors.step_stock(ctx, shared)
    bs_stock_debtors.step_debtors(ctx, shared)
    bs_stock_debtors.step_prepayments(ctx, shared)
    bs_bank_creditors.step_bank(ctx, shared)
    bs_bank_creditors.step_creditors(ctx, shared)
    bs_sops.step_duplicates(ctx, shared)
    bs_sops.step_related(ctx, shared)
    bs_sops.step_pattern(ctx, shared)
    bs_sops.step_restaurant(ctx, shared)
    bs_dla.step_dla(ctx, shared)


def add_accrual_tabs(ctx: BuildContext) -> None:
    """G10 accruals and the G10.2 accrual review."""
    wb, engagement, db, tb_records = ctx.wb, ctx.engagement, ctx.db, ctx.tb_records
    tb_codes_present, report_notes = ctx.tb_codes_present, ctx.report_notes
    bold_font, remove_sheet = ctx.bold_font, ctx.remove_sheet
    rebuild_control_subledger = partial(_rebuild_control_subledger, ctx)
    write_balance_summary = partial(_write_balance_summary, ctx)

    # 12. Accruals (Section G10)
    has_accruals = any(c in tb_codes_present for c in {"5360", "2120"})
    if not has_accruals:
        for s in ["G10 - Accruals", "G10.1 - NL Transactions"]:
            remove_sheet(s)
        if "G1 (LEAD)" in wb.sheetnames:
            wb["G1 (LEAD)"]["D25"] = 0.0
    else:
        rebuild_control_subledger("G10.1 - NL Transactions", {"5360", "5760"}, "accrual", "Accruals")
        write_balance_summary("G10 - Accruals", ["5360", "2120"], credit=True, detail_rows=list(range(15, 44)))

    # Accruals SOP (G10.2): regular running costs with no cost in a month, above all the final month.
    # Shown even without an accruals account: a missing accrual is exactly the case to catch.
    if db is not None:
        flags = accrual_review(str(engagement.id), engagement.period_end_date, tb_records, db)
        after = next((n for n in ("G10.1 - NL Transactions", "G10 - Accruals") if n in wb.sheetnames), None)
        ws = wb.create_sheet("G10.2 - Accrual review",
                             wb.sheetnames.index(after) + 1 if after else
                             (wb.sheetnames.index("H") if "H" in wb.sheetnames else len(wb.sheetnames)))
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        ws["A4"] = "Accrual review"
        ws["A4"].font = Font(name="Calibri", size=12, bold=True)
        ws["A5"] = ("Running costs that normally occur every month but have no cost in a month, above all the final "
                    "month of the year. Review only: nothing is posted. Amounts are the cost recorded in each month.")
        months = flags[0].months if flags else []
        heads = ["Account", "Code"] + [m.strftime("%b-%y") for m in months] + \
                ["Months with a cost", "Missing month(s)", "Final month missing", "Average monthly cost", "Reason", "Question for the client"]
        for c, text in enumerate(heads, 1):
            ws.cell(row=7, column=c, value=text).font = bold_font
        for r, f in enumerate(flags, 8):
            ws.cell(row=r, column=1, value=f.account)
            ws.cell(row=r, column=2, value=f.code)
            for i, v in enumerate(f.monthly):
                cell = ws.cell(row=r, column=3 + i, value=v if v else None)
                cell.number_format = "#,##0.00;(#,##0.00)"
                if not v and months[i] in f.missing:
                    # A missing month highlighted; a word, as tidy clears fills on empty cells
                    cell.value = "none"
                    cell.fill = MISSING_FILL
                    cell.alignment = Alignment(horizontal="center")
            c = 3 + len(months)
            ws.cell(row=r, column=c, value=sum(1 for v in f.monthly if v))
            ws.cell(row=r, column=c + 1, value=", ".join(m.strftime("%b-%y") for m in f.missing))
            ws.cell(row=r, column=c + 2, value="YES" if f.final_missing else "")
            ws.cell(row=r, column=c + 3, value=f.average).number_format = "#,##0.00"
            ws.cell(row=r, column=c + 4, value=f.message)
            ws.cell(row=r, column=c + 5, value=f.client_question)
            if f.final_missing:
                ws.cell(row=r, column=c + 2).font = Font(name="Calibri", size=10, bold=True, color="C00000")
        if not flags:
            ws["A8"] = "No regular running cost is missing a month."
        # Bills after the year end that relate back are checked when next year's ledger is uploaded
        from backend.app.services.ingestion.next_year import next_year_lines
        have_next = bool(next_year_lines(str(engagement.id), db))
        ws.cell(row=9 + len(flags), column=1, value=(
            "Bills dated after the year end that relate back: checked against next year's ledger (see the accruals "
            "points)." if have_next else
            "Bills dated after the year end that relate back: not checked (upload next year's ledger with the files)."))
        _supporting_lines(ctx, ws, flags, 11 + len(flags))
        ws.column_dimensions["A"].width = 40
        final = sum(1 for f in flags if f.final_missing)
        if final:
            report_notes.append(f"{final} regular cost(s) with nothing in the final month: accrual review (G10.2)")
    _accrual_schedule(ctx)


ACCRUALS = "5360"
MISSING_FILL = PatternFill("solid", fgColor="FCE4D6")      # a month with no cost on the G10.2 grid
# How each accrual journal was worked out (its basis), from its narrative
ACCRUAL_BASIS = (
    (re.compile(r"reverse|reversed|released|b/f", re.I), "Last year's accrual reversed"),
    (re.compile(r"as last year|last year", re.I), "As last year"),
    (re.compile(r"accountancy|audit|fee", re.I), "Fixed fee"),
    (re.compile(r"statement|interest", re.I), "Lender's statement / interest"),
)


PREPAYMENTS = "4900"
# How each prepayment journal was worked out, from its narrative
PREPAYMENT_BASIS = (
    (re.compile(r"reverse|reversed|release|b/f", re.I), "Last year's prepayment released"),
    (re.compile(r"as last year|last year", re.I), "As last year"),
    (re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}|period|months?\b", re.I), "Period in the bill"),
)


def _supporting_lines(ctx, ws, flags, top: int, per_account: int = 15) -> None:
    """Under the grid, each flagged account's last ledger lines of the year as supporting lines, each linked to its
    General Ledger row by formula (gl_links)."""
    from backend.app.services.workbook.gl_links import note_gl_line
    if not flags:
        return
    bold = Font(name="Calibri", size=10, bold=True)
    ws.cell(row=top, column=1, value="Supporting ledger lines (the last lines of the year on each account)").font = bold
    r = top
    for f in flags:
        lines = [tx for tx in (ctx.tx_rows or []) if str(tx[1]) == str(f.code)][-per_account:]
        if not lines:
            continue
        r += 2
        ws.cell(row=r, column=1, value=f"{f.code} {f.account}").font = bold
        r += 1
        for c, h in enumerate(("Date", "Source", "Description", "Debit", "Credit"), 1):
            ws.cell(row=r, column=c, value=h).font = bold
        for tx in lines:
            r += 1
            for c, v in ((1, tx[0]), (2, tx[4]), (3, (tx[5] or "")[:200]), (4, tx[7] or None), (5, tx[8] or None)):
                cell = ws.cell(row=r, column=c, value=v)
                if c >= 4:
                    cell.number_format = "#,##0.00;(#,##0.00)"
            note_gl_line(ctx, ws, r, tx, {1: "Date", 2: "Source", 3: "Description", 4: "Debit", 5: "Credit"})


def _accrual_schedule(ctx: BuildContext) -> None:
    """G10.3, one row per accrual: each approved journal with a line on accruals (5360), the cost
    account it is set against, its basis and amount (a new accrual a credit, a reversal a debit), the status, and the
    total checked to the ETB's journals on 5360."""
    _journal_schedule(ctx, ACCRUALS, "G10.3 - Accrual schedule", ("G10.2 - Accrual review", "G10 - Accruals"),
                      "Accrual schedule (one row per accrual journal)", "Accrued (+) / reversed (-) £",
                      "accrual", "Journals on accruals per B1-ETB (credit +)", credit=True, basis=ACCRUAL_BASIS)
    # E3.3, the same for prepayments (each with its basis and status, last year's released line by line), a
    # prepayment a debit
    _journal_schedule(ctx, PREPAYMENTS, "E3.3 - Prepayment schedule", ("E3.2 - Prepayment review", "E3.1 NL Analysis",
                                                                         "E3 - Prepayments"),
                      "Prepayment schedule (one row per prepayment journal)", "Prepaid (+) / released (-) £",
                      "prepayment", "Journals on prepayments per B1-ETB (debit +)", credit=False, basis=PREPAYMENT_BASIS)


def _journal_schedule(ctx: BuildContext, control: str, title: str, after_tabs: tuple, heading: str, amount_head: str,
                      word: str, etb_label: str, credit: bool, basis: tuple) -> None:
    """One row per approved journal with a line on the control code: the account it is set against, its basis and
    amount, the status, and the total checked to the ETB's journals on the code."""
    wb = ctx.wb
    rows: Dict[int, Dict[str, Any]] = {}
    for j in ctx.journals or []:
        no = j.get("no")
        if no is None:
            continue
        r = rows.setdefault(int(no), {"narrative": " ".join(str(j.get("narrative") or "").split()), "amount": 0.0,
                                      "other": []})
        if str(j.get("code")) == control:
            moved = float(j.get("credit") or 0) - float(j.get("debit") or 0)
            r["amount"] += moved if credit else -moved
        else:
            r["other"].append(str(j.get("code")))
    rows = {n: r for n, r in rows.items() if abs(r["amount"]) >= 0.005}
    anchor = next((n for n in after_tabs if n in wb.sheetnames), None)
    if not rows or anchor is None:
        return
    ws = wb.create_sheet(title, wb.sheetnames.index(anchor) + 1)
    ws["A1"], ws["A2"] = "=A!B2", "='Notes & Queries'!A2"
    ws["A4"] = heading
    ws["A4"].font = Font(name="Calibri", size=12, bold=True)
    heads = ["Journal", "Narrative", "Set against code", "Basis", amount_head, "Status"]
    for c, h in enumerate(heads, 1):
        ws.cell(row=6, column=c, value=h).font = ctx.bold_font
    r = 7
    for no, row in sorted(rows.items()):
        how = next((label for words, label in basis if words.search(row["narrative"])), "Estimate")
        values = [no, row["narrative"][:150], ", ".join(dict.fromkeys(row["other"])), how, round(row["amount"], 2),
                  "Approved (B2)"]
        for c, v in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if c == 5:
                cell.number_format = "#,##0.00;(#,##0.00)"
        r += 1
    plus, minus = ("K", "J") if credit else ("J", "K")
    ws.cell(row=r + 1, column=2, value=f"Total of the {word} journals").font = ctx.bold_font
    ws.cell(row=r + 1, column=5, value=f"=SUM(E7:E{r - 1})").number_format = "#,##0.00;(#,##0.00)"
    ws.cell(row=r + 2, column=2, value=etb_label)
    ws.cell(row=r + 2, column=5, value=f"=SUMIF('B1-ETB'!$A:$A,{control},'B1-ETB'!${plus}:${plus})"
                                       f"-SUMIF('B1-ETB'!$A:$A,{control},'B1-ETB'!${minus}:${minus})").number_format = "#,##0.00;(#,##0.00)"
    ws.cell(row=r + 3, column=2, value="Check: schedule v B1-ETB journals (must be nil)").font = ctx.bold_font
    ws.cell(row=r + 3, column=5, value=f"=ROUND(E{r + 1}-E{r + 2},2)")
    for c, w in zip("ABCDEF", (9, 70, 18, 30, 22, 16)):
        ws.column_dimensions[c].width = w
    if credit:
        _bills_against(ctx, ws, rows)


def _bills_against(ctx: BuildContext, ws, rows: Dict[int, Dict[str, Any]]) -> None:
    """Beside each accrual reversed this year, the bill this year that settled it and the over- (+) or
    under- (-) accrual (accrued less the bill)."""
    from datetime import date
    from backend.app.services.workbook.accrual_bills import first_bill
    end = getattr(getattr(ctx, "engagement", None), "period_end_date", None)
    if end is None:
        return
    try:
        start = date(end.year - 1, end.month, end.day) if not (end.month == 2 and end.day == 29) else date(end.year - 1, 2, 28)
    except ValueError:
        return
    start = date.fromordinal(start.toordinal() + 1)
    heads = ["Bill this year that settled it", "Bill date", "Bill £", "Over (+) / under (-) accrued £"]
    for c, h in enumerate(heads, 7):
        ws.cell(row=6, column=c, value=h).font = ctx.bold_font
    for i, (no, row) in enumerate(sorted(rows.items())):
        r = 7 + i
        if row["amount"] >= 0 or not row["other"]:
            continue                  # a new accrual, not one reversed
        bill = first_bill(getattr(ctx, "tx_rows", None), row["other"][0], row["narrative"], start, -row["amount"])
        if bill is None:
            ws.cell(row=r, column=7, value="No bill found on the account in the first four months: check it")
            continue
        when, amount, text = bill
        ws.cell(row=r, column=7, value=text)
        ws.cell(row=r, column=8, value=when).number_format = "dd/mm/yyyy"
        ws.cell(row=r, column=9, value=amount).number_format = "#,##0.00;(#,##0.00)"
        ws.cell(row=r, column=10, value=f"=ROUND(-E{r}-I{r},2)").number_format = "#,##0.00;(#,##0.00)"
    for c, w in zip("GHIJ", (45, 12, 14, 18)):
        ws.column_dimensions[c].width = w


def add_reserves_tab(ctx: BuildContext) -> None:
    """J2 reserves: profit for the year and dividends from the ETB."""
    wb, client_name, ye_str = ctx.wb, ctx.client_name, ctx.ye_str

    # Reserves (J2)
    if "J2 - Reserves" in wb.sheetnames:
        ws_j2 = wb["J2 - Reserves"]
        ws_j2["A1"] = client_name
        ws_j2["A2"] = ye_str
        ws_j2["E10"] = "=-SUMIF('B1-ETB'!$A:$A,\"<4000\",'B1-ETB'!$N:$N)"  # all P&L accounts (firm codes below 4000)
        ws_j2["E12"] = "=-SUMIFS('B1-ETB'!$N:$N,'B1-ETB'!$A:$A,\">=8010\",'B1-ETB'!$A:$A,\"<=8011\")"  # dividends paid
        # Last year's closing reserves: the opening (last year's filed TB) on the reserves codes, credit less debit, so the
        # brought forward (E8 = F14) is last year's retained earnings, not nil
        closing_ly = ("SUMIFS('B1-ETB'!$G:$G,'B1-ETB'!$A:$A,\">=8000\",'B1-ETB'!$A:$A,\"<=8099\")"
                      "-SUMIFS('B1-ETB'!$F:$F,'B1-ETB'!$A:$A,\">=8000\",'B1-ETB'!$A:$A,\"<=8099\")")
        ws_j2["F8"] = f"={closing_ly}"
        # Last year's column in full (the comparatives): last year's profit and dividends from B1-ETB's last-year
        # column (T: last year's filed TB or last year's job), the b/fwd the closing less them, so the column adds to
        # last year's closing reserves (nil profit when last year's TB was the balance sheet only)
        etb = wb["B1-ETB"] if "B1-ETB" in wb.sheetnames else None
        if etb is not None and str(etb["T6"].value or "").startswith("Last year"):
            ws_j2["F10"] = "=-SUMIF('B1-ETB'!$A:$A,\"<4000\",'B1-ETB'!$T:$T)"
            ws_j2["F12"] = "=-SUMIFS('B1-ETB'!$T:$T,'B1-ETB'!$A:$A,\">=8010\",'B1-ETB'!$A:$A,\"<=8011\")"
            ws_j2["F8"] = f"=({closing_ly})-F10-F12"
            for a in ("F8", "F10", "F12"):
                ws_j2[a].number_format = ws_j2["E10"].number_format


def _stock_tabs(ctx: BuildContext) -> None:
    """Stock: the D1 column headed for stock (the template says debtors), D2 and D2.2 headed with the client and year
    end like every tab, and on D2 the stock's movement: b/fwd (last year's filed TB), the GL movement on the stock
    codes, the closing stock journals, c/fwd per the ETB."""
    wb = ctx.wb
    if "D1 (LEAD)" in wb.sheetnames:
        wb["D1 (LEAD)"]["B6"] = "Stock and work in progress"
    for s in ("D2 - Stock Material", "D2.2 - Stock details"):
        if s in wb.sheetnames:
            wb[s]["A1"] = "=A!B2"
            wb[s]["A2"] = "='Notes & Queries'!A2"
    if "D2 - Stock Material" not in wb.sheetnames:
        return
    ws = wb["D2 - Stock Material"]
    # The stock codes' year as one T with its lines named, tied to B1-ETB, below the
    # stock count block (rows 6-15): b/f, the year's ledger lines by name, the closing stock journals, c/d
    codes = sorted({int(t.std_code) for t in ctx.tb_records if t.std_code is not None and 4300 <= int(t.std_code) <= 4310})
    if codes:
        from backend.app.services.workbook.balance_tabs.t_shape import t_account
        top = 18
        ws.cell(row=top - 1, column=1, value="Stock movement (codes 4300-4310)").font = ctx.bold_font
        # Not the codes' schedule: the D1 lead reads the stock count (D2.2), and adds the books' stock codes as
        # 'other balances with no schedule' (a stock count left nil then shows on the lead check)
        t_account(ctx, ws, codes, top=top, schedule=False)
        return
    rng = lambda sheet, col: (f"SUMIFS('{sheet}'!${col}:${col},'{sheet}'!$A:$A,\">=4300\",'{sheet}'!$A:$A,\"<=4310\")")
    top = 18
    ws.cell(row=top, column=2, value="Stock movement (codes 4300-4310)").font = ctx.bold_font
    rows = [("Balance b/fwd (last year's filed TB)", f"={rng('B1-ETB', 'F')}-{rng('B1-ETB', 'G')}"),
            ("Movement per GL", f"={rng(GL_TAB, 'G')}-{rng(GL_TAB, 'H')}"),
            # (the books' opening less last year's filed TB, and TB amounts the GL does not hold: in the ETB final too)
            ("Opening adjustment and TB not in the GL (B1-ETB O-P and S)",
             f"={rng('B1-ETB', 'O')}-{rng('B1-ETB', 'P')}+{rng('B1-ETB', 'S')}"),
            ("Closing stock journals (approved)", f"={rng('B1-ETB', 'J')}-{rng('B1-ETB', 'K')}"),
            ("Balance c/fwd per ETB", f"={rng('B1-ETB', 'N')}")]
    for i, (label, formula) in enumerate(rows, start=1):
        ws.cell(row=top + i, column=2, value=label)
        c = ws.cell(row=top + i, column=4, value=formula)
        c.number_format = '#,##0.00;(#,##0.00);"-"'
    chk = top + len(rows) + 1
    ws.cell(row=chk, column=2, value="Check: b/fwd + movement + adjustment + journals - c/fwd (must be nil)").font = ctx.bold_font
    c = ws.cell(row=chk, column=4, value=f"=ROUND(D{top + 1}+D{top + 2}+D{top + 3}+D{top + 4}-D{top + 5},2)")
    c.number_format = '#,##0.00;(#,##0.00);"-"'
    c.font = ctx.bold_font


# Companies House SIC codes of a precious metals or jewellery trade: the only clients the template's spot-price sheet fits
PRECIOUS_METAL_SIC = {"24410", "32120", "32130", "46480", "46720", "47770"}
METAL_WORDS = ("gold", "silver", "platinum", "palladium", "bullion", "jewel")


def _deals_in_precious_metals(engagement, tb_records) -> bool:
    """A precious metals or jewellery business: its SIC code, or stock accounts named for the metals."""
    import json
    profile = getattr(engagement, "profile", None)
    try:
        register = json.loads(profile.companies_house) if profile is not None and profile.companies_house else {}
    except ValueError:
        register = {}
    if {str(c) for c in (register.get("sic_codes") or [])} & PRECIOUS_METAL_SIC:
        return True
    stock = [t for t in tb_records if t.std_code is not None and 4300 <= int(t.std_code) <= 4310]
    return any(w in (t.raw_account_name or "").lower() for t in stock for w in METAL_WORDS)


def _plain_stock_details(ws, engagement, bold_font) -> None:
    """D2.2 as a plain stock list: item, quantity, unit cost and value, the total in E12 (where D2 reads it), the
    closing stock the setup holds on the first line, and the valuation rule."""
    from backend.app.services.review.setup_checks import setup_of
    for row in ws.iter_rows(min_row=4, max_row=max(ws.max_row, 25)):
        for c in row:
            if type(c).__name__ != "MergedCell":
                c.value = None
    ws["A4"] = "Stock details (count at the year end)"
    ws["A4"].font = bold_font
    for col, head in zip("BCDE", ("Item / category", "Quantity", "Unit cost £", "Value £")):
        ws[f"{col}6"] = head
        ws[f"{col}6"].font = bold_font
    entered = (setup_of(getattr(engagement, "profile", None)).get("policies") or {}).get("closing_stock")
    if entered not in (None, ""):
        ws["B7"] = "Closing stock per the client (setup)"
        ws["E7"] = float(entered)
    for r in range(7, 12):
        if r > 7 or entered in (None, ""):
            ws[f"E{r}"] = f"=IF(AND(ISNUMBER(C{r}),ISNUMBER(D{r})),C{r}*D{r},\"\")"
        ws[f"E{r}"].number_format = '#,##0.00;(#,##0.00);"-"'
    ws["B12"] = "Total closing stock"
    ws["B12"].font = bold_font
    ws["E12"] = "=SUM(E7:E11)"
    ws["E12"].font = bold_font
    ws["E12"].number_format = '#,##0.00;(#,##0.00);"-"'
    ws["B14"] = ("Valued at the lower of cost and estimated selling price less costs to complete and sell "
                 "(FRS 102 s13.4). Attach the client's stock count.")
