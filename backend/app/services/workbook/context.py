"""What every part of the workbook build shares (BuildContext), and the helpers several sections use: removing a
template tab, a firm code's account name, the aged lists, a control account's sub-ledger, the E3 / G10 summary."""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from openpyxl.styles import Border, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.ingestion.ageing_reports import AgeingReport

logger = logging.getLogger(__name__)


@dataclass
class BuildContext:
    wb: Any
    engagement: ClientEngagement
    db: Optional[Session]
    tb_records: List[TBRecord]
    client_name: str
    ye_str: str
    bold_font: Font
    accounting_total_border: Border
    ageing: Dict[str, AgeingReport]
    journals: List[Dict[str, Any]] = field(default_factory=list)       # approved journals, one line each
    removed_sheets: List[str] = field(default_factory=list)             # template tabs this client does not need
    last_year_by_code: Dict[str, float] = field(default_factory=dict)  # last year's final per firm code (B1-ETB T)
    report_notes: List[str] = field(default_factory=list)               # problems listed with the QA result
    general_points: list = field(default_factory=list)   # (tab, general check) about one area: on its tab (screen_papers)
    # Filled as the build goes: the TB as (code, name, debit, credit), the codes it uses, the firm chart's short
    # names, and the ledger lines (date 'dd/mm/yyyy', code, type, account, source, description, ref, debit, credit)
    tb_account_list: List[tuple] = field(default_factory=list)
    ttb_rows: List[tuple] = field(default_factory=list)      # the TTB tab's rows: the list less nil brought-forward lines
    tb_codes_present: Set[str] = field(default_factory=set)
    etb_codes: List[Any] = field(default_factory=list)                   # the accounts on the ETB, in order
    opening_by_code: Dict[str, float] = field(default_factory=dict)       # last year's balances by firm code
    tb_kind: str = ""               # "movement" / "closing" when the ETB reads the movement from the ledger
    chart_names: Dict[int, str] = field(default_factory=dict)
    tx_rows: List[tuple] = field(default_factory=list)
    gl_links: List[tuple] = field(default_factory=list)       # tabs' lines to link to the GL (gl_links.py)
    # A schedule tab's c/fwd cell for the one code it covers and its sign against the ETB (1: debit +, -1: owed +),
    # for B1-ETB's 'final less schedule c/fwd' column
    schedule_cf: Dict[int, Tuple[str, int]] = field(default_factory=dict)

    def remove_sheet(self, name: str) -> None:
        if name in self.wb.sheetnames:
            self.removed_sheets.append(name)
            del self.wb[name]

    def account_name(self, code: Any) -> str:
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            return str(code)
        if code_int in self.chart_names:
            return self.chart_names[code_int]
        return next((n for c, n, _, _ in self.tb_account_list if c == str(code_int)), f"Account {code_int}")


def format_std_code(val: Any) -> str:
    if val is None or val == "" or str(val).strip() == "":
        return "1999"
    try:
        return str(int(str(val).split(".")[0]))
    except (ValueError, TypeError):
        return str(val).strip()


def code_sort_key(code: Any):
    try:
        return (0, int(code), "")
    except (TypeError, ValueError):
        return (1, 0, str(code))


# The general ledger tab; the template names its sheet 'General Ledger Detail', renamed on load
GL_TAB = "General Ledger"
TEMPLATE_GL_TAB = "General Ledger Detail"


def short_chart_names(db: Session) -> Dict[int, str]:
    """The firm chart's names without the bracketed section ('Bank charges (Administrative expenses)' -> 'Bank charges')."""
    from sqlalchemy import select
    from backend.app.models.database import MasterCOA
    return {c.std_code: re.sub(r"\s*\(.*?\)\s*$", "", c.std_name).strip() for c in db.execute(select(MasterCOA)).scalars().all()}


