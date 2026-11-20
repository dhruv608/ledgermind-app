"""The screen's extra papers in the workbook, so the Excel shows the control accounts as the screen does. Each comes
from the same service the screen reads, so the two never disagree, and is written under its area's tab after what is
already there (nothing above moves):

    trade adjustments (duplicates, unallocated, direct, opening variance)   E2 / G2   services/trade_adjustments
    sales reconciliation (VAT returns box 6 to the P&L)                     G9        services/sales_reconciliation
    payroll summary by month (total, employees, directors)                   G6        services/payroll_summary
    residual value and useful life typed on the asset register               C1-1      services/fixed_asset_schedule
    stock lines (type, impairment, verified by)                              D2.2      models/stock_lines
    year-end prepayments and accruals with their invoices                    E3 / G10  models/yearend_adjustments
    papers the accountant added on an area                                   area tab  models/custom_papers

A paper that cannot be read leaves a note and the rest of the workbook is built."""

import json
import logging
from datetime import date
from typing import Any, Callable, List, Optional, Sequence

from openpyxl.styles import Font

logger = logging.getLogger(__name__)

MONEY = '#,##0.00;(#,##0.00);"-"'
BOLD = Font(name="Calibri", size=10, bold=True)
TITLE = Font(name="Calibri", size=11, bold=True)
NOTE = Font(name="Calibri", size=9, italic=True, color="64748B")

# The tab each screen area's papers go under (the first one the workbook has)
AREA_TABS = {
    "bank": ["F2-Bank", "F1 (LEAD)"], "sales": ["E1 (LEAD)"], "purchases": ["G1 (LEAD)"],
    "loans": ["G4 - Loans & HP", "G1 (LEAD)"], "dla": ["G3- DLA", "J1 - Share Capital"],
    "accruals": ["G10 - Accruals", "E3 - Prepayments"], "tax": ["H1-Taxation"], "vat": ["G9 - VAT"],
    "payroll": ["G6 - Net Wages", "G7-PAYE liabilities"], "fixed": ["C1 (LEAD)"], "stock": ["D2 - Stock Material"],
    "opening": ["B1-ETB"], "expenses": ["B1-ETB"], "general": ["A1 - General checks", "B1-ETB"],
}


def _tab(wb, names: Sequence[str]):
    return next((wb[n] for n in names if n in wb.sheetnames), None)


def last_used(ws) -> int:
    """The last row holding a value (a template's empty formatted rows below it do not count)."""
    for r in range(ws.max_row, 0, -1):
        if any(c.value not in (None, "") for c in ws[r]):
            return r
    return 0


def block(ws, title: str, heads: Sequence[str], rows: List[Sequence[Any]], money: Sequence[int] = (),
          total: Sequence[int] = (), note: str = "") -> int:
    """A titled table under what the tab already holds (two rows clear): heading row, the rows, a total of the `total`
    columns (1-based). Returns the last row written."""
    r = last_used(ws) + 3
    ws.cell(row=r, column=1, value=title).font = TITLE
    if note:
        r += 1
        ws.cell(row=r, column=1, value=note).font = NOTE
    r += 1
    for c, h in enumerate(heads, 1):
        ws.cell(row=r, column=c, value=h).font = BOLD
    first = r + 1
    for values in rows:
        r += 1
        for c, v in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if c in money and isinstance(v, (int, float)):
                cell.number_format = MONEY
            elif isinstance(v, int):
                cell.number_format = "0"
            elif isinstance(v, date):
                cell.number_format = "dd/mm/yyyy"
    if total and rows:
        r += 1
        ws.cell(row=r, column=1, value="Total").font = BOLD
        for c in total:
            col = ws.cell(row=first, column=c).column_letter
            cell = ws.cell(row=r, column=c, value=f"=SUM({col}{first}:{col}{r - 1})")
            cell.number_format, cell.font = MONEY, BOLD
    return r


