"""
Aged receivables / aged payables reports uploaded with a client's files (Xero or QuickBooks, summary or detail).

Reports are recognised by the title inside the file, not the file name (clients' file names can be swapped),
and the newest upload of each kind wins.
"""

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.app.services.ingestion.ingestion_service import parse_period_end

RECEIVABLES = re.compile(r"aged receivables|a/r ageing|receivables ageing|customer balance detail", re.IGNORECASE)
PAYABLES = re.compile(r"aged payables|a/p ageing|payables ageing|supplier balance detail", re.IGNORECASE)
BUCKET = re.compile(r"^(current|older|future|period \d+|<\s*1 month|\d+\s*months?|\d+\s*-\s*\d*\s*(days?)?|\d+\s*\+\s*(days?)?|"
                    r"\d+\s*and over|[<>]\s*\d+\s*days?)$", re.IGNORECASE)
OPEN_BALANCE = "open balance"   # QuickBooks balance detail: what is still owed on each line
# Sage listings: the amount still owed on each line (its 'Total' column is the invoice's full amount)
OUTSTANDING = ("o/s amt", "o/s amount", "outstanding", "amount outstanding", "amount due")
# Lines that total a section ('Total', 'Totals:', 'Supplier Totals') or the whole report ('Grand totals',
# 'Report Totals', 'Period Totals')
TOTAL_WORDS = re.compile(r"^([a-z]+\s+)?totals?:?$", re.IGNORECASE)
GRAND_TOTAL = re.compile(r"^(grand|report|period)\s+totals?:?$", re.IGNORECASE)


def _owed_column(header: List[Any]) -> Optional[int]:
    """The column of what is still owed on each line: Sage's 'O/S Amt' (its 'Total' is the invoice's full amount).
    A plain 'Outstanding' column beside the report's own Total or Open Balance was added by hand (what was still
    unpaid later), and is not the year-end figure."""
    names = [v.strip().lower() if isinstance(v, str) else "" for v in header]
    own_total = any(n in ("total", OPEN_BALANCE) for n in names)
    return next((j for j, n in enumerate(names) if n in OUTSTANDING and not (n == "outstanding" and own_total)), None)


def _total_column(header: List[Any]) -> Optional[int]:
    """The column holding each line's whole amount: Open Balance (QuickBooks), Total / Total O/S, else Balance (Sage 50)."""
    names = [v.strip().lower() if isinstance(v, str) else "" for v in header]
    for test in (lambda n: n == OPEN_BALANCE, lambda n: n == "total" or re.match(r"total\s+o/?s\b", n), lambda n: n == "balance"):
        found = next((j for j, n in enumerate(names) if test(n)), None)
        if found is not None:
            return found
    return None


def _dated(r: List[Any]) -> Optional[date]:
    """The line's date: Sage moves it one column left on some lines, so the first few cells are looked at."""
    return next((d for d in (_as_date(v) for v in r[:4]) if d), None)


@dataclass
class AgeingReport:
    kind: str                 # "AR" or "AP"
    file_name: str
    rows: List[List[Any]]     # the report exactly as uploaded (first sheet)
    as_at: Optional[date]
    total: Optional[float]    # grand total across the ageing buckets
    title_date: Optional[date] = None   # the date in the title, when it was wrong (see read_ageing_reports)


def _clean(v: Any) -> Any:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


def _grand_total(rows: List[List[Any]]) -> Optional[float]:
    header_idx = _header_row(rows)
    if header_idx is None:
        # An empty report (nothing owed) has a title but no ageing columns or amounts
        has_numbers = any(isinstance(v, (int, float)) for r in rows for v in r)
        return 0.0 if not has_numbers else None
    header = rows[header_idx]
    owed_col = _owed_column(header)
    if owed_col is not None:
        # Sage's own grand total line ('TOTAL', in capitals; each customer's own line is 'Total')
        grand = [r for r in rows[header_idx + 1:] if "TOTAL" in r and owed_col < len(r) and isinstance(r[owed_col], (int, float))]
        if grand:
            return round(float(grand[-1][owed_col]), 2)
        return round(sum(float(r[owed_col]) for r in rows[header_idx + 1:]
                         if owed_col < len(r) and isinstance(r[owed_col], (int, float)) and _dated(r)), 2)
    total_col = _total_column(header)
    buckets = [j for j, v in enumerate(header) if isinstance(v, str) and BUCKET.match(v.strip())]

    def row_amount(r: List[Any]) -> Optional[float]:
        if total_col is not None:
            v = r[total_col] if total_col < len(r) else None
            return float(v) if isinstance(v, (int, float)) else None
        values = [float(r[j]) for j in buckets if j < len(r) and isinstance(r[j], (int, float))]
        return sum(values) if values else None

    report_total, lines_total = None, 0.0
    for r in rows[header_idx + 1:]:
        first = next((v for v in r if v not in (None, "")), None)
        label = first.strip().lower() if isinstance(first, str) else ""
        # A total can sit in any column ('Grand totals' under the dates, a fee earner's 'Totals' mid-row)
        words = [v.strip() for v in r if isinstance(v, str) and TOTAL_WORDS.match(v.strip())]
        if label in ("total", "totals", "totals:") or any(GRAND_TOTAL.match(w) for w in words):
            report_total = row_amount(r)
        elif words or label.startswith(("total", "percentage")):
            continue  # sub-totals per contact or section, and the percentage line
        else:
            lines_total += row_amount(r) or 0.0
    # Xero exports leave their Total lines uncalculated (0), so add up the lines instead
    if report_total:
        return round(report_total, 2)
    return round(lines_total, 2)


