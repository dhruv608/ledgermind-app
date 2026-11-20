"""G6.4 Subcontractors: every individual paid through wages, subcontractor / labour or labour-type cost accounts, as a
subcontractor v employee sheet (on the payroll?, totals by kind of account, months paid, the flag / question
for the client). The figures and flags come from services/review/subcontractors.py, as the review's U-SUB points."""

from openpyxl.styles import Font

from backend.app.services.workbook.context import BuildContext

TITLE = "G6.4 - Subcontractors"
BOLD = Font(name="Calibri", size=10, bold=True)
MONEY = "#,##0.00;(#,##0.00);-"


def add_subcontractor_tab(ctx: BuildContext) -> None:
    if ctx.db is None:
        return
    from backend.app.services.review.subcontractors import individuals
    found = individuals(ctx.engagement, ctx.tb_records, ctx.db)
    people = found["people"]
    subs = found.get("subcontractors") or []
    if not people and not subs:
        return
    wb = ctx.wb
    after = next((n for n in ("G6.3 - Avg. No. of Employee", "G6.2 - Payroll summary", "G6 - Net Wages") if n in wb.sheetnames), None)
    ws = wb.create_sheet(TITLE, wb.sheetnames.index(after) + 1 if after else len(wb.sheetnames))
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    ws["E1"] = "G6.4"
    ws["A4"] = "Subcontractor v employee: individuals paid through wages, subcontractor and cost accounts"
    ws["A4"].font = Font(name="Calibri", size=12, bold=True)
    ws["A5"] = ("Payee = the contact on the ledger line; a person = first name and surname, no company words. On the "
                "payroll = shares two name parts or the surname with someone on the payroll report"
                + ("." if found["payroll_names"] else " (the payroll report gives no names, so it cannot be confirmed)."))
    total = 6
    if not people:
        ws["A5"] = "No individual (a first name and surname) was paid through the wages or subcontractor accounts."
    if people:
        total = _people_block(ws, people)
    if subs:
        _paid_block(ws, subs, total + 4 if people else 7, found["has_cis"], found.get("subcontractor_accounts") or [])
    for col, width in zip("ABCDEFGHIJ", (30, 18, 14, 10, 12, 14, 16, 16, 40, 60)):
        ws.column_dimensions[col].width = width
    flagged = sum(1 for p in people if any(f[:2] in ("A:", "B:", "C:", "D:") for f in p.flags))
    if flagged:
        ctx.report_notes.append(f"{flagged} individual(s) to ask the client about: subcontractor or employee (G6.4)")


def _people_block(ws, people) -> int:
    heads = ["Individual (payee)", "On payroll?", "Total paid £", "Payments", "Months paid", "Via wages £",
             "Via subcontractor / labour £", "Via other cost accounts £", "Accounts", "Flag / question for the client"]
    for c, text in enumerate(heads, 1):
        ws.cell(row=7, column=c, value=text).font = BOLD
    for r, p in enumerate(people, 8):
        ws.cell(row=r, column=1, value=p.name)
        ws.cell(row=r, column=2, value="Unknown (no names)" if p.on_payroll is None else "Yes" if p.on_payroll else "No")
        for c, v in ((3, p.total), (6, p.via_wages), (7, p.via_subcontractor), (8, p.via_other)):
            ws.cell(row=r, column=c, value=round(v, 2)).number_format = MONEY
        ws.cell(row=r, column=4, value=p.payments)
        ws.cell(row=r, column=5, value=len(p.months))
        ws.cell(row=r, column=9, value=", ".join(sorted(p.accounts))[:200])
        ws.cell(row=r, column=10, value="; ".join(p.flags) or "-")
    total = 8 + len(people)
    ws.cell(row=total, column=1, value="Total").font = BOLD
    for c in (3, 6, 7, 8):
        col = "CDEFGH"[c - 3]
        cell = ws.cell(row=total, column=c, value=f"=SUM({col}8:{col}{total - 1})")
        cell.number_format = MONEY
        cell.font = BOLD
    ws.cell(row=total + 2, column=1, value=(
        "Flags: A on the payroll and paid as a subcontractor; B paid as a subcontractor in 6+ months (employment "
        "status, CIS); C paid through wages but not on the payroll; D paid in 3+ months (£1,000+) through cost "
        "accounts. Each is a question for the client, not a conclusion."))
    return total + 2


def _paid_block(ws, subs, top: int, has_cis: bool, accounts) -> None:
    """Each payee on the subcontractor accounts (people and companies): gross, CIS deducted, net."""
    ws.cell(row=top, column=1, value="Subcontractors paid: gross, CIS deducted and net").font = Font(name="Calibri", size=12, bold=True)
    ws.cell(row=top + 1, column=1, value=(
        "From the subcontractor / labour accounts in the ledger; CIS deducted = the ledger's CIS deducted / payable "
        "lines naming the same payee. Agree each to the CIS300 monthly returns and the CIS statements given (G7.2)."
        + ("" if has_cis else " The ledger has no CIS account: if the work is construction, ask the client whether "
                              "CIS applies and the subcontractors' verification status.")))
    heads = ["Subcontractor (payee)", "Payments", "Gross paid £", "CIS deducted £", "Net paid £", "CIS rate",
             "Not labour: reanalyse"]
    for c, text in enumerate(heads, 1):
        ws.cell(row=top + 3, column=c, value=text).font = BOLD
    first = top + 4
    for r, s in enumerate(subs, first):
        ws.cell(row=r, column=1, value=s["name"])
        ws.cell(row=r, column=2, value=s["payments"])
        ws.cell(row=r, column=3, value=s["gross"]).number_format = MONEY
        ws.cell(row=r, column=4, value=s["cis"]).number_format = MONEY
        ws.cell(row=r, column=5, value=f"=C{r}-D{r}").number_format = MONEY
        ws.cell(row=r, column=6, value=f'=IF(C{r}=0,"-",D{r}/C{r})').number_format = "0%"
        if s.get("not_labour"):
            ws.cell(row=r, column=7, value=f"{s['not_labour']}, not a subcontractor: move to the cost it belongs to")
    last = first + len(subs)
    ws.cell(row=last, column=1, value="Total").font = BOLD
    for col in "CDE":
        cell = ws[f"{col}{last}"]
        cell.value = f"=SUM({col}{first}:{col}{last - 1})"
        cell.number_format = MONEY
        cell.font = BOLD
    ws.cell(row=last + 1, column=1, value="Accounts included (lines naming a payee): " + "; ".join(accounts)[:300])
