"""Notes & Queries, the notes the app can write from its own figures: the bank accounts as a table of books v
reconciliation balance, and the profit and loss comparatives, this year v last year by code with the variance. Added
after the general notes the core tabs write (rows 6 to 12). FRS 102 s3 needs
last year's comparatives; the bank figures are the Balance sheet tab's (services/reconciliation/control_accounts.py)."""

from typing import Dict

from openpyxl.styles import Font

MONEY = "#,##0.00;(#,##0.00);-"
BOLD = Font(bold=True)
FIRST_ROW = 16                       # the general notes take rows 6 to 14
BIG_CHANGE = (1000.0, 0.20)          # a P&L line that moved by both £1,000 and 20%: a comment


def add_notes(ctx) -> None:
    wb, db, engagement, tb_records = ctx.wb, ctx.db, ctx.engagement, ctx.tb_records
    if db is None or "Notes & Queries" not in wb.sheetnames:
        return
    ws = wb["Notes & Queries"]
    # Row 14: the opening and movement note (core tabs), when the ETB reads the movement from the ledger
    row, sr = FIRST_ROW, 6 if ws.cell(row=14, column=2).value else 5
    row, sr = _extraction_note(ws, row, sr, engagement, tb_records, db)
    row, sr = _bank_note(ws, row, sr, engagement, db)
    row, sr = _area_notes(ws, row, sr, engagement, tb_records, db)
    _pl_note(ws, row, sr, engagement, tb_records, db)


def _money(cell):
    cell.number_format = MONEY
    return cell


def _extraction_note(ws, row: int, sr: int, engagement, tb_records, db):
    """The extraction checks (C1-C11, setup/extraction_checks.py) as on the Data check: a WARNING keeps the
    workbook a draft until it is cleared or explained."""
    from backend.app.services.bank_only.books import is_books_client
    from backend.app.services.setup.extraction_checks import extraction_items
    from backend.app.services.setup.profile_service import ProfileService
    if is_books_client(engagement):
        return row, sr
    try:
        items = extraction_items(db, engagement, list(tb_records), ProfileService.get_or_create_profile(db, engagement.id))
    except Exception:
        return row, sr
    if not items:
        return row, sr
    ws.cell(row=row, column=1, value=sr)
    ws.cell(row=row, column=2, value="Data checks (opening, movement, TB)").font = BOLD
    ws.cell(row=row, column=4, value="Last year's filed TB, the general ledger and the TB against each other. "
                                     "'To clear' keeps the workbook a draft until explained.")
    row += 1
    for item in items:
        ws.cell(row=row, column=4, value=item.label)
        ws.cell(row=row, column=5, value="OK" if item.status == "OK" else "To clear")
        ws.cell(row=row, column=6, value=item.detail)
        if item.status != "OK":
            ws.cell(row=row, column=5).font = Font(bold=True, color="C00000")
        row += 1
    return row + 1, sr + 1


def _bank_note(ws, row: int, sr: int, engagement, db):
    from backend.app.services.reconciliation.control_accounts import reconciliations
    try:
        banks = [r for r in reconciliations(engagement, db) if r.area == "Bank"]
    except Exception:
        banks = []
    if not banks:
        return row, sr
    ws.cell(row=row, column=1, value=sr)
    ws.cell(row=row, column=2, value="Bank accounts").font = BOLD
    ws.cell(row=row, column=4, value=f"{len(banks)} bank account(s): the books against the bank statement at the year "
                                     f"end. A difference is explained before the balance is relied on.")
    row += 1
    for col, head in zip(range(4, 9), ("Bank", "Balance in the books £", "Per the statement £", "Difference £", "Comment")):
        ws.cell(row=row, column=col, value=head).font = BOLD
    for i, b in enumerate(banks, 1):
        row += 1
        ws.cell(row=row, column=3, value=f"{sr}.{i}")
        ws.cell(row=row, column=4, value=b.account)
        _money(ws.cell(row=row, column=5, value=round(b.books, 2)))
        if b.other is not None:
            _money(ws.cell(row=row, column=6, value=round(b.other, 2)))
            _money(ws.cell(row=row, column=7, value=f"=E{row}-F{row}"))
        comment = b.note or ("Agrees to the statement" if b.difference is not None and abs(b.difference) < 1
                             else "Statement balance not entered" if b.other is None else "Difference to explain")
        ws.cell(row=row, column=8, value=comment)
    return row + 2, sr + 1


def _gbp(v: float) -> str:
    return f"£{abs(v):,.2f}" + (" Cr" if v < -0.005 else " Dr" if v > 0.005 else "")