def _header_row(rows: List[List[Any]]) -> Optional[int]:
    """The column headings: ageing buckets (Current, 1 Month...), or a balance detail's 'Open Balance'."""
    return next((i for i, r in enumerate(rows[:15])
                 if sum(1 for v in r if isinstance(v, str) and BUCKET.match(v.strip())) >= 3
                 or any(isinstance(v, str) and v.strip().lower() == OPEN_BALANCE for v in r)), None)


@dataclass
class OutstandingItem:
    contact: str
    when: Optional[date]        # invoice / bill date (None in a summary report: one line per contact)
    number: str                 # invoice / bill number ('' in a summary report)
    amount: float               # still outstanding at the report date
    kind: str = ""              # the report's transaction type ('bill', 'expense', 'deposit'), when it has one
    due: Optional[date] = None  # the due date, when the report gives it


def _as_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", v.strip()):
        d, m, y = (int(x) for x in v.strip().split("/"))
        try:
            return date(y, m, d)
        except ValueError:
            return None
    return None


def outstanding_items(report: AgeingReport) -> List[OutstandingItem]:
    """What each customer / supplier still owes or is owed at the report date. A detail report gives one item per
    invoice or bill (date, number, amount); a summary report gives one item per contact (the total only)."""
    rows = report.rows
    header_idx = _header_row(rows)
    if header_idx is None:
        return []
    header = [v.strip().lower() if isinstance(v, str) else "" for v in rows[header_idx]]
    col = lambda *names: next((j for j, h in enumerate(header) if h in names), None)
    owed_col = _owed_column(rows[header_idx])
    total_col = owed_col if owed_col is not None else _total_column(rows[header_idx])
    sage = owed_col is not None
    buckets = [j for j, h in enumerate(header) if BUCKET.match(h)]
    date_col = col("invoice date", "date")
    number_col = col("invoice number", "no.", "number", "invoice reference", "reference")
    contact_col = col("contact")
    type_col = col("transaction type", "type")
    due_col = col("due date", "due")

    def cell(r: List[Any], j: Optional[int]) -> Any:
        return r[j] if j is not None and j < len(r) else None

    def amount(r: List[Any]) -> Optional[float]:
        if total_col is not None:
            v = cell(r, total_col)
            return float(v) if isinstance(v, (int, float)) else None
        values = [float(r[j]) for j in buckets if j < len(r) and isinstance(r[j], (int, float))]
        return sum(values) if values else None

    items, contact = [], ""
    for r in rows[header_idx + 1:]:
        first = next((v for v in r if v not in (None, "")), None)
        if first is None:
            continue
        label = first.strip() if isinstance(first, str) else ""
        if label.lower().startswith(("total", "percentage", "[fx]", "all foreign values")):
            continue
        if sage and isinstance(first, str) and "credit limit" in first.lower():
            contact = first.split(",")[0].strip()      # 'ACME SUPPLIES LTD (ACM1), Credit limit: 0.00, ...'
            continue
        when = _as_date(cell(r, date_col)) if date_col is not None else None
        if when is None and sage:
            when = _dated(r)
        value = amount(r)
        if when is not None:                               # a detail line: one invoice / bill
            if value and abs(value) >= 0.01 and contact:
                number = cell(r, number_col)
                kind = str(cell(r, type_col) or "").strip().lower() if type_col is not None else ""
                items.append(OutstandingItem(contact, when, "" if number is None else str(number).strip(), round(value, 2),
                                             kind, _as_date(cell(r, due_col)) if due_col is not None else None))
        elif label and value is None:                      # a contact heading in a detail report
            contact = label
        elif label and value is not None and abs(value) >= 0.01:   # a summary line: contact and its total
            name = cell(r, contact_col) if contact_col is not None else label
            items.append(OutstandingItem(str(name or label).strip(), None, "", round(value, 2)))
    return items


CONTROL_CODES = {"AR": 4400, "AP": 5200}   # trade debtors / trade creditors


