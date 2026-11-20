"""D1-P Development costs (property trading rules IND-PRD-06 / 07 / 08), for a confirmed property trading /
development client:

  Site costs by type   every ledger line given to a site (the property SOP's tagging; one site: every development-type
                       line) split into land, SDLT and legal, professional, contractors, materials and tool hire,
                       finance and arrangement fees, site insurance, other; lines, amount and examples per type.
  Flags                personal or revenue items in the site cost (Red), payments to individuals (CIS or employment
                       status?), finance and arrangement fees in the cost (capitalised: the firm's policy?)
  Property schedule    one row per site (IND-PRD-07): costs this year, sale proceeds, cost released to cost of sales
                       and net realisable value (typed), closing stock, and the check that stock is not above its net
                       realisable value (IND-PRD-08, FRS 102 s13.19).
Nothing is posted: the property SOP's own points (B1 costs expensed, B3 sale with no cost of sales) propose the moves."""

import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from openpyxl.styles import Font, PatternFill

from backend.app.services.workbook.balance_tabs.common import INPUT_FILL
from backend.app.services.workbook.context import BuildContext

TAB = "D1-P Development costs"
MONEY = "#,##0.00;(#,##0.00);-"
RED = PatternFill("solid", fgColor="F8CBAD")
AMBER = PatternFill("solid", fgColor="FCE4D6")
TYPES = (     # in this order: 'stamp duty land tax' is SDLT, not land
    ("SDLT and legal", re.compile(r"stamp duty|\bsdlt\b|legal|solicitor|conveyanc|land registry|searches", re.I)),
    ("Land and purchase", re.compile(r"\bland\b|\bplot\b|purchase price|completion|acquisition", re.I)),
    ("Professional (architect, planning)", re.compile(r"architect|planning|surveyor|engineer|consultant|design|structur", re.I)),
    ("Finance and arrangement fees", re.compile(r"interest|arrangement|broker|finance|funding|lender|bridging|valuation fee", re.I)),
    ("Materials and tool hire", re.compile(r"material|timber|wickes|travis perkins|\bb ?& ?q\b|screwfix|toolstation|jewson|selco|build yard|builders? merchant|hire|plumbase|topps tiles", re.I)),
    ("Site insurance", re.compile(r"insurance", re.I)),
    ("Contractors", re.compile(r"\b(ltd|limited|contractor|builders?|construction|roofing|plumbing|electrical|groundwork|scaffold)\b", re.I)),
)
OTHER = "Other - to review"
PERSONAL = re.compile(r"hamper|supermarket|tesco|sainsbury|asda|aldi|lidl|restaurant|clothing|netflix|spotify|holiday|"
                      r"gym|amazon prime|boots|primark", re.I)
PERSON = re.compile(r"^(mr|mrs|ms|miss)?\s*[A-Z][a-z]+\s+[A-Z][a-z]+(\s|$|-)")
STOCK_CODES = range(4300, 4311)


def _type(text: str) -> str:
    return next((name for name, words in TYPES if words.search(text)), OTHER)


