"""Patterns, helpers and result types the ledger file readers share."""

import calendar
import io
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd
from pydantic import BaseModel


# Balance sheet accounts kept on the credit side (liabilities, equity, reserves), by name: used for QuickBooks opening
# balances of accounts with no lines in the year, which show no side of their own
CREDIT_SIDE_NAME = re.compile(r"retained|earnings|reserve|share|capital|premium|loan|hire purchase|\bhp\b|finance lease|"
                              r"creditor|payable|accrual|deferred|provision|\bvat\b|paye|\bnic?\b|pension|tax|overdraft|"
                              r"director|suspense", re.I)

DEBIT_SIDE_NAME = re.compile(r"dividend|drawing|prepay|debtor|receivable|cost|equipment|vehicle|bike|computer|"
                             r"furniture|fixtures|property|stock|bank|cash", re.I)

REPORT_TITLES = [
    "trial balance", "general ledger", "aged payables", "aged receivables",
    "a/p ageing", "a/r ageing", "balance sheet", "profit and loss", "ttb movement",
    "general ledger detail", "aged payables summary", "aged receivables summary",
    "aged payables detail", "aged receivables detail"
]

# A report's own title on the line where the company name usually is ('Nominal Transactions', 'Supplier Balance
# Detail', 'Transaction Detail by Account'): not a company name
REPORT_TITLE_WORDS = re.compile(r"\b(transactions?|report|ledger|listing|summary|detail|balances?|ageing|aged|"
                                r"nominal|journal|statement|analysis|by account|movements?)\b", re.I)

COMPANY_SUFFIX = re.compile(r"\b(ltd|limited|llp|plc|cic|c\.i\.c|lp|t/a|t_a|trading as)\b", re.I)

# Which file's header date to trust for the period end (TB "as at" date is the year end; aged reports may be run later)
PERIOD_ROLE_PRIORITY = ["TB", "GL", "AP", "AR"]

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}

MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

MONTHS["sept"] = 9

MONTH_RE = r"(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")"

# What a file is. UNKNOWN: neither its content nor its name says; the upload screen asks the accountant
ROLES = ("TB", "GL", "AR", "AP")

# The one line a TB built from a ledger that does not balance carries its difference on
LEDGER_DIFFERENCE = "Ledger difference (the GL does not balance): suspense to clear"

UNKNOWN = "UNKNOWN"

SKIP = "SKIP"           # a tab of a combined workbook the accountant left out (notes, workings, last year's TB)

ROLE_LABELS = {"TB": "Trial balance", "GL": "General ledger", "AR": "Customer balances (debtors)",
               "AP": "Supplier balances (creditors)"}

class FilesNeedRoles(ValueError):
    """Some files could not be identified, or two look like the same report: the accountant says which is which.
    files: [{filename, role (or UNKNOWN), how}] for every file uploaded."""

    def __init__(self, files: List[Dict[str, str]], message: str):
        super().__init__(message)
        self.files = files

# Report titles: Xero, QuickBooks, and Sage ("Debtor Listing", "Creditor Listing")
AR_WORDS = re.compile(r"customer balance|customer ageing|customer aging|aged debtors|aged receivables|debtors? listing", re.I)

AP_WORDS = re.compile(r"supplier balance|vendor balance|supplier ageing|supplier aging|aged creditors|aged payables|creditors? listing", re.I)

# The VAT columns of a QuickBooks GL export in the newer layout ('VAT amount' / 'Tax amount', 'VAT code' / 'Tax code' /
# 'VAT rate'), whatever the capitals
VAT_AMOUNT_HEAD = re.compile(r"^(vat|tax) amount$", re.I)

VAT_CODE_HEAD = re.compile(r"^(vat|tax) (code|rate|name)$", re.I)

def _qb_vat_amount(row) -> Optional[float]:
    for k, v in row.items():
        if VAT_AMOUNT_HEAD.match(str(k).strip()) and pd.notna(v) and str(v).strip() not in ("", "nan"):
            try:
                return float(str(v).replace(",", "").replace("£", "").strip())
            except ValueError:
                return None
    return None

def _unique_headers(headers: List[str]) -> Tuple[List[str], bool]:
    """Column names made unique ('Debit', 'Debit (2)', ...) so each name picks one column, and whether any repeated.
    An extended TB repeats Debit / Credit under each group (opening, journals, final, P&L, balance sheet): with the
    names repeated, a row's 'Debit' would be several values."""
    seen: Dict[str, int] = {}
    out = []
    for h in headers:
        key = h.strip().lower()
        seen[key] = seen.get(key, 0) + 1
        out.append(h if seen[key] == 1 or key in ("", "nan", "none") else f"{h} ({seen[key]})")
    repeated = any(n > 1 for k, n in seen.items() if k not in ("", "nan", "none"))
    return out, repeated