# ------------------------------------------------------------------------------------------------------------------
# Aged debtors / creditors reports uploaded with the client's files
# ------------------------------------------------------------------------------------------------------------------
def write_ageing_report(ctx: BuildContext, sheet: str, report: Optional[AgeingReport], title: str, ref: str) -> None:
    wb = ctx.wb
    if sheet not in wb.sheetnames:
        return
    ws = wb[sheet]
    for row in ws.iter_rows():
        for cell in row:
            cell.value = None
            cell.hyperlink = None
    if report is None:
        ws["A1"] = title
        ws["A2"] = "=A!B2"
        ws["A6"] = f"No {title.lower()} report was uploaded for this client."
        ws["H1"] = ref
        return
    # The listing of open items first, then the report exactly as uploaded under it
    from backend.app.services.workbook.open_item_listing import write_listing
    start = 1
    try:
        listed = write_listing(ws, report, ctx, top=4)
    except Exception:
        logger.exception("Open item listing not written")
        listed = 4
    if listed > 4:
        ws["A1"], ws["A2"] = "=A!B2", "='Notes & Queries'!A2"
        ws.cell(row=1, column=12, value=ref)
        ws.cell(row=listed + 1, column=1, value="The report as uploaded").font = Font(name="Calibri", size=10, bold=True)
        start = listed + 2
    for r_idx, values in enumerate(report.rows, start):
        for c_idx, value in enumerate(values, 1):
            if value is not None:
                ws.cell(row=r_idx, column=c_idx, value=value)
    if start == 1 and ref not in (report.rows[0] if report.rows else []):
        ws.cell(row=1, column=max(len(v) for v in report.rows) + 2, value=ref)


def reconcile_ageing(ctx: BuildContext, sheet: str, report: Optional[AgeingReport], kind: str, code: int,
                     top: int = 16) -> None:
    """The aged report's total at C{top}, and a note on it at A{top + 2}."""
    ws = ctx.wb[sheet]
    engagement, report_notes = ctx.engagement, ctx.report_notes
    note = f"A{top + 2}"
    ws[f"C{top}"] = report.total if report is not None and report.total is not None else None
    balance = sum(float(t.net_amount or 0.0) for t in ctx.tb_records if t.std_code == code)
    if report is None and abs(balance) >= 0.01:
        ws[note] = f"No aged {kind} report uploaded - balance not agreed to a listing."
        report_notes.append(f"No aged {kind} report uploaded")
    elif report is None:
        ws[note] = f"No aged {kind} report uploaded (balance is nil)."
    elif report.title_date:
        ws[note] = (f"Note: the aged {kind} report's title says {report.title_date:%d/%m/%Y}, but its total agrees "
                     f"with the books at the year end {engagement.period_end_date:%d/%m/%Y}, so it is used as the "
                     f"year-end report (the title date is wrong).")
        report_notes.append(f"Aged {kind} report titled {report.title_date:%d/%m/%Y} used as the year-end report (total agrees)")
    elif report.as_at and report.as_at != engagement.period_end_date:
        ws[note] = (f"Note: the aged {kind} report is dated {report.as_at:%d/%m/%Y}, "
                     f"not the year end {engagement.period_end_date:%d/%m/%Y}.")
        report_notes.append(f"Aged {kind} report dated {report.as_at:%d/%m/%Y}, not the year end")


# ------------------------------------------------------------------------------------------------------------------
# A control account's nominal ledger tab, and the E3 / G10 summary
# ------------------------------------------------------------------------------------------------------------------
UNMAPPED = "9999"
# A ledger tab's accounts by name, for lines whose account has no firm code yet
LEDGER_NAMES = {
    "debtor": r"trade debtors?|accounts receivable|debtors? control|^debtors?\b(?!.*prepay)",
    "prepayment": r"prepayment",
    "bank": r"\bbank\b(?!.*(charge|fee|interest|loan))|current a/?c|current account|savings|deposit account",
    "creditor": r"trade creditors?|accounts payable|creditors? control|"
                r"^creditors?\b(?!.*(wage|paye|\bni\b|vat|director|accrual|nest|pension|corporation|loan|tax))",
    "director": r"directors?'?s?'? ?(loan|current) ?(account|a/?c)?|directors?'?s?'? ?(account|acc|a/?c)\b|\bdla\b",
    "accrual": r"accrual",
    "wage": r"net wages|wages (payable|control)|salaries payable",
    "paye": r"paye|\bni (payable|liability)|hmrc ?- ?paye",
    "vat": r"\bvat\b",
    "stock": r"\bstocks?\b|inventor",
}


