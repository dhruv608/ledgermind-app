"""PY-TB and OBD: last year's trial balance as it came in, with the firm code beside each account, and the opening
balances per the books against last year's closing, code by code, with why they differ and the reserves brought
forward at the foot. The comparison is the one the Opening balances area shows (review/opening_balances.py), not worked out again."""

from backend.app.services.workbook.balance_tabs import BOLD, _money, _new_sheet

PY_TB = "PY-TB - Last year's TB"
CY_TB = "CY-TB - This year's TB"
OBD = "OBD - Opening balances"


def add_opening_tabs(ctx) -> None:
    db, engagement, tb_records = ctx.db, ctx.engagement, ctx.tb_records
    if db is None:
        return
    from backend.app.services.review import last_year as ly
    try:
        source, lines = ly._from_files(engagement, db)
    except Exception:
        source, lines = "", []
    if lines:
        _last_year_tb(ctx, source, lines)
    _client_tb(ctx, tb_records)
    _opening_balances(ctx, db, engagement, tb_records)


def _client_tb(ctx, tb_records) -> None:
    """CY-TB: this year's trial balance as the client gave it, in the TTB's
    layout, before any mapping or journal. Lines the app adds itself (last year's balance on an account the client no
    longer has) are not the client's and are left out."""
    rows = [t for t in tb_records if getattr(t, "match_source", None) != "ROLL_FORWARD"
            and (abs(float(t.debit_amount or 0)) >= 0.005 or abs(float(t.credit_amount or 0)) >= 0.005)]
    if not rows:
        return
    ws = _new_sheet(ctx, CY_TB, ["TTB", "B2-Journals", "B1-ETB"])
    ws["D1"] = "CY-TB"
    ws["A4"] = "This year's trial balance, as the client gave it"
    ws["A4"].font = BOLD
    for col, head in zip("ABCDEF", ("Code", "Account", "Debit £", "Credit £", "Balance £", "Code name")):
        ws[f"{col}6"] = head
        ws[f"{col}6"].font = BOLD
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["F"].width = 40
    name_of = getattr(ctx, "account_name", None)
    r = 7
    for t in rows:
        ws[f"A{r}"] = t.std_code
        ws[f"B{r}"] = t.raw_account_name
        if abs(float(t.debit_amount or 0)) >= 0.005:
            _money(ws.cell(row=r, column=3, value=round(float(t.debit_amount), 2)))
        if abs(float(t.credit_amount or 0)) >= 0.005:
            _money(ws.cell(row=r, column=4, value=round(float(t.credit_amount), 2)))
        _money(ws.cell(row=r, column=5, value=f"=C{r}-D{r}"))
        if t.std_code is not None and name_of is not None:
            try:
                ws[f"F{r}"] = name_of(t.std_code)
            except Exception:
                pass
        r += 1
    ws[f"B{r}"] = "Total"
    ws[f"B{r}"].font = BOLD
    _money(ws.cell(row=r, column=3, value=f"=SUM(C7:C{r - 1})"), bold=True, total=True)
    _money(ws.cell(row=r, column=4, value=f"=SUM(D7:D{r - 1})"), bold=True, total=True)
    ws[f"B{r + 1}"] = "Check: debits less credits (must be nil)"
    _money(ws.cell(row=r + 1, column=3, value=f"=ROUND(C{r}-D{r},2)"))


def _last_year_tb(ctx, source: str, lines) -> None:
    ws = _new_sheet(ctx, PY_TB, ["TTB", "B2-Journals", "B1-ETB"])
    ws["D1"] = "PY-TB"
    ws["A4"] = f"Last year's trial balance ({source})"
    ws["A4"].font = BOLD
    # The TTB's layout: code, client account, Dr, Cr, balance and the code's name
    for col, head in zip("ABCDEF", ("Code", "Account", "Debit £", "Credit £", "Balance £", "Code name")):
        ws[f"{col}6"] = head
        ws[f"{col}6"].font = BOLD
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["F"].width = 40
    name_of = getattr(ctx, "account_name", None)
    r = 7
    for line in lines:
        ws[f"A{r}"] = line.code
        ws[f"B{r}"] = line.name
        if line.amount >= 0:
            _money(ws.cell(row=r, column=3, value=round(line.amount, 2)))
        else:
            _money(ws.cell(row=r, column=4, value=round(-line.amount, 2)))
        _money(ws.cell(row=r, column=5, value=f"=C{r}-D{r}"))
        if line.code is not None and name_of is not None:
            try:
                ws[f"F{r}"] = name_of(line.code)
            except Exception:
                pass
        r += 1
    ws[f"B{r}"] = "Total"
    ws[f"B{r}"].font = BOLD
    _money(ws.cell(row=r, column=3, value=f"=SUM(C7:C{r - 1})"), bold=True, total=True)
    _money(ws.cell(row=r, column=4, value=f"=SUM(D7:D{r - 1})"), bold=True, total=True)
    # Last year's TB must balance (red)
    ws[f"B{r + 1}"] = "Check: debits less credits (must be nil)"
    _money(ws.cell(row=r + 1, column=3, value=f"=ROUND(C{r}-D{r},2)"))
    _opens_on(ctx, ws, lines)
    link_etb(ctx.wb, ws, lines)