def parse_period_end(text: str) -> Optional[date]:
    """Return the period END date from a report title line, e.g.
    'As at 30 September 2025', 'For the period 1 October 2024 to 30 September 2025',
    'April, 2025-March, 2026', 'January-December, 2025', 'Year Ended 31/12/2025'."""
    t = text.replace(",", " ")

    # Day Month Year (take the last one: the end of a 'from ... to ...' range)
    dmy = re.findall(rf"\b(\d{{1,2}})\s+({MONTH_RE})\.?\s+(\d{{4}})\b", t, re.IGNORECASE)
    if dmy:
        d, m, y = dmy[-1]
        try:
            return date(int(y), MONTHS[m.lower()], int(d))
        except ValueError:
            pass

    # Numeric dd/mm/yyyy (UK order)
    num = re.findall(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", t)
    if num:
        d, m, y = num[-1]
        try:
            return date(int(y), int(m), int(d))
        except ValueError:
            pass

    # Month ranges without days: 'April 2025-March 2026', 'January-December 2025' -> last day of the last month
    months = re.findall(rf"\b({MONTH_RE})\b", t, re.IGNORECASE)
    years = re.findall(r"\b(\d{4})\b", t)
    if months and years:
        y, m = int(years[-1]), MONTHS[months[-1].lower()]
        return date(y, m, calendar.monthrange(y, m)[1])
    return None

_SIMPLE_FORMULA = re.compile(r"^=\s*[-+(]*\s*[\d.,]+(\s*[-+*/]\s*[-+(]*\s*[\d.,]+\s*\)*)*\s*\)*\s*$")

def _number_of(formula: str) -> Optional[float]:
    """The value of a formula that is only numbers and + - * / ( ) ('=521.78', '=100+20.5'), else None."""
    import ast
    import operator
    text = formula.lstrip("=").replace(",", "").strip()
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.USub: operator.neg, ast.UAdd: operator.pos}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.operand))
        raise ValueError
    try:
        return round(ev(ast.parse(text, mode="eval")), 2)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        return None

def with_formula_values(fname: str, fbytes: bytes) -> bytes:
    """An .xlsx whose amounts are typed as formulas ('=521.78') and saved without their results (every amount reads
    as 0): each such cell gets its number as the saved value. Only those cells are changed; every other formula keeps
    its saved result, and other files are returned unchanged."""
    if not fname.lower().endswith(".xlsx"):
        return fbytes
    import zipfile
    cell = re.compile(r'<c ([^>]*?)(?<!/)><f>([^<]*)</f>(?:<v>[^<]*</v>|<v\s*/>)?</c>')

    def fix(m):
        formula = "=" + m.group(2).replace("&amp;", "&")
        number = _number_of(formula) if _SIMPLE_FORMULA.match(formula) else None
        if number is None:
            return m.group(0)
        attrs = re.sub(r'\s*\bt="[^"]*"', "", m.group(1))
        return f'<c {attrs}><v>{number!r}</v></c>'
    try:
        with zipfile.ZipFile(io.BytesIO(fbytes)) as z:
            parts = {n: z.read(n) for n in z.namelist()}
        changed = False
        for n, data in parts.items():
            if n.startswith("xl/worksheets/") and n.endswith(".xml") and b"<f>" in data:
                text = data.decode("utf-8")
                new_text = cell.sub(fix, text)
                if new_text != text:
                    parts[n], changed = new_text.encode("utf-8"), True
        if not changed:
            return fbytes
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for n, data in parts.items():
                z.writestr(n, data)
        return out.getvalue()
    except Exception:
        return fbytes

class NormalizedEngagementData(BaseModel):
    client_name: str
    period_end_date: date
    prior_period_end_date: Optional[date] = None
    source_system: str
    tb_df: pd.DataFrame
    gl_df: pd.DataFrame
    ap_df: Optional[pd.DataFrame] = None
    ar_df: Optional[pd.DataFrame] = None

    class Config:
        arbitrary_types_allowed = True


# A trial balance column holding the firm's code for each account beside the client's own code ('Account Code' 1200
# and 'Taxcalc Code' 4802, or 'Final code')
FIRM_CODE_HEADING = re.compile(r"^\s*(tax\s?calc(\s+code)?|final\s+code|firm\s+code|tc\s+code)\s*$", re.I)


def firm_code_of(value) -> Optional[int]:
    """The firm code in a cell: 4802, '4802', 4802.0, '5400 A' (a director's sub-account of 5400); None if blank."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    m = re.match(r"\s*(\d{1,4})(?:\.0+)?(?:\s*[A-Za-z]?)\s*$", str(value))
    return int(m.group(1)) if m else None