TYPE_COL, TYPE_HEAD = 14, "DLA type"          # column N of the director's loan ledger (G3.1)
# The director's loan, line by line (each type on its own line of the T-account)
DLA_TYPES = (
    ("Dividends credited", re.compile(r"\bdividends?\b|\bdivs?\b", re.I)),
    ("Net salary credited", re.compile(r"\bsalar(y|ies)\b|\bwages?\b|net pay|payroll", re.I)),
    ("Use of home", re.compile(r"use of home|\bwfh\b|working from home|home office", re.I)),
    ("Mileage claimed", re.compile(r"mileage|\bamap\b|business miles", re.I)),
    ("Interest", re.compile(r"\binterest\b", re.I)),
)
CREDITED_TYPES = {"Dividends credited", "Net salary credited", "Use of home", "Mileage claimed"}
DLA_DRAWINGS = "Drawings and payments to the director"
DLA_INTRODUCED = "Money introduced"
# Costs the director paid for the company, apart from money put in. A credit to the loan from an
# expense, bill or cheque the ledger posted with the loan account as the way it was paid
DLA_EXPENSES = "Expenses paid personally for the company"
EXPENSE_SOURCE = re.compile(r"^\s*(expense|bill|purchase|cheque|check|credit card expense|supplier invoice|"
                            r"payable invoice|spend money)\b", re.I)
DLA_TYPE_ORDER = (DLA_DRAWINGS, DLA_INTRODUCED, DLA_EXPENSES) + tuple(t for t, _ in DLA_TYPES)


def dla_type(tx) -> str:
    """The type of a director's loan ledger line (date, code, type, account, source, description, ref, debit, credit)."""
    text = f"{tx[4]} {tx[5]} {tx[6]}"
    paid_out = float(tx[7] or 0) > float(tx[8] or 0)
    for label, words in DLA_TYPES:
        # Dividends, salary, use of home and mileage are credited to the director: a debit that names them is money
        # paid out to the director, not a credit
        if words.search(text) and not (paid_out and label in CREDITED_TYPES):
            return label
    if paid_out:
        return DLA_DRAWINGS
    return DLA_EXPENSES if EXPENSE_SOURCE.search(str(tx[4] or "")) else DLA_INTRODUCED


# A control tab's ledger columns written from the GL line, by the GL tab's heading (the code in B stays a value: the
# leads sum by it)
SUBLEDGER_FROM_GL = {1: "Date", 4: "Account Name", 5: "Source", 6: "Description", 7: "Reference", 8: "Debit",
                     9: "Credit"}


def note_gl_line(ctx, ws, row, tx, cols):
    from backend.app.services.workbook.gl_links import note_gl_line as note
    note(ctx, ws, row, tx, cols)


