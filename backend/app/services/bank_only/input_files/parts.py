"""What each uploaded file or tab is (bank statement, sales, bills, last year's TB or listings)."""

from typing import Any, Dict, List, Optional, Tuple
import csv
from datetime import date, datetime, timedelta
import io
import openpyxl
import re

from backend.app.services.bank_only.input_files.common import (
    BankAccount, BankLine, DESC_WORDS, HEAD_COLUMN, IN_EXACT, OUT_EXACT, Problem, _date, _header, _money_columns,
    _title_values, RawInput)


# What a file or tab is, in the raw data route
BANK, SALES, BILLS, OPENING_TB, OPENING_SALES, OPENING_BILLS, SKIP = (
    "BANK", "SALES", "BILLS", "OPENING_TB", "OPENING_SALES", "OPENING_BILLS", "SKIP")
RAW_ROLES = (BANK, SALES, BILLS, OPENING_TB, OPENING_SALES, OPENING_BILLS)
ROLE_LABELS = {BANK: "Bank statement", SALES: "Sales invoices (Dext)", BILLS: "Purchase bills (Dext)",
               OPENING_TB: "Last year's closing TB", OPENING_SALES: "Last year's unpaid invoices",
               OPENING_BILLS: "Last year's unpaid bills", SKIP: "Skip"}
_LAST_YEAR = re.compile(r"opening|unpaid|listing|b/?f\b|brought forward|last year|prior year|\b20\d\d\b.*(tb|trial)", re.I)


def _parts(files_data: List[Tuple[str, bytes]]):
    """Every sheet of every file, named as the upload screen names it: the file name when the file has one sheet,
    '<sheet>.xlsx' when it has several (as for a combined workbook). Parsed once per set of files while the server
    runs (the Data check, the books and the queries read the same files)."""
    from backend.app.services.shared.file_cache import digest, remember
    key = digest(*[part for name, data in files_data for part in (name, data)])
    return remember("sheets", key, lambda: _read_parts(files_data), copy_out=False)


def _read_parts(files_data: List[Tuple[str, bytes]]):
    out = []
    for fname, fbytes in files_data:
        low = fname.lower()
        if low.endswith(".csv"):
            wb = openpyxl.Workbook()
            ws = wb.active
            for row in csv.reader(io.StringIO(fbytes.decode("utf-8-sig", errors="replace"))):
                ws.append([_csv_value(v) for v in row])
            out.append((fname, ws))
        elif low.endswith((".xlsx", ".xlsm")):
            wb = openpyxl.load_workbook(io.BytesIO(fbytes), data_only=True)
            sheets = [ws for ws in wb.worksheets if ws.max_row > 1]
            for ws in sheets:
                out.append((fname if len(sheets) == 1 else f"{ws.title}.xlsx", ws))
    return out


def _csv_value(v: str) -> Any:
    v = v.strip()
    if not v:
        return None
    d = _date(v)
    if d:
        return datetime(d.year, d.month, d.day)
    try:
        return float(v.replace(",", "").replace("£", ""))
    except ValueError:
        return v


def part_role(name: str, ws, year_end: Optional[date] = None) -> str:
    """What a sheet is, from its column headings (its name only to tell last year's lists from this year's)."""
    def has(*words):
        return _header(ws, list(words))[0] is not None
    named_last_year = bool(_LAST_YEAR.search(f"{name} {ws.title}"))
    hr, heads = _header(ws, ["date", DESC_WORDS])
    money = any(c is not None for c in _money_columns(heads)) if hr is not None else False
    if money and has("date", DESC_WORDS, "balance"):
        return BANK
    # Supplier first: a Dext purchases export also has a (rebilling) Customer column; a sales export has no Supplier
    for party, this_year, last_year in (("supplier", BILLS, OPENING_BILLS), ("customer", SALES, OPENING_SALES)):
        if has("date", party):
            if named_last_year or _all_before(ws, party, year_end):
                return last_year
            return this_year
    # A statement typed up without a balance column (a savings account's 'Paid In' only)
    if money and re.search(r"bank|statement|current|saver|saving|card", f"{name} {ws.title}", re.I):
        return BANK
    if (has("debit", "credit") or has("dr", "cr")) and not has("date") and any(
            has(w) for w in ("code", "account", "nominal", "name", "particulars", "description", "details")):
        return OPENING_TB
    return SKIP


def _all_before(ws, party: str, year_end: Optional[date]) -> bool:
    """Every invoice in the sheet is dated before the year started: last year's list."""
    if year_end is None:
        return False
    start = year_end.replace(year=year_end.year - 1) + timedelta(days=1)
    hr, heads = _header(ws, ["date", party])
    c = min((i for h, i in heads.items() if "date" in h and "due" not in h), default=None)
    dates = [_date(r[c]) for r in ws.iter_rows(min_row=hr + 1, values_only=True) if c is not None and c < len(r)]
    dates = [d for d in dates if d]
    return bool(dates) and all(d < start for d in dates)


