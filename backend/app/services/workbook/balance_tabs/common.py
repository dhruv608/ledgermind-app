"""Shared parts of the balance sheet tabs: styles, the build context, ETB formula helpers, cells and ledger lines."""

from openpyxl.styles import Border, Font, PatternFill, Side
from typing import Callable, Dict, List, Optional, Tuple
from backend.app.services.mapping.chart_lookup import account_name_keys
from dataclasses import dataclass, field
from datetime import date, datetime
import re


INPUT_COLOUR = "FFF2CC"
INPUT_FILL = PatternFill(fill_type="solid", fgColor=INPUT_COLOUR)
MONEY = "#,##0.00;(#,##0.00);-"
BOLD = Font(name="Calibri", size=10, bold=True)
TITLE = Font(name="Calibri", size=12, bold=True)
TOTAL_BORDER = Border(top=Side(style="thin", color="000000"), bottom=Side(style="double", color="000000"))

BANK_CODES = list(range(4800, 4831))
LOANS_WITHIN_1_YEAR = [5000, 5005, 5010, 5015, 5100, 5110, 5120]
LOANS_AFTER_1_YEAR = [5001, 5002, 5006, 5007, 5011, 5012, 5016, 5017, 5500, 5510, 5520]
OTHER_DEBTORS = list(range(4420, 4430)) + list(range(4520, 4530))
S455_CODES = [4450, 4550]
DIVIDEND_CODES = [8010, 8011]

DEPOSIT_WORDS = re.compile(r"\bdeposit", re.I)
RESERVE_WORDS = re.compile(r"retained|profit and loss|p\s*&\s*l|reserve", re.I)
# Foreign currencies in a bank account's name (not GBP: "Revolut GBP Main" is a sterling account)
CURRENCY = re.compile(r"\b(USD|EUR|CAD|AUD|CHF|JPY|AED|INR|PLN|SEK|NOK|DKK)\b|[$€]", re.I)
BROUGHT_FORWARD = re.compile(r"^brought forward:", re.I)
OPENING_LINE = re.compile(r"opening balance", re.I)


@dataclass
class Context:
    wb: object
    client_name: str
    period_end: date
    tb_records: list
    tx_rows: list                      # (date 'dd/mm/yyyy', code, type, account, source, description, ref, debit, credit)
    opening_by_code: Dict[str, float]  # last year's balances by firm code (debit +), as on the ETB
    account_name: Callable[[int], str]
    tb_kind: str = ""                  # "movement" / "closing" when the ETB's movement is the ledger's (B1-ETB H:I)
    lead_rows: Dict[str, Dict[str, int]] = field(default_factory=dict)   # tab -> its lead lines' rows (lead_lines)
    s455_tax: float = 0.0
    s455_note: str = ""
    notes: List[str] = field(default_factory=list)
    statements: Dict[str, dict] = field(default_factory=dict)   # typed on the control accounts screen, "bank:4800"
    # The ledger's opening balances the TB could not take: {account: (amount debit +, account is in the TB)}
    gl_openings: Dict[str, Tuple[float, bool]] = field(default_factory=dict)
    # The loans register's agreements with their schedules: [(Agreement, Schedule)]
    agreements: list = field(default_factory=list)
    # Each lender's balance at last year's end on last year's working paper ({lender: owed}): shares out a balance last
    # year's TB keeps by code only (loans.last_year_loans)
    last_year_loans: Dict[str, float] = field(default_factory=dict)
    journals: list = field(default_factory=list)   # approved journals, one line each ({code, debit, credit, ...})
    # A schedule tab's carried-forward cell for the one code it covers ({4800: "'F3.1 - Bank'!D18"}): B1-ETB's
    # 'final less schedule c/fwd' column
    schedule_cf: Dict[int, Tuple[str, int]] = field(default_factory=dict)   # (cell, sign: 1 debit +, -1 owed +)
    # A read bank statement's lines against the books, by bank code (services/bank_statement.statement_match)
    statement_lines: Dict[int, dict] = field(default_factory=dict)
    period_start: Optional[date] = None    # the day after last year's TB date (a short period); None: 12 months


# ------------------------------------------------------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------------------------------------------------------
def period_start_formula(ctx) -> object:
    """The first day of the period for a b/fwd line: the day after last year's TB date when known (a short or long
    period after a change of year end), else twelve months before the year end."""
    start = getattr(ctx, "period_start", None)
    engagement = getattr(ctx, "engagement", None)
    if start is None and engagement is not None and getattr(engagement, "prior_period_end_date", None):
        from datetime import timedelta
        start = engagement.prior_period_end_date + timedelta(days=1)
    return start if start is not None else "=EDATE(YearEnd,-12)+1"


def _etb(codes, col: str) -> str:
    return "+".join(f"SUMIF('B1-ETB'!$A:$A,{c},'B1-ETB'!${col}:${col})" for c in codes) or "0"


def _etb_bf(codes) -> str:
    """The books' balance brought forward on B1-ETB: last year's filed TB (F-G) and the opening adjustment (O-P)."""
    return f"({_etb(codes, 'F')})-({_etb(codes, 'G')})+({_etb(codes, 'O')})-({_etb(codes, 'P')})"


