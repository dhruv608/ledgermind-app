"""
The accountant's planning and completion tabs (FRS, Associated Co's, Accrual and checklists), filled from what the
app already knows:

  FRS                 the size test (turnover, balance sheet total, employees; this year and last year) against the
                      limits for the year (the new limits only for years beginning on or after 6 April 2025), and
                      the framework chosen on the setup
  Associated Co's     the count on the setup (it divides the corporation tax limits) and the connected companies
  Accrual             the accountancy fees invoiced this year, by month; the fee agreed is the accountant's input
  Checklists          the firm's Accounts & CT600 checklist and its FRS 105 or FRS 102 1A disclosure checklist
                      (rules/checklists.json, the firm's own wording), with Yes / No / N/A columns
"""

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl.styles import Alignment
from openpyxl.worksheet.datavalidation import DataValidation

from backend.app.services.workbook.balance_tabs import BOLD, INPUT_FILL, MONEY, TITLE, Context, _input, _lines_for, _money, _when
from backend.app.services.setup.engagement_setup import FRAMEWORK_NAMES, NEW_LIMITS_FROM, size_limits

CHECKLISTS = Path(__file__).resolve().parents[2] / "rules" / "checklists.json"
ACCOUNTANCY_FEES = 3301
WRAP = Alignment(wrap_text=True, vertical="top")
AFTER = ["A1 - General checks", "A"]


def _sheet(ctx: Context, title: str, after: List[str], heading: str, ref: str):
    wb = ctx.wb
    anchor = next((n for n in after if n in wb.sheetnames), None)
    ws = wb.create_sheet(title, wb.sheetnames.index(anchor) + 1 if anchor else len(wb.sheetnames))
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    ws["H1"] = ref
    ws["A4"] = heading
    ws["A4"].font = TITLE
    return ws


def _period_start(record: Dict[str, Any]) -> Optional[date]:
    try:
        return date.fromisoformat(str((record.get("client") or {}).get("period_start"))[:10])
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------------------------
def frs_tab(ctx: Context, record: Dict[str, Any], last_year: Dict[str, Optional[float]], after: List[str]) -> str:
    c = record.get("client") or {}
    start = _period_start(record)
    limits = size_limits(start)
    ws = _sheet(ctx, "A2 - FRS (size test)", after, "FRS - which standard: FRS 105 (micro) or FRS 102 1A (small)", "A2")
    ws["A5"] = ("A company is micro / small when it meets at least two of the three limits, in this year and the year "
                "before (two years in a row; not needed in the first year). The turnover limit is pro-rated for a "
                "period longer or shorter than 12 months.")
    ws["A5"].alignment = WRAP
    ws.merge_cells("A5:G5")
    ws.row_dimensions[5].height = 45
    rule = ("the limits for financial years beginning on or after 6 April 2025 (SI 2024/1303)" if start is None
            or start >= NEW_LIMITS_FROM else "the limits before 6 April 2025: this year began on "
            f"{start:%d/%m/%Y}, before the new limits apply")
    ws["A6"] = f"Limits used: {rule}."
    heads = ["", "This year", "Last year", "Micro limit", "Small limit", "Medium limit"]
    for i, h in enumerate(heads, 1):
        ws.cell(row=8, column=i, value=h).font = BOLD
    lim = {x["band"]: x for x in limits}
    rows = [("Turnover", c.get("turnover"), last_year.get("turnover"), "turnover"),
            ("Balance sheet total (fixed and current assets)", c.get("balance_sheet_total"), last_year.get("assets"), "assets"),
            ("Average number of employees", c.get("employees"), last_year.get("employees"), "employees")]
    for r, (label, now, before, key) in enumerate(rows, 9):
        ws.cell(row=r, column=1, value=label)
        for col, v in ((2, now), (3, before)):
            cell = ws.cell(row=r, column=col)
            if v is None:
                _input(cell)                 # not known: the accountant types it
            else:
                cell.value = v
            cell.number_format = MONEY if key != "employees" else "0.0"
        for col, band in ((4, "Micro"), (5, "Small"), (6, "Medium")):
            if band in lim and lim[band].get(key) is not None:
                cell = ws.cell(row=r, column=col, value=lim[band][key])
                cell.number_format = MONEY if key != "employees" else "0"
    ws["A13"] = "Limits met (2 of 3 needed)"
    ws["A13"].font = BOLD
    for r, (band, col) in enumerate((("Micro", "D"), ("Small", "E"), ("Medium", "F")), 14):
        ws.cell(row=r, column=1, value=band)
        for year_col in ("B", "C"):
            met = "+".join(f'AND({year_col}{x}<>"",{year_col}{x}<={col}{x})*1' for x in (9, 10, 11))
            ws[f"{year_col}{r}"] = f'=IF(COUNT({year_col}9:{year_col}11)<2,"Not known",IF({met}>=2,"Yes","No"))'
    ws["A18"] = "Size this year"
    ws["B18"] = '=IF(B14="Yes","Micro",IF(B15="Yes","Small",IF(B16="Yes","Medium",IF(B14="Not known","Not known","Large"))))'
    ws["A19"] = "Size last year"
    ws["B19"] = '=IF(C14="Yes","Micro",IF(C15="Yes","Small",IF(C16="Yes","Medium",IF(C14="Not known","Not known","Large"))))'
    for r in (18, 19):
        ws[f"A{r}"].font = BOLD
        ws[f"B{r}"].font = BOLD
    framework = c.get("framework")
    ws["A21"] = "Framework on the client setup"
    ws["B21"] = FRAMEWORK_NAMES.get(framework, "Not chosen yet")
    ws["B21"].font = BOLD
    ws["A22"] = "Check"
    ws["B22"] = ('=IF(B21="Not chosen yet","Choose the framework on the client setup",'
                 'IF(AND(B21="FRS 105",OR(B18<>"Micro",AND(B19<>"Micro",B19<>"Not known"))),'
                 '"FRS 105 needs a micro-entity this year and last year: check",'
                 'IF(AND(B21="FRS 102 1A",OR(B18="Medium",B18="Large")),"Too large for FRS 102 1A: full FRS 102",'
                 '"Agrees with the size test")))')
    ws["A24"] = "Not a micro-entity whatever the size: a charity, an LLP or qualifying partnership, an investment " \
                "undertaking, a financial holding or insurance undertaking, a credit institution, an overseas company, " \
                "a parent preparing group accounts or a subsidiary included in consolidated accounts."
    ws["A25"] = "FRS 105 still right? Consider FRS 102 instead when the company has a deferred tax asset, goodwill or " \
                "investment property to revalue, development or borrowing costs to capitalise, or is growing fast."
    for r in (24, 25):
        ws[f"A{r}"].alignment = WRAP
        ws.merge_cells(f"A{r}:G{r}")
        ws.row_dimensions[r].height = 45
    ws.column_dimensions["A"].width = 46
    for col in "BCDEF":
        ws.column_dimensions[col].width = 16
    return ws.title


