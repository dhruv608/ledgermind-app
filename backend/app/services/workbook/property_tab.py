"""P1 - Property income and costs, for a letting client:

  1. Properties: the setup's list (rental ones); blank, the ones the ledger suggests (marked 'suggested').
  2. Each P&L ledger line given to a property by the property SOP's own tagging (tracking tag, then the property's name
     or words in the account or description, then with one property every property-type line); the rest 'Unallocated'.
  3. Rent grid: property by month, the rent received (net, as the ledger has it) and the number of receipts.
  4. Cost grid: property and cost type by month (mortgage interest, repairs, insurance, agent fees, utilities,
     service charge, other).
  6. Flags with the property and months named: (a) a month with no rent, (b) a negative receipt, (c) net receipts that
     vary (gross up from the agent's statements), (d) one payer for two or more properties, (e) costs but no income,
     (f) mortgage paid but no capital repaid (the whole payment as interest?).
Step 5 (last year per property) and the Notes & Queries side follow once last year's papers give rent per property."""

import re
from collections import defaultdict
from statistics import mean, pstdev
from typing import Dict, List, Optional, Tuple

from openpyxl.styles import Font, PatternFill

from backend.app.services.workbook.context import BuildContext

TAB = "P1 - Property income and costs"
UNALLOCATED = "Unallocated"
COST_TYPES = (
    ("Mortgage interest", re.compile(r"mortgage|interest", re.I)),
    ("Repairs and maintenance", re.compile(r"repair|maintenance|plumb|electrician|handyman", re.I)),
    ("Insurance", re.compile(r"insurance|guarantee", re.I)),
    ("Agent fees", re.compile(r"agent|letting|management fee|commission|landlord", re.I)),
    ("Utilities and council tax", re.compile(r"\bgas\b|electric|water|council tax|utilit", re.I)),
    ("Service charge and ground rent", re.compile(r"service charge|ground rent", re.I)),
)
OTHER = "Other costs"
FLAG = PatternFill("solid", fgColor="FCE4D6")
MONEY = "#,##0.00;(#,##0.00);-"
VARY = 0.10               # net receipts varying by more than 10% of their average: deductions not shown
LOAN_CODES = set(range(5000, 5012)) | {5100, 5110} | set(range(5500, 5511))


def _cost_type(text: str) -> str:
    return next((name for name, words in COST_TYPES if words.search(text)), OTHER)


def _payer(description: str) -> str:
    from backend.app.sa.property_bank import payer_of
    return payer_of(description or "")


