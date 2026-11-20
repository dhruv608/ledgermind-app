"""K0.2 GL scrutiny: what the accountant did on the GL scrutiny screen (Accounts tab), as a summary and error report:
per code, how many ledger lines were read, moved and asked about; every
line moved to another code (wrong code -> right code, with its journal); every line asked about, with the client's
answer from the Queries tab; and the flagged lines nobody has checked yet. The figures come from services/papers/scrutiny.py.
(The template's H is corporation tax, so the sheet sits in K, the profit and loss review, beside K0 and K0.1.)"""

from openpyxl.styles import Font, PatternFill

from backend.app.services.workbook.context import BuildContext

TITLE = "K0.2 - GL scrutiny"
BOLD = Font(name="Calibri", size=10, bold=True)
HEAD = Font(name="Calibri", size=11, bold=True)
HEAD_FILL = PatternFill("solid", fgColor="E2EFDA")
MONEY = "#,##0.00;(#,##0.00);-"
STATUS = {"OPEN": "Open", "ANSWERED": "Answered", "CLEARED": "Done"}


def add_scrutiny_tab(ctx: BuildContext) -> None:
    if ctx.db is None:
        return
    from backend.app.services.papers.scrutiny import report
    data = report(ctx.engagement, ctx.db)
    if not data["accounts"]:
        return                                   # no ledger lines: nothing was there to read
    wb = ctx.wb
    after = next((n for n in ("K0.1 - Restaurant review", "K0 - Pattern review", "K") if n in wb.sheetnames), None)
    ws = wb.create_sheet(TITLE, wb.sheetnames.index(after) + 1 if after else len(wb.sheetnames))
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    ws["H1"] = "K0.2"
    ws["A4"] = "GL scrutiny: the ledger read line by line"
    ws["A4"].font = Font(name="Calibri", size=12, bold=True)
    ws["A5"] = ("Each ledger line was marked OK, moved to the right code (a journal, approved on B2) or asked about "
                "(a client query). Flagged lines are the ones worth reading first: asset words, unusual payments, "
                "related parties, the opposite side of the account, round sums.")
    row = 7

    def heading(text: str) -> None:
        nonlocal row
        ws.cell(row=row, column=1, value=text).font = HEAD
        row += 1

    def columns(names) -> None:
        nonlocal row
        for c, text in enumerate(names, 1):
            cell = ws.cell(row=row, column=c, value=text)
            cell.font = BOLD
            cell.fill = HEAD_FILL
        row += 1

    def put(values, money_cols=(), date_col=None) -> None:
        nonlocal row
        for c, v in enumerate(values, 1):
            cell = ws.cell(row=row, column=c, value=v)
            if c in money_cols:
                cell.number_format = MONEY
            if c == date_col and v is not None:
                cell.number_format = "dd/mm/yyyy"
        row += 1

    def code(c) -> str:
        return "-" if c is None else str(c).zfill(4)

    # 1. Summary per code
    heading("1. Summary by account code")
    columns(["Code", "Account", "Lines", "Checked", "Moved", "Asked", "Flagged, not checked", "Ledger total £"])
    first = row
    for a in data["accounts"]:
        put([code(a["code"]), a["name"], a["lines"], a["checked"], a["moved"], a["asked"], a["flagged"], a["total"]],
            money_cols=(8,))
    ws.cell(row=row, column=1, value="Total").font = BOLD
    for c, col in ((3, "C"), (4, "D"), (5, "E"), (6, "F"), (7, "G")):
        ws.cell(row=row, column=c, value=f"=SUM({col}{first}:{col}{row - 1})").font = BOLD
    row += 2

    # 2. Error report: lines on the wrong code
    heading("2. Error report: lines moved to the right code")
    columns(["Date", "Description", "Amount £", "Was on", "Moved to", "Journal", "Journal status"])
    for m in data["moved"]:
        put([m["date"], m["description"][:250], m["amount"], f"{code(m['code'])} {m['account']}",
             f"{code(m['to_code'])} {m['to_account']}", m["journal"],
             {"APPROVED": "Approved", "REJECTED": "Rejected"}.get(m["journal_status"], "Proposed")],
            money_cols=(3,), date_col=1)
    if not data["moved"]:
        put(["No line was moved."])
    row += 1

    # 3. Lines asked about
    heading("3. Lines asked about (client queries)")
    columns(["Date", "Description", "Amount £", "Account", "Question", "Answer", "Status"])
    for q in data["asked"]:
        put([q["date"], q["description"][:250], q["amount"], f"{code(q['code'])} {q['account']}", q["question"],
             q["answer"] or "-", STATUS.get(q["status"], q["status"])], money_cols=(3,), date_col=1)
    if not data["asked"]:
        put(["No line was asked about."])
    row += 1

    # 4. Flagged lines still to check
    heading("4. Flagged lines not checked yet")
    columns(["Date", "Description", "Amount £", "Account", "Why flagged"])
    for f in data["flagged"]:
        put([f["date"], f["description"][:250], f["amount"], f"{code(f['code'])} {f['account']}", f["flags"]],
            money_cols=(3,), date_col=1)
    if not data["flagged"]:
        put(["None: every flagged line has been checked."])

    for col, width in zip("ABCDEFGH", (12, 50, 14, 34, 34, 40, 14, 14)):
        ws.column_dimensions[col].width = width