# ----------------------------------------------------------------------------------------------------------------------
def trade_adjustments_papers(ctx) -> None:
    from backend.app.services.reconciliation.trade_adjustments import trade_adjustments
    for side, tab in (("customer", "E2-Trade Debtors"), ("supplier", "G2 - Trade creditors")):
        if tab not in ctx.wb.sheetnames:
            continue
        data = trade_adjustments(ctx.engagement, ctx.db, side)
        rows: List[Sequence[Any]] = []
        for line in data["lines"]:
            rows.append((line["label"], line["count"] or None, line["amount"], line["note"] or None))
            for d in line["details"]:
                rows.append((f"    {d}"[:200], None, None, None))
            if line["more"]:
                rows.append((f"    ... and {line['more']} more", None, None, None))
        block(ctx.wb[tab], "Adjustments to the ledger (as on the screen)", ("Adjustment", "Items", "Amount £", "Note"),
              rows, money=(3,))


def sales_reconciliation_paper(ctx) -> None:
    from backend.app.services.reconciliation.sales import sales_reconciliation
    ws = _tab(ctx.wb, ["G9 - VAT"])
    if ws is None:
        return
    data = sales_reconciliation(ctx.engagement, ctx.db)
    note = (f"{data['basis'].title()} basis" + ("; flat rate scheme" if data.get("flat_rate") else "")
            + ("" if data["ready"] else f". {data['why_not']}"))
    block(ws, "Sales reconciliation: VAT returns to the P&L (as on the screen)", ("Line", "", "", "Amount £", "Note"),
          [(l["label"], None, None, l["amount"], l["note"]) for l in data["lines"]], money=(4,), note=note)


PAYROLL_HEADS = ("Month", "Gross pay", "PAYE", "Employee NI", "Student loan", "Employee pension", "Employer NI",
                 "Net pay", "Employer pension", "PAYE / NI liability", "Employment allowance", "Total liability",
                 "Pension payable")
PAYROLL_KEYS = ("gross", "paye", "ee_ni", "student_loan", "ee_pension", "er_ni", "net", "er_pension", "liability",
                "allowance", "total_liability", "pension_payable")


def payroll_summary_paper(ctx) -> None:
    from backend.app.services.papers.payroll_summary import payroll_summary
    ws = _tab(ctx.wb, AREA_TABS["payroll"])
    if ws is None:
        return
    data = payroll_summary(ctx.engagement, ctx.db)
    if not data["has_reports"]:
        return
    money = tuple(range(2, len(PAYROLL_HEADS) + 1))
    for t in data["tables"]:
        rows = [(m["month"], *[m[k] for k in PAYROLL_KEYS]) for m in t["months"]]
        block(ws, f"Payroll summary by month: {t['title'].lower()} (as on the screen)", PAYROLL_HEADS, rows, money=money,
              total=money, note=(f"{t['people']} people on the payroll report" if t.get("people") else ""))
    if data.get("split"):
        ws.cell(row=last_used(ws) + 2, column=1, value=data["split"]).font = NOTE


def asset_details_paper(ctx) -> None:
    from backend.app.services.papers.fixed_asset_schedule import register
    ws = _tab(ctx.wb, ["C1-1-FA detail", "C1 (LEAD)"])
    if ws is None:
        return
    rows = [(a["description"], a["date"] and date.fromisoformat(a["date"]), a["residual_value"], a["useful_life_years"])
            for c in register(ctx.engagement, ctx.db)["classes"] for a in c["assets"]
            if a["residual_value"] is not None or a["useful_life_years"] is not None]
    if rows:
        block(ws, "Residual value and useful life (typed on the asset register)",
              ("Asset", "Date", "Residual value £", "Useful life (years)"), rows, money=(3,))


def stock_lines_paper(ctx) -> None:
    from sqlalchemy import select
    from backend.app.models.stock_lines import StockLine
    ws = _tab(ctx.wb, ["D2.2 - Stock details", "D2 - Stock Material"])
    if ws is None:
        return
    lines = list(ctx.db.execute(select(StockLine).where(StockLine.engagement_id == str(ctx.engagement.id))).scalars())
    if not lines:
        return
    rows = [(l.stock_type or None, l.description, l.code, float(l.amount or 0), float(l.impairment or 0),
             round(float(l.amount or 0) - float(l.impairment or 0), 2), l.last_year,
             {"US": "Us", "CLIENT": "Client"}.get(l.verified_by, l.verified_by or None), l.note or None) for l in lines]
    block(ws, "Stock lines (as on the screen)", ("Type", "Description", "Code", "Amount £", "Impairment £", "Net £",
                                                 "Last year £", "Verified by", "Note"),
          rows, money=(4, 5, 6, 7), total=(4, 5, 6))


