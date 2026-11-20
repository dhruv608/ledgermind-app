"""Debtors by age on the Balance sheet tab (Trade debtors row): the client's own aged receivables report put into the
same five boxes whatever software made it: not due, 1-30, 31-60, 61-90 and 91+ days.

The report's own age columns are used when it has them (Xero: Current, < 1 Month, 1 Month, 2 Months, 3 Months, Older;
QuickBooks: Current, 1 - 30, 31 - 60, 61 - 90, 91 and over; Sage: Current, Period 1..3, Older). A balance detail with
no age columns (QuickBooks Customer Balance Detail, Sage listings) is aged by each invoice's date at the report date."""

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.ingestion.ageing_reports import (BUCKET, _as_date, _header_row, outstanding_items,
                                                          read_ageing_reports)

BOXES = ["Not due", "1-30", "31-60", "61-90", "91+"]


def box_of(heading: str) -> Optional[int]:
    """Which of the five boxes a report's age column goes in (None: not an age column)."""
    h = heading.strip().lower()
    if not BUCKET.match(h):
        return None
    if h in ("current", "future") or "not due" in h:
        return 0
    if h == "older" or "over" in h or h.endswith("+"):
        return 4
    if h.startswith("<") and "month" in h:
        return 1                                     # Xero '< 1 Month': under a month overdue
    m = re.search(r"(\d+)\s*months?", h)
    if m:                                            # Xero '1 Month' / '2 Months' / '3 Months'
        return min(int(m.group(1)) + 1, 4)
    m = re.search(r"period\s*(\d+)", h)
    if m:                                            # Sage 'Period 1' .. 'Period 3'
        return min(int(m.group(1)), 4)
    m = re.match(r"[<>]?\s*(\d+)", h)
    if m:                                            # QuickBooks '1 - 30', '31 - 60', '61 - 90'
        start = int(m.group(1))
        return 1 if start <= 30 else 2 if start <= 60 else 3 if start <= 90 else 4
    return None


def _by_columns(rows: List[List[Any]], header_idx: int) -> Dict[str, List[float]]:
    header = [v.strip() if isinstance(v, str) else "" for v in rows[header_idx]]
    cols = {j: box_of(h) for j, h in enumerate(header) if h and box_of(h) is not None}
    contact_col = next((j for j, h in enumerate(header) if h.lower() == "contact"), None)
    out: Dict[str, List[float]] = {}
    contact = ""
    for r in rows[header_idx + 1:]:
        first = next((v for v in r if v not in (None, "")), None)
        if first is None:
            continue
        label = first.strip() if isinstance(first, str) else ""
        if label.lower().startswith(("total", "percentage", "[fx]", "all foreign values")):
            continue
        values = {j: float(r[j]) for j in cols if j < len(r) and isinstance(r[j], (int, float))}
        if not values:
            if label:
                contact = label                      # a customer heading in a detail report
            continue
        if contact_col is not None and isinstance(r[contact_col] if contact_col < len(r) else None, str):
            name = r[contact_col].strip()
        else:
            name = label if label and not _as_date(first) else contact
        if not name:
            continue
        boxes = out.setdefault(name, [0.0] * 5)
        for j, v in values.items():
            boxes[cols[j]] += v
    return out


def debtor_ageing(engagement: ClientEngagement, db: Session, kind: str = "AR") -> Dict[str, Any]:
    """Debtors by age from the aged receivables report ("AR"), or creditors by age from the aged payables ("AP", for
    the Purchases and creditors area, as the debtors' listing is on Sales and debtors)."""
    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    report = read_ageing_reports(str(engagement.id), engagement.period_end_date, tb_records).get(kind)
    if report is None:
        return {"report": None}
    return from_report(report, report.as_at or engagement.period_end_date)


def from_report(report, as_at) -> Dict[str, Any]:
    """The five boxes per customer from one aged receivables report (AgeingReport), aged at as_at."""
    rows, header_idx = report.rows, _header_row(report.rows)
    method, undated = "columns", 0.0
    customers: Dict[str, List[float]] = {}
    if header_idx is not None:
        customers = _by_columns(rows, header_idx)
    if not customers:
        # No age columns: each invoice by its age at the report date
        method = "dates"
        for item in outstanding_items(report):
            boxes = customers.setdefault(item.contact, [0.0] * 5)
            if item.when is None:
                undated += item.amount
                continue
            days = (as_at - item.when).days
            boxes[0 if days <= 0 else 1 if days <= 30 else 2 if days <= 60 else 3 if days <= 90 else 4] += item.amount
    out = []
    for name, boxes in customers.items():
        total = round(sum(boxes), 2)
        if abs(total) < 0.005 and all(abs(b) < 0.005 for b in boxes):
            continue
        out.append({"customer": name, "total": total, "boxes": [round(b, 2) for b in boxes]})
    out.sort(key=lambda c: -c["total"])
    totals = [round(sum(c["boxes"][i] for c in out), 2) for i in range(5)]
    return {
        "report": report.file_name,
        "as_at": as_at.isoformat() if as_at else None,
        "method": method,                     # "columns": the report's own ages; "dates": by invoice date
        "boxes": BOXES,
        "customers": out,
        "totals": totals,
        "total": round(sum(totals), 2),
        "report_total": report.total,         # the report's own grand total, to check against
        "undated": round(undated, 2),
        # Trade debtors / creditors listing: each invoice still open, by customer, with a total per customer
        # (a summary report has one line per customer only)
        "listing": _listing(report),
    }


def _listing(report) -> List[Dict[str, Any]]:
    by: Dict[str, List[Dict[str, Any]]] = {}
    for item in outstanding_items(report):
        by.setdefault(item.contact, []).append({
            "date": item.when.isoformat() if item.when else None, "type": item.kind, "number": item.number,
            "due": item.due.isoformat() if item.due else None, "amount": round(item.amount, 2)})
    out = [{"customer": name, "items": sorted(items, key=lambda i: i["date"] or ""),
            "total": round(sum(i["amount"] for i in items), 2)} for name, items in by.items()]
    return sorted([c for c in out if abs(c["total"]) >= 0.005 or len(c["items"]) > 1], key=lambda c: -c["total"])
