"""E2.2 / G2.2: the listing of open invoices and bills at the year end, one row per item of the
customer / supplier balance report: Customer (Supplier) | Invoice (Bill) no. | Date | Due date | Gross | VAT | Net |
Outstanding | Days old | Paid after year end | Flag.

Gross and VAT are the invoice's own, from its lines in the ledger (tax/open_items.py: the same contact on the same
day); net is gross less VAT; outstanding is what the report shows still owed. An invoice with no VAT while the
contact's other invoices carry VAT is red. On cash accounting the VAT on open items is not yet due
(VAT Notice 731: output tax when the customer pays, input tax when the bill is paid): the VAT column says so.
The listing's total is checked against the report's own total; the report as uploaded follows underneath."""

from datetime import date
from typing import List, Optional

from openpyxl.styles import Font, PatternFill

from backend.app.services.mapping.chart_lookup import VAT_CONTROL
from backend.app.services.tax.open_items import (contacts_with_vat, documents_by_day, find_document, ledger_documents,
                                                 missing_vat)

MONEY = '#,##0.00;(#,##0.00);"-"'
RED_ROW = PatternFill("solid", fgColor="FEE2E2")
CASH_NOTE = PatternFill("solid", fgColor="FEF3C7")
MAX_ROWS = 2000
CASH_SCHEMES = ("CASH", "FLAT_RATE_CASH")


def item_flags(item, ye: Optional[date], owed: bool, by_day, with_vat) -> List[str]:
    """The listing's flags: over 90 days old at the year end, a balance on the wrong side, and an invoice / bill with
    no VAT while the contact's other ones carry VAT."""
    flags = []
    days = (ye - item.when).days if (item.when and ye) else None
    if days is not None and days > 90 and abs(item.amount) >= 1:
        flags.append("Over 90 days")
    if item.amount <= -1:
        flags.append("Debit balance (the supplier owes the company)" if owed else
                     "Credit balance (the company owes the customer)")
    if with_vat and missing_vat(item, find_document(item, by_day), with_vat):
        flags.append("No VAT (the supplier's other bills carry VAT)" if owed else
                     "No VAT (the customer's other invoices carry VAT)")
    return flags


def write_listing(ws, report, ctx, top: int = 4) -> int:
    """The listing from row `top`; returns the next free row (the same row when the report gives no items)."""
    from backend.app.services.ingestion.ageing_reports import outstanding_items
    from backend.app.services.ingestion.next_year import next_year_lines
    from backend.app.services.review.paid_after import note_for, paid_after
    from backend.app.services.sop.common import gl_lines

    items = outstanding_items(report)
    if not items:
        return top
    owed = report.kind == "AP"
    engagement, db = ctx.engagement, ctx.db
    ye = engagement.period_end_date
    profile = getattr(engagement, "profile", None)
    vat_client = bool(getattr(profile, "is_vat_registered", False))
    cash = vat_client and (getattr(profile, "vat_scheme", "") or "") in CASH_SCHEMES
    side = "AP" if owed else "AR"
    docs = (ledger_documents(gl_lines(str(engagement.id), ctx.tb_records, db), VAT_CONTROL)
            if db is not None and vat_client else {})
    by_day, with_vat = documents_by_day(docs, side), contacts_with_vat(docs, side)
    later = [l for l in (next_year_lines(str(engagement.id), db) if db is not None else [])
             if ye is None or (l.when - ye).days <= 183]
    matched = paid_after(items, later, owed) if later else {}
    bold = Font(name="Calibri", size=10, bold=True)

    who, doc = ("Supplier", "Bill") if owed else ("Customer", "Invoice")
    ws.cell(row=top, column=1, value=f"Open {doc.lower()}s at the year end, from the {who.lower()} balance report").font = bold
    head = top + 2
    heads = [who, f"{doc} no.", "Date", "Due date", "Gross", "VAT", "Net", "Outstanding", "Days old",
             "Paid after year end", "Flag"]
    for c, h in enumerate(heads, 1):
        ws.cell(row=head, column=c, value=h).font = bold
    if cash:
        note = ws.cell(row=top + 1, column=6,
                       value=("Cash accounting: the VAT on these is not due until each is paid (VAT Notice 731); "
                              "check it is not already in the VAT account or the returns"))
        note.fill = CASH_NOTE
    r = head
    for n, item in enumerate(items[:MAX_ROWS]):
        r += 1
        found = find_document(item, by_day) if docs else None
        days = (ye - item.when).days if (item.when and ye) else None
        flags = item_flags(item, ye, owed, by_day, with_vat)
        ws.cell(row=r, column=1, value=(item.contact or "")[:80])
        ws.cell(row=r, column=2, value=item.number or None)
        for col, when in ((3, item.when), (4, getattr(item, "due", None))):
            if when:
                ws.cell(row=r, column=col, value=when).number_format = "dd/mm/yyyy"
        if found is not None:
            sign = -1 if item.amount < 0 else 1
            gross, vat = sign * round(found["gross"], 2), sign * round(abs(found["vat"]), 2)
            ws.cell(row=r, column=5, value=gross).number_format = MONEY
            ws.cell(row=r, column=6, value=vat).number_format = MONEY
            ws.cell(row=r, column=7, value=f"=E{r}-F{r}").number_format = MONEY
            if cash:
                ws.cell(row=r, column=6).fill = CASH_NOTE
        ws.cell(row=r, column=8, value=round(item.amount, 2)).number_format = MONEY
        ws.cell(row=r, column=9, value=days)
        if later:
            ws.cell(row=r, column=10, value=note_for(matched.get(n), True) or None)
        if flags:
            ws.cell(row=r, column=11, value="; ".join(flags))
            if any(f.startswith("No VAT") for f in flags):
                for c in range(1, 12):
                    ws.cell(row=r, column=c).fill = RED_ROW
    last = r
    if len(items) > MAX_ROWS:
        r += 1
        ws.cell(row=r, column=1, value=f"... and {len(items) - MAX_ROWS} more on the report below (not listed)")
    r += 1
    ws.cell(row=r, column=1, value="Total").font = bold
    for col in (5, 6, 7, 8):
        letter = "EFGH"[col - 5]
        ws.cell(row=r, column=col, value=f"=SUM({letter}{head + 1}:{letter}{last})").number_format = MONEY
        ws.cell(row=r, column=col).font = bold
    total_r = r
    if vat_client:
        ws.cell(row=r + 1, column=1, value=f"VAT on the open {doc.lower()}s (feeds the VAT reconciliation, G9)")
        ws.cell(row=r + 1, column=8, value=f"=F{total_r}").number_format = MONEY
        r += 1
    if report.total is not None and len(items) <= MAX_ROWS:
        ws.cell(row=r + 1, column=1, value="Total per the report")
        ws.cell(row=r + 1, column=8, value=round(float(report.total), 2)).number_format = MONEY
        ws.cell(row=r + 2, column=1, value="Check: listing v the report's total (must be nil)").font = bold
        ws.cell(row=r + 2, column=8, value=f"=ROUND(H{total_r}-H{r + 1},2)").number_format = MONEY
        r += 2
    return r + 1