def yearend_adjustment_papers(ctx) -> None:
    from sqlalchemy import select
    from backend.app.models.yearend_adjustments import YearEndAdjustment
    items = list(ctx.db.execute(select(YearEndAdjustment).where(
        YearEndAdjustment.engagement_id == str(ctx.engagement.id))).scalars())
    for kind, tab, title in (("PREPAYMENT", ["E3 - Prepayments"], "Prepayments entered (as on the screen)"),
                             ("ACCRUAL", ["G10 - Accruals"], "Accruals entered (as on the screen)")):
        ws = _tab(ctx.wb, tab)
        mine = [a for a in items if a.kind == kind]
        if ws is None or not mine:
            continue
        rows = [("This year" if a.period == "THIS_YEAR" else "Last year", a.description, a.cost_code, float(a.amount or 0),
                 a.invoice_number, a.invoice_date, None if a.invoice_amount is None else float(a.invoice_amount),
                 a.period_from, a.period_to) for a in sorted(mine, key=lambda a: (a.period, a.cost_code))]
        block(ws, title, ("Year", "Description", "Cost code", "Amount £", "Invoice no.", "Invoice date", "Invoice amount £",
                          "Period from", "Period to"), rows, money=(4, 7))


def added_papers(ctx) -> None:
    from sqlalchemy import select
    from backend.app.models.custom_papers import CustomPaper
    for p in ctx.db.execute(select(CustomPaper).where(CustomPaper.engagement_id == str(ctx.engagement.id))
                            .order_by(CustomPaper.id)).scalars():
        ws = _tab(ctx.wb, AREA_TABS.get(p.area, []) + ["B1-ETB"])
        if ws is None:
            continue
        try:
            lines = json.loads(p.lines or "[]")
            codes = json.loads(p.codes or "[]")
        except ValueError:
            lines, codes = [], []
        kind = {"DETAILED": "Detailed T", "SUPPORTING": "Supporting note", "RECONCILIATION": "Reconciliation",
                "LOAN_SCHEDULE": "Loan schedule"}.get(p.kind, p.kind.title())
        note = (p.note or "")[:250] + (f" (codes {', '.join(str(c) for c in codes)})" if codes else "")
        rows = [(l.get("label"), l.get("side", "").title(), float(l.get("amount") or 0)) for l in lines]
        last = block(ws, f"{kind} added: {p.name}"[:120], ("Line", "Side", "Amount £"), rows, money=(3,), note=note)
        if p.kind == "RECONCILIATION" and rows:
            dr = sum(a for _l, s, a in rows if s == "Debit")
            cr = sum(a for _l, s, a in rows if s == "Credit")
            ws.cell(row=last + 1, column=1, value="Difference: debit less credit (must be nil)").font = BOLD
            ws.cell(row=last + 1, column=3, value=round(dr - cr, 2)).number_format = MONEY


def general_points_paper(ctx) -> None:
    """The general checks about one area (dividends v reserves, old debtors and bills, cash in hand), on its tab."""
    by_tab = {}
    for tab, gf in getattr(ctx, "general_points", None) or []:
        if tab in ctx.wb.sheetnames:
            by_tab.setdefault(tab, []).append(gf)
    for tab, points in by_tab.items():
        block(ctx.wb[tab], "Points to review (general checks)", ("Point", "Detail"),
              [(gf.title, gf.details) for gf in points])


PAPERS: List[Callable] = [general_points_paper, trade_adjustments_papers, sales_reconciliation_paper, payroll_summary_paper,
                          asset_details_paper, stock_lines_paper, yearend_adjustment_papers, added_papers]


def add_screen_papers(ctx) -> int:
    """Writes every paper this job has; returns how many could not be read (each noted for the report)."""
    if getattr(ctx, "db", None) is None or getattr(ctx, "engagement", None) is None:
        return 0
    failed = 0
    for paper in PAPERS:
        try:
            paper(ctx)
        except Exception as e:                  # one paper never stops the workbook
            failed += 1
            logger.warning("screen paper %s not written: %s", paper.__name__, e)
            try:
                ctx.db.rollback()
            except Exception:
                pass
            notes: Optional[list] = getattr(ctx, "report_notes", None)
            if notes is not None:
                notes.append(f"Workbook: the screen's {paper.__name__.replace('_', ' ')} could not be added ({e})"[:200])
    return failed
