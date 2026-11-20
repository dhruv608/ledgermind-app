"""P2 - Agent statements (industry rules IND-PRP-06 / 07 / 10), for a confirmed
letting client whose rent comes through letting agents: one block per agent, a row per month.

  Net received per bank   from the ledger (the agent's receipts, as P1 finds them by payer)
  Gross rent, commission, repairs, other deductions   typed from the agent's statements (input cells)
  Net per statement       = gross - commission - repairs - other
  Difference              = net per statement - net per bank (must be nil once the statements are typed)

Below each block, the gross-up journal the totals give (gross rent to rental income; commission and repairs to their
costs; the net is what the books already hold) and a cell for the rent the agent held at the year end (a debtor,
IND-PRP-07). Nothing is posted: the accountant types the statements, then posts the journal shown."""

from collections import defaultdict
from typing import Dict, Optional, Tuple

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from backend.app.services.workbook.balance_tabs.common import INPUT_FILL
from backend.app.services.workbook.context import BuildContext

TAB = "P2 - Agent statements"
MONEY = "#,##0.00;(#,##0.00);-"
AGENT_WORDS = ("agent", "letting", "lettings", "estate", "property management", "landlord", "propert")


def _is_agent(payer: str) -> bool:
    return any(w in payer.lower() for w in AGENT_WORDS)


def add_agent_tab(ctx: BuildContext, after: Optional[str]) -> Optional[str]:
    from sqlalchemy import select
    from backend.app.models.database import MasterCOA
    from backend.app.services.setup.profile_service import confirmed_industry
    from backend.app.services.sop.common import gl_lines, year_months
    from backend.app.services.sop.property import INCOME_SECTIONS, RENT_INCOME
    from backend.app.services.workbook.property_tab import _payer
    profile = getattr(ctx.engagement, "profile", None)
    if ctx.db is None or confirmed_industry(profile) != "PRP":
        return None
    chart = {c.std_code: c for c in ctx.db.execute(select(MasterCOA)).scalars()}
    months = year_months(ctx.engagement.period_end_date)
    by_agent: Dict[str, Dict[Tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))
    for l in gl_lines(str(ctx.engagement.id), ctx.tb_records, ctx.db):
        c = chart.get(l.code)
        if c is None or c.category not in INCOME_SECTIONS or l.when is None:
            continue
        payer = _payer(l.description)
        if payer and _is_agent(payer) and RENT_INCOME.search(f"{l.account} {c.std_name} {l.description}") or \
                payer and _is_agent(payer) and c.std_code == 400:
            by_agent[payer][(l.when.year, l.when.month)] += round(l.credit - l.debit, 2)
    if not by_agent:
        return None
    wb = ctx.wb
    ws = wb.create_sheet(TAB, wb.sheetnames.index(after) + 1 if after in wb.sheetnames else len(wb.sheetnames))
    ws["A1"], ws["A2"], ws["E1"] = "=A!B2", "='Notes & Queries'!A2", "P2"
    ws["A4"] = "Agent statements: net rent received v the agents' statements (P2)"
    ws["A4"].font = Font(name="Calibri", size=12, bold=True)
    ws["A5"] = ("Type each month's figures from the agent's statement in the shaded cells. The difference must be "
                "nil; the totals give the gross-up journal below each agent.")
    heads = ["Month", "Net received per bank", "Gross rent per statement", "Commission", "Repairs", "Other deductions",
             "Net per statement", "Difference (must be nil)"]
    row = 7
    for agent, amounts in sorted(by_agent.items()):
        ws.cell(row=row, column=1, value=agent).font = ctx.bold_font
        row += 1
        for c, h in enumerate(heads, 1):
            ws.cell(row=row, column=c, value=h).font = ctx.bold_font
        first = row + 1
        for m in months:
            row += 1
            ws.cell(row=row, column=1, value=m.strftime("%b-%y"))
            net = amounts.get((m.year, m.month))
            ws.cell(row=row, column=2, value=round(net, 2) if net else None).number_format = MONEY
            for col in range(3, 7):
                cell = ws.cell(row=row, column=col)
                cell.fill, cell.number_format = INPUT_FILL, MONEY
            ws.cell(row=row, column=7, value=f'=IF(C{row}="","",C{row}-D{row}-E{row}-F{row})').number_format = MONEY
            ws.cell(row=row, column=8, value=f'=IF(C{row}="","",ROUND(G{row}-B{row},2))').number_format = MONEY
        row += 1
        ws.cell(row=row, column=1, value="Total").font = ctx.bold_font
        for col in range(2, 9):
            letter = get_column_letter(col)
            ws.cell(row=row, column=col, value=f"=SUM({letter}{first}:{letter}{row - 1})").number_format = MONEY
        total = row
        row += 2
        ws.cell(row=row, column=1, value=("Gross-up journal once typed (IND-PRP-06): Dr commission / agent fees "
                                          f"=D{total}, Dr repairs =E{total}, Dr other costs =F{total}; Cr rental "
                                          f"income (400) the same total (gross rent less the net already in the books)"))
        row += 1
        ws.cell(row=row, column=1, value="Rent held by the agent at the year end (a debtor, IND-PRP-07)")
        held = ws.cell(row=row, column=7)
        held.fill, held.number_format = INPUT_FILL, MONEY
        row += 3
    ws.column_dimensions["A"].width = 30
    for col in "BCDEFGH":
        ws.column_dimensions[col].width = 16
    ctx.report_notes.append(f"Agent statements (P2): {len(by_agent)} agent(s) to agree to their statements")
    return ws.title