def add_development_tab(ctx: BuildContext) -> Optional[str]:
    from sqlalchemy import select
    from backend.app.models.database import MasterCOA
    from backend.app.services.setup.profile_service import confirmed_industry
    from backend.app.services.sop.common import gl_lines
    from backend.app.services.sop.property import (DEVELOPMENT, INCOME_SECTIONS, TRADING, PropertyEntry, _owner,
                                                   property_entries)
    profile = getattr(ctx.engagement, "profile", None)
    if ctx.db is None or confirmed_industry(profile) != "PRD":
        return None
    chart = {c.std_code: c for c in ctx.db.execute(select(MasterCOA)).scalars()}
    sites = [e for e in property_entries(profile) if e.model == TRADING] or [PropertyEntry("Site", TRADING, None, ["site"])]
    costs: Dict[str, Dict[str, List]] = defaultdict(lambda: defaultdict(list))
    sales: Dict[str, float] = defaultdict(float)
    for l in gl_lines(str(ctx.engagement.id), ctx.tb_records, ctx.db):
        c = chart.get(l.code)
        if c is None:
            continue
        text = f"{l.account} {l.description}"
        owner = _owner(l, sites) or (sites[0] if len(sites) == 1 else None)
        if owner is None:
            continue
        if c.category in INCOME_SECTIONS:
            if not re.search(r"rent", text, re.I):
                sales[owner.name] += l.credit - l.debit
            continue
        in_stock = l.code in STOCK_CODES
        if not (in_stock or (c.financial_class == "Profit and Loss" and DEVELOPMENT.search(text))) or l.debit < 0.01:
            continue
        costs[owner.name][_type(text)].append(l)
    if not costs and not sales:
        return None

    wb = ctx.wb
    anchor = next((n for n in reversed(wb.sheetnames) if re.match(r"^D\d", n)), None)
    ws = wb.create_sheet(TAB, wb.sheetnames.index(anchor) + 1 if anchor else len(wb.sheetnames))
    ws["A1"], ws["A2"], ws["E1"] = "=A!B2", "='Notes & Queries'!A2", "D1-P"
    ws["A4"] = "Development costs by site and type, and the property schedule (D1-P)"
    ws["A4"].font = Font(name="Calibri", size=12, bold=True)
    bold = ctx.bold_font
    row = 6
    flags: List[Tuple[str, str, PatternFill]] = []
    for site in [s.name for s in sites]:
        if not costs[site]:
            continue
        ws.cell(row=row, column=1, value=site).font = bold
        row += 1
        for c, h in enumerate(("Cost type", "Lines", "Amount £", "Examples", "Flag"), 1):
            ws.cell(row=row, column=c, value=h).font = bold
        first = row + 1
        for kind in [n for n, _w in TYPES] + [OTHER]:
            lines = costs[site].get(kind) or []
            if not lines:
                continue
            row += 1
            amount = round(sum(l.debit - l.credit for l in lines), 2)
            examples = "; ".join(f"{l.when:%d/%m/%y} {(l.description or l.account)[:30]}" for l in sorted(lines, key=lambda x: -x.debit)[:2])
            flag = "Amber" if kind in (OTHER, "Finance and arrangement fees") else "OK"
            for v, col in ((kind, 1), (len(lines), 2), (amount, 3), (examples, 4), (flag, 5)):
                cell = ws.cell(row=row, column=col, value=v)
                if col == 3:
                    cell.number_format = MONEY
            if flag == "Amber":
                ws.cell(row=row, column=5).fill = AMBER
        row += 1
        ws.cell(row=row, column=1, value="Total").font = bold
        ws.cell(row=row, column=3, value=f"=SUM(C{first}:C{row - 1})").number_format = MONEY
        all_lines = [l for ls in costs[site].values() for l in ls]
        personal = [l for l in all_lines if PERSONAL.search(f"{l.description} {l.account}")]
        people = sorted({(l.description or "").split(" - ")[0] for l in all_lines
                         if PERSON.match((l.description or "").split(" - ")[0]) and not re.search(r"\bltd\b|limited", l.description or "", re.I)})
        if personal:
            flags.append((site, f"Personal or revenue items in the site cost: {'; '.join((l.description or '')[:35] for l in personal[:3])} "
                                f"(£{sum(l.debit for l in personal):,.2f}): not a site cost", RED))
        if people:
            flags.append((site, f"Payments to individuals ({', '.join(people[:4])}): subcontractors under CIS or employees?", AMBER))
        if costs[site].get("Finance and arrangement fees"):
            flags.append((site, "Finance and arrangement fees in the site cost: capitalised only if that is the firm's "
                                "policy (IND-PRD-06; FRS 102 s25)", AMBER))
        if costs[site].get(OTHER):
            flags.append((site, "Costs not recognised as a site cost type: check each has an invoice and belongs to the site", AMBER))
        row += 3

    ws.cell(row=row, column=1, value="Property schedule (IND-PRD-07 / 08)").font = bold
    row += 1
    heads = ("Site", "Costs this year", "Sale proceeds", "Cost released to cost of sales", "Closing stock",
             "Net realisable value", "Check: stock not above NRV (must be nil)", "Status (sold / let / held)")
    for c, h in enumerate(heads, 1):
        ws.cell(row=row, column=c, value=h).font = bold
    for site in [s.name for s in sites]:
        row += 1
        spent = round(sum(l.debit - l.credit for ls in costs[site].values() for l in ls), 2)
        ws.cell(row=row, column=1, value=site)
        ws.cell(row=row, column=2, value=spent).number_format = MONEY
        ws.cell(row=row, column=3, value=round(sales[site], 2)).number_format = MONEY
        for col in (4, 6, 8):
            cell = ws.cell(row=row, column=col)
            cell.fill = INPUT_FILL
            if col != 8:
                cell.number_format = MONEY
        ws.cell(row=row, column=5, value=f"=B{row}-N(D{row})").number_format = MONEY
        ws.cell(row=row, column=7, value=f'=IF(F{row}="","",MAX(0,ROUND(E{row}-F{row},2)))').number_format = MONEY
    row += 2
    ws.cell(row=row, column=1, value="Points to look at").font = bold
    for site, text, fill in flags or [("", "None", None)]:
        row += 1
        ws.cell(row=row, column=1, value=site)
        cell = ws.cell(row=row, column=2, value=text)
        if fill:
            cell.fill = fill
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["D"].width = 48
    for col in "BCEFGH":
        ws.column_dimensions[col].width = 16
    if flags:
        ctx.report_notes.append(f"Development costs (D1-P): {len(flags)} point(s) to look at")
    return ws.title