def _area_notes(ws, row: int, sr: int, engagement, tb_records, db):
    """One note per balance sheet account the Balance sheet tab compares (bank has its own table): opening, the year's
    movement, approved journals and the closing balance, then what it agrees to (per books, expected, the
    difference), written as a note reads ('the opening balance of trade debtors was ..., the closing ...')."""
    from backend.app.services.reconciliation.control_accounts import reconciliations
    from backend.app.services.review import last_year as ly
    from backend.app.services.tax.ct_computation import final_balances
    try:
        rows = [r for r in reconciliations(engagement, db) if r.area != "Bank" and r.codes]
    except Exception:
        return row, sr
    after = final_balances(engagement.id, tb_records, db)
    has_opening = any(t.opening_amount is not None for t in tb_records)
    prior = {} if has_opening else ly.prior_balances_by_code(engagement, db)
    for r in rows:
        codes = set(r.codes)
        tb = [t for t in tb_records if t.std_code in codes]
        books = round(sum(float(t.net_amount or 0) for t in tb), 2)
        closing = round(sum(after.get(c, 0.0) for c in codes), 2)
        opening = (round(sum(float(t.opening_amount or 0) for t in tb), 2) if has_opening
                   else round(sum(prior.get(c, 0.0) for c in codes), 2))
        journals = round(closing - books, 2)
        if max(abs(opening), abs(closing), abs(books)) < 0.005:
            continue
        story = (f"Opening balance {_gbp(opening)}; movement in the year {_gbp(books - opening)}"
                 + (f"; approved journals {_gbp(journals)}" if abs(journals) >= 0.005 else "")
                 + f"; closing balance {_gbp(closing)}.")
        if r.other is None:
            check = f" To agree to: {r.compared_with} (not in yet)."
        elif r.difference is not None and abs(r.difference) < 1:
            check = f" Agrees to {r.compared_with}."
        else:
            check = (f" Per {r.compared_with}: £{abs(r.other):,.2f}; difference £{abs(r.difference or 0):,.2f} to "
                     f"explain.")
        ws.cell(row=row, column=1, value=sr)
        ws.cell(row=row, column=2, value=r.account).font = BOLD
        # The row's own note only beside a difference (when not compared it is the screen's 'type its figure' hint)
        extra = f" {r.note}" if r.note and r.other is not None and abs(r.difference or 0) >= 1 else ""
        ws.cell(row=row, column=4, value=story + check + extra)
        row, sr = row + 2, sr + 1
    return row, sr


def _pl_note(ws, row: int, sr: int, engagement, tb_records, db) -> None:
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.review import last_year as ly
    from backend.app.services.tax.ct_computation import final_balances
    chart = ChartLookup(db)
    # Last year's P&L: last year's job in the app (its final figures, after its approved journals), else last year's
    # TB when it has P&L lines (a closing TB of balance sheet accounts only has none: every line would read 'new')
    last: Dict[int, float] = {}
    source = ""
    try:
        job = ly.last_year_job(engagement, db)
        if job is not None:
            from backend.app.models.database import TBRecord
            last_tb = db.query(TBRecord).filter(TBRecord.engagement_id == job.id).all()
            last, source = final_balances(job.id, last_tb, db), f"last year's job, year ended {job.period_end_date:%d/%m/%Y}"
        else:
            last, source = ly.prior_balances_by_code(engagement, db), "last year's TB"
    except Exception:
        last = {}
    last = {c: v for c, v in last.items() if chart.is_pl(c)}
    this = final_balances(engagement.id, tb_records, db)
    codes = sorted(c for c in set(this) | set(last)
                   if chart.is_pl(c) and (abs(this.get(c, 0.0)) >= 0.005 or abs(last.get(c, 0.0)) >= 0.005))
    if not codes:
        return
    ws.cell(row=row, column=1, value=sr)
    ws.cell(row=row, column=2, value="Profit and loss comparatives").font = BOLD
    ws.cell(row=row, column=4, value=(f"This year against last year ({source}), code by code, after approved journals "
                                      f"(debits positive). Lines that moved by more than £1,000 and 20% are commented."
                                      if last else "This year only: last year's P&L is not in the app (the TB "
                                                   "uploaded for last year holds the balance sheet only). Add last "
                                                   "year's figures from the prior accounts to compare."))
    row += 1
    for col, head in zip(range(3, 9), ("Code", "Account", "This year £", "Last year £", "Variance £", "Comment")):
        ws.cell(row=row, column=col, value=head).font = BOLD
    first = row + 1
    for c in codes:
        row += 1
        now, before = round(this.get(c, 0.0), 2), round(last.get(c, 0.0), 2)
        ws.cell(row=row, column=3, value=c)
        ws.cell(row=row, column=4, value=chart.name(c))
        _money(ws.cell(row=row, column=5, value=now))
        if last:
            _money(ws.cell(row=row, column=6, value=before))
            _money(ws.cell(row=row, column=7, value=f"=E{row}-F{row}"))
            change = abs(now) - abs(before)
            if abs(change) >= BIG_CHANGE[0] and (not before or abs(change) / abs(before) >= BIG_CHANGE[1]):
                what = ("new this year" if not before else "none this year" if not now else
                        f"{'up' if change > 0 else 'down'} {abs(change) / abs(before):.0%}")
                ws.cell(row=row, column=8, value=f"{what}: explain")
    row += 1
    ws.cell(row=row, column=4, value="Profit (-) / loss for the year before tax").font = BOLD
    pre_tax = [r for r, c in enumerate(codes, first) if chart.is_pre_tax_pl(c)]
    if pre_tax:
        sums = "+".join(f"E{r}" for r in pre_tax)
        _money(ws.cell(row=row, column=5, value=f"={sums}")).font = BOLD
        if last:
            _money(ws.cell(row=row, column=6, value="=" + "+".join(f"F{r}" for r in pre_tax))).font = BOLD
            _money(ws.cell(row=row, column=7, value=f"=E{row}-F{row}")).font = BOLD