# ------------------------------------------------------------------------------------------------------------------
def associated_tab(ctx: Context, record: Dict[str, Any], companies: List[str], after: List[str]) -> str:
    ws = _sheet(ctx, "A3 - Associated companies", after, "Associated companies", "A3")
    ws["A5"] = ("Companies are associated when one controls the other, or the same person or group of persons "
                "controls both, at any time in the period (CTA 2010 s25). Each one divides the corporation tax "
                "small profits and marginal relief limits (£50,000 / £250,000).")
    ws["A5"].alignment = WRAP
    ws.merge_cells("A5:F5")
    ws.row_dimensions[5].height = 45
    count = (record.get("ct") or {}).get("associated_companies")
    ws["A7"] = "Number of associated companies (client setup, used in the tax computation H1)"
    if count is None:
        _input(ws["E7"])
        ws["F7"] = "Not answered on the setup"
    else:
        ws["E7"] = int(count)
    ws["E7"].number_format = "0"
    ws["A7"].font = BOLD
    ws["A8"] = "Small profits limit for this company"
    ws["E8"] = "=IF(E7=\"\",\"\",50000/(E7+1))"
    ws["A9"] = "Upper (marginal relief) limit for this company"
    ws["E9"] = "=IF(E7=\"\",\"\",250000/(E7+1))"
    for r in (8, 9):
        ws[f"E{r}"].number_format = MONEY
    ws["A11"] = "Companies connected through the directors (related parties on the setup)"
    ws["A11"].font = BOLD
    for i, name in enumerate(companies or ["None recorded"], 12):
        ws.cell(row=i, column=1, value=name)
    note = 12 + max(len(companies), 1) + 1
    ws.cell(row=note, column=1, value=("Check each one for control (shares, votes, rights to assets) and for "
                                       "commercial interdependence before counting it.")).alignment = WRAP
    ws.column_dimensions["A"].width = 70
    ws.column_dimensions["E"].width = 16
    return ws.title