def rebuild_control_subledger(
    ctx: BuildContext,
    sheet_name: str,
    target_codes: Set[str],
    keyword_match: str,
    account_title: str,
    line_filter=None,
    type_of=None,
):
    """
    Clears the template's rows from row 7 down and writes this client's ledger lines for the control account.
    type_of(tx): a type written in column TYPE_COL for each line (the director's loan: drawings, salary,
    dividends ...), which the lead sums by.
    """
    wb, bold_font = ctx.wb, ctx.bold_font
    if sheet_name not in wb.sheetnames:
        return

    ws = wb[sheet_name]
    ws["A1"] = ctx.client_name
    ws["A2"] = ctx.ye_str
    if ws["A4"].value:
        ws["A4"] = f"{account_title} - Nominal Ledger"

    # 1. Clear every row from row 7 down (the template's example rows)
    max_r = max(ws.max_row, 30)
    max_c = max(ws.max_column, 14)
    for r in range(7, max_r + 2):
        for c in range(1, max_c + 1):
            ws.cell(row=r, column=c).value = None

    # 2. This client's GL lines, by the firm code the account is mapped to. The account name (a
    # pattern) only decides for a line whose account has no code yet (not in the TB, or still unmapped, 9999): as a
    # plain word 'bank' would take Bank charges, 'director' Directors' remuneration, 'wage' the Wages expense
    name_pattern = LEDGER_NAMES.get(keyword_match, keyword_match)
    matching_txs = [
        tx for tx in ctx.tx_rows
        if (line_filter(tx) if line_filter else
            (tx[1] in target_codes) or (tx[1] in ("", UNMAPPED) and bool(name_pattern)
                                        and re.search(name_pattern, tx[3], re.I) is not None))
    ]

    if not matching_txs:
        ws.cell(row=7, column=1, value="No transactions in period")
        return

    for idx, tx in enumerate(matching_txs):
        r = 7 + idx
        # (dt_str, acc_code, acc_type, acc, src, desc, ref, deb, cred)
        ws.cell(row=r, column=1, value=tx[0]) # Date
        ws.cell(row=r, column=2, value=int(tx[1]) if str(tx[1]).isdigit() else tx[1])  # Code (lead sheets sum by it)
        ws.cell(row=r, column=3, value=tx[2]) # Type
        ws.cell(row=r, column=4, value=tx[3]) # Name
        ws.cell(row=r, column=5, value=tx[4]) # Source
        ws.cell(row=r, column=6, value=tx[5]) # Description
        ws.cell(row=r, column=7, value=tx[6]) # Reference
        ws.cell(row=r, column=8, value=tx[7] if tx[7] != 0 else None) # Debit
        ws.cell(row=r, column=9, value=tx[8] if tx[8] != 0 else None) # Credit
        note_gl_line(ctx, ws, r, tx, SUBLEDGER_FROM_GL)

    tot_r = 7 + len(matching_txs)
    if type_of is not None:
        ws.cell(row=6, column=TYPE_COL, value=TYPE_HEAD).font = bold_font
        for idx, tx in enumerate(matching_txs):
            ws.cell(row=7 + idx, column=TYPE_COL, value=type_of(tx))
        ws.column_dimensions[get_column_letter(TYPE_COL)].width = 34
    ws.cell(row=tot_r, column=6, value="TOTAL").font = bold_font
    ws.cell(row=tot_r, column=8, value=f"=SUM(H7:H{tot_r-1})").font = bold_font
    ws.cell(row=tot_r, column=9, value=f"=SUM(I7:I{tot_r-1})").font = bold_font
    heads = {c: str(ws.cell(row=6, column=c).value or "").strip().lower() for c in range(1, max_c + 1)}
    # The ledger's VAT on each line and its code, when it has them
    vat_col = next((c for c, h in heads.items() if h == "vat"), None)
    code_col = next((c for c, h in heads.items() if h in ("vat rate name", "vat code")), None)
    vat_from_gl = {c: h for c, h in ((vat_col, "VAT"), (code_col, "VAT code")) if c}
    for idx, tx in enumerate(matching_txs):
        if vat_from_gl:
            note_gl_line(ctx, ws, 7 + idx, tx, vat_from_gl)
        if vat_col and len(tx) > 9 and tx[9] is not None:
            ws.cell(row=7 + idx, column=vat_col, value=tx[9])
        if code_col and len(tx) > 10 and tx[10]:
            ws.cell(row=7 + idx, column=code_col, value=tx[10])
    # The running balance of each account: its opening on the ETB (last year's filed TB) plus the debits
    # less the credits to date, so the account's last line is its closing balance per the books
    run_col = next((c for c, h in heads.items() if "running" in h), None)
    if run_col:
        for r in range(7, tot_r):
            ws.cell(row=r, column=run_col, value=(
                f"=SUMIF('B1-ETB'!$A:$A,$B{r},'B1-ETB'!$F:$F)-SUMIF('B1-ETB'!$A:$A,$B{r},'B1-ETB'!$G:$G)"
                f"+SUMIF($B$7:$B{r},$B{r},$H$7:$H{r})-SUMIF($B$7:$B{r},$B{r},$I$7:$I{r})")
            ).number_format = "#,##0.00;(#,##0.00);\"-\""
    # Columns the ledger gives nothing for (VAT, net, VAT rate when the export has none): no empty column left headed
    for c, h in heads.items():
        if h and c != run_col and c > 2 and all(ws.cell(row=r, column=c).value in (None, "") for r in range(7, tot_r)):
            ws.cell(row=6, column=c).value = None


