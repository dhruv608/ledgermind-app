"""CIS tabs: G7.2 CIS by month and G7.3 CIS HMRC Rec.

G7.2: each HMRC tax month (6th to 5th), books against HMRC: CIS deducted from subcontractors (cash basis) against the
CIS300, and CIS suffered (cash basis) against the EPS claim. G7.3: the proof of the cash basis per side (CIS in the
ledger + opening unpaid - closing unpaid = cash), the HMRC year figures entered, the T1-T10 tests with their queries,
and the CIS on invoices unpaid at the year end (timing: it goes to HMRC in the month it is paid).
Everything comes from services/cis (cash.py, hmrc.py, checks.py), as the CIS screen and the review.
"""

import json

from openpyxl.styles import Font

from backend.app.services.workbook.context import BuildContext

BOLD = Font(name="Calibri", size=10, bold=True)
TITLE = Font(name="Calibri", size=12, bold=True)
MONEY = "#,##0.00;(#,##0.00);-"
SIDE_NAMES = {"deducted": "CIS deducted from subcontractors (contractor side, owed to HMRC)",
              "suffered": "CIS suffered on sales (subcontractor side, recoverable from HMRC)"}


def _sheet(wb, title: str, after: str):
    anchor = next((n for n in (after, "G7.1 - NL Analysis", "G7-PAYE liabilities") if n in wb.sheetnames), None)
    ws = wb.create_sheet(title, wb.sheetnames.index(anchor) + 1 if anchor else len(wb.sheetnames))
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    return ws


def _money(cell, value, bold: bool = False):
    cell.value = value
    cell.number_format = MONEY
    if bold:
        cell.font = BOLD
    return cell