def read_ageing_reports(engagement_id: str, period_end: Optional[date] = None, tb_records=None) -> Dict[str, AgeingReport]:
    """The aged debtors / creditors reports uploaded with the client's files. With the year end and the trial balance,
    a report whose title shows another date but whose total agrees exactly with the books at the year end is taken as
    the year-end report: the title date is wrong."""
    found = _read_ageing_reports(engagement_id)
    if period_end is None or tb_records is None:
        return found
    for kind, report in found.items():
        if report.as_at in (None, period_end) or report.total is None:
            continue
        balance = abs(sum(float(t.net_amount or 0.0) for t in tb_records if t.std_code == CONTROL_CODES[kind]))
        if balance >= 0.01 and abs(abs(report.total) - balance) < 1.0:
            report.title_date, report.as_at = report.as_at, period_end
    return found


def _read_ageing_reports(engagement_id: str) -> Dict[str, AgeingReport]:
    from backend.app.core.s3 import s3_service
    from backend.app.services.shared.file_cache import digest, remember
    stored = s3_service.list_files(f"raw_uploads/{engagement_id}/")
    return remember("ageing", digest(*[part for n, b in stored for part in (n, b)]), lambda: _read_stored(stored))


def _read_stored(stored) -> Dict[str, AgeingReport]:
    import io
    import json
    found: Dict[str, AgeingReport] = {}
    # What each file (or tab) was taken as at upload: the accountant's choice is followed (a skipped tab is not
    # read). Uploads with no saved roles are read by their titles only
    roles: Dict[str, str] = {}
    for n, b in stored:
        if n == "_roles.json":
            try:
                roles = json.loads(b.decode())
            except ValueError:
                roles = {}
    from backend.app.services.ingestion.ingestion_service import with_formula_values
    files = [(n, with_formula_values(n, b)) for n, b in stored if n.lower().endswith((".xlsx", ".xls", ".csv"))]
    for fname, data in files:
        # Every tab: a prepared input file holds the reports as tabs beside the TB and ledger
        try:
            sheets = ({fname: pd.read_csv(io.BytesIO(data), header=None)} if fname.lower().endswith(".csv")
                      else pd.read_excel(io.BytesIO(data), header=None, sheet_name=None))
        except Exception:
            continue
        for i, (sheet, df) in enumerate(sheets.items()):
            rows = [[_clean(v) for v in r] for r in df.values.tolist()]
            if roles:
                # A tab of a combined workbook has its own role; a separate file is read from its first sheet
                role = roles.get(f"{sheet}.xlsx") if len(sheets) > 1 and f"{sheet}.xlsx" in roles else (
                    roles.get(fname) if i == 0 else None)
                kind = role if role in ("AR", "AP") else None
            else:
                title = " ".join(str(v) for r in rows[:6] for v in r if v is not None)
                kind = "AR" if RECEIVABLES.search(title) else "AP" if PAYABLES.search(title) else None
            if kind is None:
                continue
            as_at = next((d for d in (parse_period_end(" ".join(str(v) for v in r if v is not None)) for r in rows[:6]) if d), None)
            name = fname if len(sheets) == 1 else f"{fname} ({sheet})"
            found[kind] = AgeingReport(kind, name, rows, as_at, _grand_total(rows))
    return found


OVER_90_BUCKET = re.compile(r"^(older|3 months|9[01]\s*(and over|\+)|over 90|\d{3}\s*(and over|\+)|9[01]\s*-\s*\d+|1[2-9]\d\s*-\s*\d+|<\s*(1[2-9]\d|[2-9]\d\d)\s*days?)$",
                            re.IGNORECASE)


def over_90_days(report: AgeingReport, as_at: date) -> Dict[str, float]:
    """What each contact has had outstanding for more than 90 days: the report's '3 Months' / 'Older' /
    '91 and over' columns, or, for a balance detail with no ageing columns, lines dated more than 90 days before
    the report date."""
    rows = report.rows
    header_idx = _header_row(rows)
    if header_idx is None:
        return {}
    header = [v.strip().lower() if isinstance(v, str) else "" for v in rows[header_idx]]
    old_cols = [j for j, h in enumerate(header) if OVER_90_BUCKET.match(h)]
    out: Dict[str, float] = {}
    if old_cols:
        contact = ""
        for r in rows[header_idx + 1:]:
            first = next((v for v in r if v not in (None, "")), None)
            if first is None:
                continue
            label = first.strip() if isinstance(first, str) else ""
            if label.lower().startswith(("total", "percentage", "[fx]")):
                continue
            values = [float(r[j]) for j in old_cols if j < len(r) and isinstance(r[j], (int, float))]
            if not values and label:
                contact = label                       # a contact heading in a detail report
                continue
            name = label if label and not _as_date(first) else contact
            if values and name:
                out[name] = round(out.get(name, 0.0) + sum(values), 2)
    else:
        cutoff = as_at - timedelta(days=90)
        for item in outstanding_items(report):
            if item.when is not None and item.when <= cutoff:
                out[item.contact] = round(out.get(item.contact, 0.0) + item.amount, 2)
    return {k: v for k, v in out.items() if v >= 0.01}