def identify_parts(files_data: List[Tuple[str, bytes]]) -> List[Dict[str, str]]:
    """[{filename, role, how}] for every sheet, as the upload screen lists them."""
    parts = _parts(files_data)
    year_end = next((_date(_title_values(ws).get("year end", "")) for _, ws in parts
                     if _title_values(ws).get("year end")), None)
    return [{"filename": n, "role": (r := part_role(n, ws, year_end)), "how": "content" if r != SKIP else
             "not a bank statement, invoice list or trial balance"} for n, ws in parts]


# Money in / out columns a bank statement has and a ledger export does not (a ledger says Debit / Credit)
STATEMENT_IN_OUT = ("money in", "paid in", "in amount", "amount in", "money out", "paid out", "out amount",
                    "amount out", "withdrawal", "deposit")


# Columns only an accounting package's ledger has (QuickBooks 'Split' / 'Adj', the account named on each line, Xero's
# 'Source'): a bank statement never has them
LEDGER_COLUMNS = ("split", "adj", "account", "source", "nominal", "n/c")


def _titled_ledger(ws) -> bool:
    """A software export, not a statement: its title (above the headings) calls it a ledger or trial balance, or it has
    a ledger's own columns (the title is sometimes replaced by 'Client: ... / Year End ...')."""
    hr, heads = _header(ws, ["date", DESC_WORDS])
    title = " ".join(str(v) for r in ws.iter_rows(min_row=1, max_row=max((hr or 6) - 1, 1), values_only=True)
                     for v in r if v).lower()
    return bool(re.search(r"ledger|trial balance|nominal", title)) or any(h in LEDGER_COLUMNS for h in heads)


def looks_like_statement(ws) -> bool:
    """A bank (or credit card) statement, not a software ledger with the same Date | Description | Debit | Credit |
    Balance shape: the title above the headings says 'statement' (not 'ledger'), or the amounts are headed money in /
    money out rather than debit / credit."""
    hr, heads = _header(ws, ["date", DESC_WORDS])
    if hr is None or _titled_ledger(ws):
        return False
    title = " ".join(str(v) for r in ws.iter_rows(min_row=1, max_row=hr - 1, values_only=True) for v in r if v).lower()
    # Typed up by the client or the preparer: 'Client: ...' / 'Y.E. ...' above the headings, a head written against
    # each line, or in / out / signed amount columns
    _, _, signed = _money_columns(heads)
    return ("statement" in title or any(w in h for h in heads for w in STATEMENT_IN_OUT)
            or bool(re.search(r"client\s*[:\-–]|\by\.?\s*e\b\.?|year\s*end", title))
            or any(HEAD_COLUMN.match(h) for h in heads) or any(h in IN_EXACT + OUT_EXACT for h in heads)
            or signed is not None)


def is_raw_upload(files_data: List[Tuple[str, bytes]]) -> bool:
    """A client with no accounting software: a bank statement with invoice or bill lists (Bank + Dext), or bank and
    card statements alone (bank only), with no trial balance or ledger for this year. (A Xero/QuickBooks ledger has
    the shape of a statement, so on its own a sheet counts only when it reads as one: looks_like_statement.)"""
    try:
        parts = _parts(files_data)
        year_end = next((_date(_title_values(ws).get("year end", "")) for _, ws in parts
                         if _title_values(ws).get("year end")), None)
        roles = [(part_role(n, ws, year_end), ws) for n, ws in parts]
    except Exception:
        return False
    found = {r for r, _ in roles}
    banks = [ws for r, ws in roles if r == BANK]
    # A QuickBooks ledger has a statement's shape and its aged lists read like invoice lists: titled 'General Ledger',
    # it is a software export (with its TB), not a client's bank statement
    if BANK in found and (SALES in found or BILLS in found) and not all(_titled_ledger(ws) for ws in banks):
        return True
    # Bank and card statements alone: one reads as a statement and none is a software ledger (a card or e-money
    # account typed as Date | Description | Debit | Credit | Balance has a ledger's shape)
    return bool(banks) and any(looks_like_statement(ws) for ws in banks) and not any(_titled_ledger(ws) for ws in banks)


REPEATED_SHARE = 0.9        # a statement whose lines are nearly all on another one is that statement again
REPEATED_MIN_LINES = 5


def _drop_repeated_statements(out: "RawInput") -> None:
    """A statement uploaded twice (the same card as 'Amex' and again as 'Credit Card') is read once: every line
    recorded once (CA 2006 s386), not its card spending and receipts counted twice. The later one is left out and the data check says so. A transfer
    between two own accounts is money out on one and in on the other, so it never makes two statements look alike."""
    def line_key(b: BankLine) -> Tuple:
        return b.when, round(b.money_out, 2), round(b.money_in, 2), " ".join(b.description.lower().split())

    kept: List[BankAccount] = []
    for a in out.accounts:
        mine = [line_key(b) for b in a.lines]
        same = next((k for k in kept if len(mine) >= REPEATED_MIN_LINES and
                     sum(1 for x in mine if x in {line_key(b) for b in k.lines}) >= REPEATED_SHARE * len(mine)), None)
        if same is None:
            kept.append(a)
            continue
        out.problems.append(Problem("Bank", "MEDIUM", (
            f"{a.name} has the same lines as {same.name} ({len(mine)} lines): the same statement uploaded twice, so it "
            f"is read once, as {same.name}. If they are two different accounts, tell us."), blocks_upload=False))
    out.accounts = kept