def _opens_on(ctx, ws, lines) -> None:
    """PY-TB column G: the code each line opens on this year in B1-ETB (balance sheet codes;
    last year's profit and the reserve's movements in 8000; additions and depreciation charge in the cost and
    depreciation brought forward), the one rule B1-ETB's opening is made by (review/extraction.opening_code)."""
    if getattr(ctx, "db", None) is None:
        return
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.review.extraction import opening_code
    chart = ChartLookup(ctx.db)
    ws["G6"], ws["G6"].font = "Opens on (B1-ETB)", BOLD
    ws.column_dimensions["G"].width = 16
    for r, line in enumerate(lines, 7):
        if isinstance(line.code, int):
            ws[f"G{r}"] = int(opening_code(line.code, chart))


def link_etb(wb, py, lines) -> int:
    """B1-ETB's opening (F / G) and last year (T) as formulas on this tab ('SUMIFS(PY-TB!Balance,
    PY-TB!Final code, code)'), so a click on the ETB lands on last year's lines. Only where this tab gives the very
    figures B1-ETB shows (to the penny, every code): the ETB's last year can come from last year's job in the app, after
    its journals, and then stays as it is. Returns how many columns were linked (0-2)."""
    if "B1-ETB" not in wb.sheetnames:
        return 0
    etb = wb["B1-ETB"]
    from backend.app.services.workbook.etb_rows import data_rows
    rows = data_rows(etb)
    if not rows:
        return 0
    ref = "'" + py.title.replace("'", "''") + "'"
    by_code, by_open = {}, {}
    for i, line in enumerate(lines, 7):
        if not isinstance(line.code, int):
            continue
        by_code[str(line.code)] = by_code.get(str(line.code), 0.0) + float(line.amount)
        opens = py.cell(row=i, column=7).value
        if opens is not None:
            by_open[str(opens)] = by_open.get(str(opens), 0.0) + float(line.amount)

    def num(v):
        return float(v) if isinstance(v, (int, float)) else 0.0

    def agrees(shown, wanted) -> bool:
        codes = {str(etb.cell(row=r, column=1).value) for r in rows}
        return (all(abs(shown[r] - wanted.get(str(etb.cell(row=r, column=1).value), 0.0)) < 0.005 for r in rows)
                and all(c in codes for c, v in wanted.items() if abs(v) >= 0.005))
    linked = 0
    # The opening: only the ledger chain's (F6 names last year's filed TB); a books client's opening is its own
    if str(etb["F6"].value or "").startswith("Opening (last year's filed TB)") and by_open:
        shown = {r: num(etb.cell(row=r, column=6).value) - num(etb.cell(row=r, column=7).value) for r in rows}
        if agrees(shown, by_open):
            for r in rows:
                sumifs = f"ROUND(SUMIFS({ref}!$E:$E,{ref}!$G:$G,$A{r}),2)"
                etb.cell(row=r, column=6, value=f"=MAX(0,{sumifs})")
                etb.cell(row=r, column=7, value=f"=MAX(0,-{sumifs})")
            linked += 1
    # Last year, every code (the comparatives): T when B1-ETB has it
    if str(etb["T6"].value or "").startswith("Last year") and by_code:
        shown = {r: num(etb.cell(row=r, column=20).value) for r in rows}
        if agrees(shown, by_code):
            for r in rows:
                etb.cell(row=r, column=20, value=f"=ROUND(SUMIFS({ref}!$E:$E,{ref}!$A:$A,$A{r}),2)")
            linked += 1
    return linked


def _opening_balances(ctx, db, engagement, tb_records) -> None:
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.review.opening_balances import opening_points
    table = {"source": "", "rows": []}
    # The review's comparison, run inside a savepoint so nothing it touches is kept
    savepoint = db.begin_nested()
    try:
        _points, _journals, compared = opening_points(engagement, tb_records, ChartLookup(db), db, [1], table=table)
    except Exception:
        compared = False
    finally:
        savepoint.rollback()
    if not compared or not table.get("rows"):
        return
    ws = _new_sheet(ctx, OBD, [PY_TB, "TTB", "B2-Journals", "B1-ETB"])
    ws["D1"] = "OBD"
    ws["A4"] = f"Opening balances per the books v last year's closing ({table.get('source') or 'last year'})"
    ws["A4"].font = BOLD
    for col, head in zip("ABCDEF", ("Code", "Account", "Opening per books £", "Last year's closing £",
                                    "Difference £", "Why")):
        ws[f"{col}6"] = head
        ws[f"{col}6"].font = BOLD
    ws.column_dimensions["F"].width = 44
    r = 7
    for row in table["rows"]:
        ws[f"A{r}"] = row["code"]
        ws[f"B{r}"] = row["name"]
        _money(ws.cell(row=r, column=3, value=row["books"]))
        _money(ws.cell(row=r, column=4, value=row["last_year"]))
        _money(ws.cell(row=r, column=5, value=f"=C{r}-D{r}"))
        ws[f"F{r}"] = row["cause"]
        r += 1
    r += 1
    ws[f"B{r}"] = "Reserves brought forward"
    ws[f"B{r}"].font = BOLD
    _money(ws.cell(row=r, column=3, value=table.get("books_bf")), bold=True, total=True)
    _money(ws.cell(row=r, column=4, value=table.get("last_year_bf")), bold=True, total=True)
    _money(ws.cell(row=r, column=5, value=f"=C{r}-D{r}"), bold=True, total=True)
    if abs(table.get("gap") or 0) >= 1:
        ws[f"F{r}"] = f"Explained above: {table.get('explained', 0):,.2f}"
    ws[f"B{r + 2}"] = ("Every balance at the start of the year should equal last year's final closing balance; "
                       "a difference is posted or explained before the year is relied on.")