def on_tab(title: str, term: str) -> str:
    """A formula term written on one tab, read from another: every cell reference gets the tab's name
    ("(E14-D14)" -> "('E2-Trade Debtors'!E14-'E2-Trade Debtors'!D14)"). A term that already names a tab stays."""
    if "!" in term:
        return term
    return re.sub(r"(?<![A-Za-z$!'])([A-Z]{1,2}\d+)(?![\d(])", lambda m: f"'{title}'!{m.group(1)}", term)


def _etb_movement(codes) -> str:
    """The year's movement on B1-ETB: the ledger's (H-I) and what of the TB the ledger does not explain (S)."""
    return f"({_etb(codes, 'H')})-({_etb(codes, 'I')})+({_etb(codes, 'S')})"


def _movement_label(ctx) -> str:
    return "Movement per GL" if getattr(ctx, "tb_kind", "") else "Movement per TTB"


CHECK_FILL = PatternFill("solid", fgColor="FFF2CC")       # a check that must be nil


def _criteria(text: str) -> str:
    """A SUMIFS text criterion that matches exactly (*, ? and ~ are wildcards in Excel)."""
    return '"' + re.sub(r"([*?~])", r"~\1", text).replace('"', '""') + '"'


def _ttb_account(code: int, name: str, col: str) -> str:
    return f"SUMIFS(TTB!${col}:${col},TTB!$A:$A,{code},TTB!$B:$B,{_criteria(name)})"


def _sheet_title(wb, ref: str, name: str) -> str:
    clean = re.sub(r"[\[\]:*?/\\']", " ", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    title = f"{ref} - {clean}"[:31].strip()
    n = 2
    while title in wb.sheetnames:
        suffix = f" ({n})"
        title = f"{ref} - {clean}"[:31 - len(suffix)].strip() + suffix
        n += 1
    return title


def _new_sheet(ctx: Context, title: str, after: List[str]):
    wb = ctx.wb
    anchor = next((n for n in after if n in wb.sheetnames), None)
    ws = wb.create_sheet(title, wb.sheetnames.index(anchor) + 1 if anchor else len(wb.sheetnames))
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 46
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 16
    return ws


def _blank(cell) -> None:
    """A template cell made empty before a tab is rewritten on it: its value, link, borders, fill, font and number
    format all go (clearing the value alone would leave the template's half boxes, date formats and links shown as
    text)."""
    if type(cell).__name__ == "MergedCell":
        return
    cell.value = None
    cell.hyperlink = None
    cell.border = Border(left=Side(), right=Side(), top=Side(), bottom=Side())
    cell.fill = PatternFill(fill_type=None)
    cell.font = Font()
    cell.number_format = "General"


def _money(cell, bold: bool = False, total: bool = False):
    cell.number_format = MONEY
    if bold:
        cell.font = BOLD
    if total:
        cell.border = TOTAL_BORDER
    return cell


def _input(cell, value=None):
    cell.value = value
    cell.fill = INPUT_FILL
    cell.number_format = MONEY
    return cell


def _when(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def _lines_for(ctx: Context, names: List[str]) -> List[tuple]:
    """Ledger lines of these accounts (matched on the name, with or without the software's code prefix), in date
    order; 'Opening balance' lines are last year's balance, already in b/fwd."""
    wanted = set()
    for n in names:
        wanted.update(account_name_keys(n))
    out = [tx for tx in ctx.tx_rows
           if any(k in wanted for k in account_name_keys(tx[3])) and not OPENING_LINE.search(f"{tx[4]} {tx[5]}")]
    return sorted(out, key=lambda tx: (_when(tx[0]) or date.min))


def _write_lines(ws, row: int, title: str, lines: List[tuple], debit_head: str, credit_head: str) -> int:
    ws.cell(row=row, column=1, value=title).font = BOLD
    row += 1
    for c, text in enumerate(["Date", "Description", "Reference", debit_head, credit_head], 1):
        ws.cell(row=row, column=c, value=text).font = BOLD
    first = row + 1
    for tx in lines:
        row += 1
        when = _when(tx[0])
        cell = ws.cell(row=row, column=1, value=when or tx[0])
        if when:
            cell.number_format = "dd/mm/yyyy"
        ws.cell(row=row, column=2, value=(tx[5] or tx[4] or "")[:120])
        ws.cell(row=row, column=3, value=tx[6] or None)
        if tx[7]:
            _money(ws.cell(row=row, column=4, value=round(tx[7], 2)))
        if tx[8]:
            _money(ws.cell(row=row, column=5, value=round(tx[8], 2)))
    if not lines:
        row += 1
        ws.cell(row=row, column=2, value="No ledger lines this year")
        return row + 2
    row += 1
    ws.cell(row=row, column=2, value="Total").font = BOLD
    for c, col in ((4, "D"), (5, "E")):
        _money(ws.cell(row=row, column=c, value=f"=SUM({col}{first}:{col}{row - 1})"), bold=True, total=True)
    return row + 2


def _records(ctx: Context, codes) -> list:
    wanted = set(codes)
    return [t for t in ctx.tb_records if t.std_code in wanted]


def _has_balance(ctx: Context, codes) -> bool:
    return any(abs(float(t.net_amount or 0)) >= 0.005 or abs(float(t.opening_amount or 0)) >= 0.005
               for t in _records(ctx, codes)) or any(abs(ctx.opening_by_code.get(str(c), 0.0)) >= 0.005 for c in codes)