def add_cis_tabs(ctx: BuildContext) -> None:
    if ctx.db is None:
        return
    from backend.app.services.cis.cash import cis_cash
    from backend.app.services.cis.checks import cis_checks
    from backend.app.services.cis.hmrc import hmrc_screen
    profile = getattr(ctx.engagement, "profile", None)
    setup_cis = (json.loads(profile.setup or "{}").get("cis") or {}) if profile is not None and profile.setup else {}
    cash = cis_cash(ctx.engagement, ctx.db, setup_cis)
    if not cash.on:
        return
    screen = hmrc_screen(ctx.engagement, ctx.db, setup_cis)
    sides = {s.name: s for s in cash.sides}

    # G7.2 CIS by month
    ws = _sheet(ctx.wb, "G7.2 - CIS by month", "G7.1 - NL Analysis")
    ws["E1"] = "G7.2"
    ws["A4"] = "CIS by HMRC tax month (6th to 5th): books (cash basis) against HMRC"
    ws["A4"].font = TITLE
    heads = ["Tax month", "Tax year", "Month no.", "CIS deducted per books", "CIS deducted per CIS300", "Difference",
             "Gross per CIS300", "CIS suffered per books", "CIS claimed on EPS", "Difference"]
    for c, text in enumerate(heads, 1):
        ws.cell(row=6, column=c, value=text).font = BOLD
    months = list(screen.get("months") or [])
    for key, books in (screen.get("books_outside_months") or {}).items():
        months.append({"tax_month": key, "label": key, "tax_year": "", "month_no": "", "books": books, "hmrc": {}})
    r = 7
    for m in months:
        books, hmrc = m.get("books") or {}, m.get("hmrc") or {}
        ws.cell(row=r, column=1, value=m["label"])
        ws.cell(row=r, column=2, value=m.get("tax_year"))
        ws.cell(row=r, column=3, value=m.get("month_no"))
        _money(ws.cell(row=r, column=4), books.get("deducted") or 0)
        _money(ws.cell(row=r, column=5), hmrc.get("deducted"))
        _money(ws.cell(row=r, column=6), f'=IF(E{r}="","",ROUND(D{r}-E{r},2))')
        _money(ws.cell(row=r, column=7), hmrc.get("gross"))
        _money(ws.cell(row=r, column=8), books.get("suffered") or 0)
        _money(ws.cell(row=r, column=9), hmrc.get("claimed_eps"))
        _money(ws.cell(row=r, column=10), f'=IF(I{r}="","",ROUND(H{r}-I{r},2))')
        r += 1
    ws.cell(row=r, column=1, value="Total").font = BOLD
    for c in range(4, 11):
        col = "ABCDEFGHIJ"[c - 1]
        _money(ws.cell(row=r, column=c), f"=SUM({col}7:{col}{r - 1})", bold=True)
    ws.cell(row=r + 2, column=1, value=(
        "Books are on a cash basis: CIS belongs to the month the subcontractor was paid / the customer paid, not the "
        "invoice date. HMRC figures are those entered on the CIS screen (CIS300 returns, EPS); blank = not entered."))
    for col, width in zip("ABCDEFGHIJ", (14, 10, 10, 16, 16, 14, 16, 16, 16, 14)):
        ws.column_dimensions[col].width = width

    # G7.3 CIS HMRC Rec
    ws = _sheet(ctx.wb, "G7.3 - CIS HMRC Rec", "G7.2 - CIS by month")
    ws["E1"] = "G7.3"
    ws["A4"] = "CIS reconciliation: books to HMRC"
    ws["A4"].font = TITLE
    r = 6
    ws.cell(row=r, column=1, value="A  Cash basis per side").font = BOLD
    r += 1
    for name in ("deducted", "suffered"):
        side = sides.get(name)
        if side is None:
            continue
        ws.cell(row=r, column=1, value=SIDE_NAMES[name]).font = BOLD
        r += 1
        for text, value in (("CIS in the ledger this year (invoice basis)", side.invoice_basis),
                            ("Add: CIS on last year's invoices paid this year (opening unpaid)", side.opening_unpaid),
                            ("Less: CIS on invoices unpaid at the year end (closing unpaid)", -side.closing_unpaid),
                            ("Less: journals (the reviewer decides)", -sum(j.amount for j in side.journals))):
            ws.cell(row=r, column=2, value=text)
            _money(ws.cell(row=r, column=4), round(value, 2))
            r += 1
        ws.cell(row=r, column=2, value="Cash basis (to HMRC by tax month, G7.2)").font = BOLD
        _money(ws.cell(row=r, column=4), side.cash_total, bold=True)
        r += 1
        ws.cell(row=r, column=2, value="Proof difference (must be nil)")
        _money(ws.cell(row=r, column=4), side.proof_difference)
        r += 1
        if side.settled_total:
            ws.cell(row=r, column=2, value="CIS recovered from / paid to HMRC (not CIS of the year)")
            _money(ws.cell(row=r, column=4), side.settled_total)
            r += 1
        for e in side.exceptions[:6]:
            ws.cell(row=r, column=2, value=f"Exception: {e}"[:250])
            r += 1
        r += 1

    year = screen.get("year") or {}
    if any(year.get(k) not in (None, "") for k in ("balance_bf", "balance_cf", "repayment_amount")):
        ws.cell(row=r, column=1, value="B  HMRC PAYE / CIS account (entered from the HMRC statement)").font = BOLD
        r += 1
        for text, key in (("Balance brought forward per HMRC", "balance_bf"), ("Balance carried forward per HMRC", "balance_cf"),
                          ("Repayment received", "repayment_amount")):
            ws.cell(row=r, column=2, value=text)
            _money(ws.cell(row=r, column=4), year.get(key))
            r += 1
        r += 1

    result = cis_checks(ctx.engagement, ctx.db, setup_cis)
    ws.cell(row=r, column=1, value="C  Tests against HMRC").font = BOLD
    r += 1
    for c, text in enumerate(["Test", "Name", "Result", "Summary", "Query to", "Query"], 1):
        ws.cell(row=r, column=c, value=text).font = BOLD
    r += 1
    for chk in result.get("checks") or []:
        for c, value in enumerate((chk["ref"], chk["name"], chk["status"], chk["summary"], chk.get("query_to"),
                                   chk.get("query")), 1):
            ws.cell(row=r, column=c, value=(str(value)[:300] if value else None))
        r += 1
    r += 1

    unpaid = [(name, i) for name in ("deducted", "suffered") if sides.get(name) for i in sides[name].unpaid]
    if unpaid:
        ws.cell(row=r, column=1, value="D  CIS on invoices unpaid at the year end (timing: HMRC in the month paid)").font = BOLD
        r += 1
        for c, text in enumerate(["Side", "Contact", "Reference", "CIS £"], 1):
            ws.cell(row=r, column=c, value=text).font = BOLD
        r += 1
        for name, i in unpaid:
            ws.cell(row=r, column=1, value=name)
            ws.cell(row=r, column=2, value=i.contact)
            ws.cell(row=r, column=3, value=i.reference)
            _money(ws.cell(row=r, column=4), i.amount)
            r += 1
    for col, width in zip("ABCDEF", (12, 60, 12, 50, 12, 70)):
        ws.column_dimensions[col].width = width
    failing = [c for c in result.get("checks") or [] if c["status"] == "FAIL"]
    if failing:
        ctx.report_notes.append(f"CIS: {len(failing)} test(s) against HMRC failing (G7.3)")