# ------------------------------------------------------------------------------------------------------------------
def fee_accrual_tab(ctx: Context, after: List[str]) -> str:
    ws = _sheet(ctx, "A4 - Accountancy fee accrual", after, "Accountancy fee: invoiced this year and accrual", "A4")
    names = [t.raw_account_name for t in ctx.tb_records if t.std_code == ACCOUNTANCY_FEES]
    lines = _lines_for(ctx, names) if names else []
    by_month: Dict[tuple, float] = defaultdict(float)
    for tx in lines:
        when = _when(tx[0])
        if when:
            by_month[(when.year, when.month)] += float(tx[7] or 0) - float(tx[8] or 0)
    ws["A6"] = "Fee agreed for this year's accounts and CT600 (£)"
    _input(ws["E6"])
    ws["A7"] = "Fee agreed for the confirmation statement (£)"
    _input(ws["E7"])
    ws["F6"] = "Type these (from the engagement letter / proposal)"
    for c, h in enumerate(["Month", "", "", "", "Invoiced (ledger)"], 1):
        if h:
            ws.cell(row=9, column=c, value=h).font = BOLD
    r = 10
    for (y, m) in sorted(by_month):
        ws.cell(row=r, column=1, value=date(y, m, 1)).number_format = "mmm yyyy"
        _money(ws.cell(row=r, column=5, value=round(by_month[(y, m)], 2)))
        r += 1
    if not by_month:
        ws.cell(row=r, column=1, value="No accountancy fees in the ledger this year" +
                ("" if names else " (no account on 3301)"))
        r += 1
    ws.cell(row=r, column=1, value="Invoiced this year").font = BOLD
    _money(ws.cell(row=r, column=5, value=f"=SUM(E10:E{r - 1})"), bold=True, total=True)
    total = r
    ws.cell(row=r + 2, column=1, value="Accrual needed: fee agreed less invoiced").font = BOLD
    _money(ws.cell(row=r + 2, column=5, value=f'=IF(AND(E6="",E7=""),"",E6+E7-E{total})'), bold=True)
    ws.cell(row=r + 3, column=1, value="If fees are outstanding or overdue, chase them before starting the work.")
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["E"].width = 16
    return ws.title


# ------------------------------------------------------------------------------------------------------------------
def checklist_tab(ctx: Context, key: str, title: str, ref: str, after: List[str]) -> Optional[str]:
    from backend.app.services.shared import rules_store
    lists = rules_store.load("checklists")
    data = lists.get(key)
    if not data:
        return None
    ws = _sheet(ctx, title, after, data["title"], ref)
    ws["A5"] = data.get("objective") or ""
    for i, note in enumerate(data.get("notes") or [], 6):
        ws.cell(row=i, column=1, value=note)
    head = 7 + len(data.get("notes") or []) + 1
    for c, h in enumerate(["Area", "Item", "Preparer (Yes / No / N/A)", "Preparer notes",
                           "Reviewer (Yes / No / N/A)", "Reviewer notes"], 1):
        ws.cell(row=head, column=c, value=h).font = BOLD
    answers = DataValidation(type="list", formula1='"Yes,No,N/A"', allow_blank=True)
    ws.add_data_validation(answers)
    section = None
    for r, item in enumerate(data["items"], head + 1):
        if item["section"] != section:
            section = item["section"]
            ws.cell(row=r, column=1, value=section).font = BOLD
        ws.cell(row=r, column=2, value=item["text"]).alignment = WRAP
        for col in ("C", "E"):
            ws[f"{col}{r}"].fill = INPUT_FILL
            answers.add(f"{col}{r}")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 80
    for col in "CDEF":
        ws.column_dimensions[col].width = 16
    ws.freeze_panes = f"A{head + 1}"
    return ws.title


# ------------------------------------------------------------------------------------------------------------------
def add_setup_tabs(ctx: Context, record: Dict[str, Any], last_year: Dict[str, Optional[float]],
                   companies: List[str]) -> List[str]:
    made = [frs_tab(ctx, record, last_year, AFTER)]
    made.append(associated_tab(ctx, record, companies, [made[-1]]))
    made.append(fee_accrual_tab(ctx, [made[-1]]))
    made.append(checklist_tab(ctx, "accounts_ct", "A5 - Accounts & CT checklist", "A5", [made[-1]]))
    # The disclosure checklist of the framework chosen (FRS 105 for a micro-entity, else FRS 102 1A)
    framework = (record.get("client") or {}).get("framework")
    size = (record.get("client") or {}).get("size")
    key = "frs105" if framework == "FRS105" or (framework is None and size == "Micro") else "frs102_1a"
    made.append(checklist_tab(ctx, key, "A6 - Disclosure checklist", "A6", [made[-1]]))
    return [m for m in made if m]