def write_balance_summary(ctx: BuildContext, sheet_name: str, codes: List[str], credit: bool, detail_rows: List[int]) -> None:
    """The E3 / G10 summary: one line per account of this kind the client uses, this year from the ETB final
    balance and last year from its opening balance (credits shown as positive for accruals), total in E14/F14
    (read by the E1 / G1 lead). The template's detail lines (another client's) are cleared, headings kept."""
    wb = ctx.wb
    if sheet_name not in wb.sheetnames:
        return
    ws = wb[sheet_name]
    for r in list(range(8, 14)) + detail_rows:
        for c in range(1, 13):
            cell = ws.cell(row=r, column=c)
            if type(cell).__name__ == "MergedCell":
                continue
            cell.value = None
            cell.fill = PatternFill(fill_type=None)
    present = [c for c in codes if c in ctx.tb_codes_present]

    def etb(dr: str, cr: str, code: str) -> str:
        a, b = (cr, dr) if credit else (dr, cr)
        return (f"=SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!${a}:${a})"
                f"-SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!${b}:${b})")
    for i, code in enumerate(present[:5]):
        r = 9 + i
        ws.cell(row=r, column=2, value=f"{ctx.account_name(code)} ({code})")
        ws.cell(row=r, column=5, value=etb("L", "M", code)).number_format = "#,##0.00;(#,##0.00);\"-\""
        ws.cell(row=r, column=6, value=etb("F", "G", code)).number_format = "#,##0.00;(#,##0.00);\"-\""
    for col in ("E", "F"):
        total = ws[f"{col}14"]
        total.value = f"=SUM({col}9:{col}13)"
        total.font = ctx.bold_font
        total.number_format = "#,##0.00;(#,##0.00);\"-\""
        total.border = ctx.accounting_total_border
    _balance_movement(ctx, ws, present, credit)


def _balance_movement(ctx: BuildContext, ws, codes: List[str], credit: bool) -> None:
    """Below the E3 / G10 summary: the balance's b/fwd (last year's filed TB), the movement per GL, the
    approved journals and the c/fwd per the ETB, with a nil check; in place of the template's empty detail table."""
    if not codes:
        return
    for r in range(16, 41):
        for c in range(1, 9):
            cell = ws.cell(row=r, column=c)
            if type(cell).__name__ != "MergedCell":
                cell.value = None
    # The balance's year as one T with its lines named (prepayments and accruals each their own paper): b/f, the year's ledger lines by name, the journals by name (b/f released, new ones posted), c/d,
    # tied to B1-ETB, below the summary by code (rows 6-14, which the leads read)
    from backend.app.services.workbook.balance_tabs.t_shape import t_account
    ws.cell(row=16, column=1, value="Movement in the year").font = ctx.bold_font
    t_account(ctx, ws, [int(c) for c in codes], top=17, owed=credit)