def add_property_tab(ctx: BuildContext) -> Optional[str]:
    from sqlalchemy import select
    from backend.app.models.database import MasterCOA
    from backend.app.services.setup.profile_service import confirmed_industry
    from backend.app.services.sop.common import gl_lines, year_months
    from backend.app.services.sop.property import (INCOME_SECTIONS, RENTAL, RENT_INCOME, PropertyEntry, _owner,
                                                   property_entries, suggest_properties)
    profile = getattr(ctx.engagement, "profile", None)
    if ctx.db is None or confirmed_industry(profile) != "PRP":
        return None
    entries = [e for e in property_entries(profile) if e.model == RENTAL]
    suggested = False
    if not entries:
        suggested = True
        entries = [PropertyEntry(s["name"], RENTAL, None, [s["name"].lower()])
                   for s in suggest_properties(str(ctx.engagement.id), ctx.tb_records, ctx.db) if s["model"] == RENTAL]
    chart = {c.std_code: c for c in ctx.db.execute(select(MasterCOA)).scalars()}
    lines = gl_lines(str(ctx.engagement.id), ctx.tb_records, ctx.db)
    months = year_months(ctx.engagement.period_end_date)
    key = lambda d: (d.year, d.month)
    names = [e.name for e in entries] + [UNALLOCATED]

    rent: Dict[str, Dict[Tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))
    count: Dict[str, Dict[Tuple[int, int], int]] = defaultdict(lambda: defaultdict(int))
    costs: Dict[Tuple[str, str], Dict[Tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))
    receipts: Dict[str, List[Tuple[object, float, str]]] = defaultdict(list)
    payers: Dict[str, set] = defaultdict(set)
    loan_repaid = sum(l.debit for l in lines if l.code in LOAN_CODES)
    for l in lines:
        c = chart.get(l.code)
        if c is None or c.financial_class != "Profit and Loss" or l.when is None:
            continue
        owner = _owner(l, entries)
        prop = owner.name if owner else UNALLOCATED
        if c.category in INCOME_SECTIONS:
            if not (RENT_INCOME.search(f"{l.account} {c.std_name}") or owner):
                continue
            amount = round(l.credit - l.debit, 2)
            rent[prop][key(l.when)] += amount
            count[prop][key(l.when)] += 1
            receipts[prop].append((l.when, amount, l.description))
            if _payer(l.description):
                payers[_payer(l.description)].add(prop)
        elif owner is not None or prop == UNALLOCATED and _cost_type(f"{l.account} {l.description}") != OTHER:
            costs[(prop, _cost_type(f"{l.account} {c.std_name} {l.description}"))][key(l.when)] += round(l.debit - l.credit, 2)

    ws = _sheet(ctx)
    bold = ctx.bold_font
    ws["A4"] = "Property income and costs by month (P1)"
    ws["A4"].font = Font(name="Calibri", size=12, bold=True)
    ws["A5"] = (("Properties suggested from the ledger (none set up on the client setup screen): confirm them there. "
                 if suggested else "") + "Lines are given to a property by tag, then its name or words in the "
                "account or description; the rest are Unallocated.")
    heads = ["Property", "Line"] + [m.strftime("%b-%y") for m in months] + ["Total"]
    row = 7
    for c, h in enumerate(heads, 1):
        ws.cell(row=row, column=c, value=h).font = bold
    row += 1
    flags: List[Tuple[str, str]] = []
    for prop in names:
        has_rent = any(rent[prop].values()) or receipts[prop]
        prop_costs = [(t, costs[(prop, t)]) for t in [n for n, _w in COST_TYPES] + [OTHER] if any(costs[(prop, t)].values())]
        if not has_rent and not prop_costs:
            continue
        if has_rent:
            row = _grid_row(ws, row, prop, "Rent received (net)", months, rent[prop], key, highlight_blank=True)
            row = _grid_row(ws, row, prop, "Number of receipts", months, count[prop], key, money=False)
            blank = [m.strftime("%b-%y") for m in months if not count[prop].get(key(m))]
            if blank and prop != UNALLOCATED:
                flags.append((prop, f"(a) No rent in {', '.join(blank)}: empty, in arrears or sold?"))
            for when, amount, text in receipts[prop]:
                if amount < 0:
                    flags.append((prop, f"(b) Negative receipt {when:%d/%m/%Y} £{amount:,.2f} ({text[:50]}): agent "
                                        f"deduction or refund? Ask for the agent's statement"))
            amounts = [a for _w, a, _t in receipts[prop] if a > 0]
            if len(amounts) >= 3 and mean(amounts) > 0 and pstdev(amounts) / mean(amounts) > VARY:
                flags.append((prop, f"(c) Net receipts vary from £{min(amounts):,.2f} to £{max(amounts):,.2f}: gross "
                                    f"up from the agent's statements"))
        for t, by_month in prop_costs:
            row = _grid_row(ws, row, prop, t, months, by_month, key)
        # (rent that could not be split between the properties may be this one's: then it is (d), not (e))
        if prop_costs and not has_rent and prop != UNALLOCATED and not receipts[UNALLOCATED]:
            flags.append((prop, "(e) Costs but no rent this year: empty or sold?"))
        row += 1
    for payer, props in sorted(payers.items()):
        if len(props - {UNALLOCATED}) >= 2 or (UNALLOCATED in props and len(entries) >= 2):
            flags.append((payer, f"(d) {payer} pays rent for more than one property: statements per property "
                                 f"to split it"))
    mortgage = sum(sum(v.values()) for (p, t), v in costs.items() if t == "Mortgage interest")
    if mortgage > 0 and loan_repaid < 1:
        flags.append(("All properties", f"(f) Mortgage payments of £{mortgage:,.2f} all in interest and no loan "
                                        f"repaid: interest-only, or capital included? Ask for the lender's statement"))
    row += 1
    ws.cell(row=row, column=1, value="Points to look at").font = bold
    for prop, text in flags or [("", "None")]:
        row += 1
        ws.cell(row=row, column=1, value=prop)
        ws.cell(row=row, column=2, value=text)
    for col, w in (("A", 34), ("B", 28)):
        ws.column_dimensions[col].width = w
    if flags:
        ctx.report_notes.append(f"Property income and costs (P1): {len(flags)} point(s) to look at")
    return ws.title


def _sheet(ctx: BuildContext):
    wb = ctx.wb
    anchor = next((n for n in reversed(wb.sheetnames) if re.match(r"^K\d", n)), None)
    ws = wb.create_sheet(TAB, wb.sheetnames.index(anchor) + 1 if anchor else len(wb.sheetnames))
    ws["A1"], ws["A2"], ws["E1"] = "=A!B2", "='Notes & Queries'!A2", "P1"
    return ws


def _grid_row(ws, row, prop, label, months, values, key, money=True, highlight_blank=False):
    ws.cell(row=row, column=1, value=prop)
    ws.cell(row=row, column=2, value=label)
    for i, m in enumerate(months):
        v = values.get(key(m))
        cell = ws.cell(row=row, column=3 + i, value=round(v, 2) if v else None)
        if money:
            cell.number_format = MONEY
        if highlight_blank and not v:
            cell.value = "none"
            cell.fill = FLAG
        elif v is not None and v < 0:
            cell.fill = FLAG
    total = ws.cell(row=row, column=3 + len(months), value=f"=SUM(C{row}:{_col(2 + len(months))}{row})")
    if money:
        total.number_format = MONEY
    return row + 1


def _col(n: int) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(n)
