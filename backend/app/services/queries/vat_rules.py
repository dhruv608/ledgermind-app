"""VAT queries the review does not ask.

  VT-01 a VAT return of the year, due to be paid before the year end, with no HMRC payment or refund matched to it:
        'Has the Q.E. [date] return been paid?'. Matched as on G9 (the client's VAT summary's own
        payments when uploaded, else the HMRC lines on the VAT account); a return is due 1 month and 7 days after its
        period, so one ending in the last 70 days of the year is not asked.
  VT-02 cash accounting (standard or flat rate): an invoice or bill still open at the year end with no VAT, while the
        same customer's / supplier's other invoices carry VAT: the VAT on it is due (or claimed) when it is
        paid, so a missing VAT changes the next return. Each open item is found in the ledger (tax/open_items.py)."""

from datetime import timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement
from backend.app.services.queries.r1_rules import _money, _query

DUE_DAYS = 70          # reconciliations.PAID_WITHIN_DAYS: a return's payment up to 70 days after it ended
VAT_MIN = 1.0


def vat_queries(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    from backend.app.services.queries.query_list import CLIENT
    from backend.app.services.reconciliation.control_accounts import vat_paid_per_return
    from datetime import date
    ye = eng.period_end_date
    if ye is None:
        return []
    paid = vat_paid_per_return(eng, db)
    if not paid.get("source"):
        return []                                    # no VAT summary and no VAT account in the ledger: cannot tell
    start = ye.replace(year=ye.year - 1) if not (ye.month == 2 and ye.day == 29) else ye.replace(year=ye.year - 1, day=28)
    unpaid = []
    for r in paid["returns"]:
        end = date.fromisoformat(r["period_end"])
        if r.get("opening") or end <= start or end + timedelta(days=DUE_DAYS) > ye:
            continue
        owed, got = float(r["owed"] or 0), float(r["paid"] or 0)
        if abs(owed) >= VAT_MIN and abs(got) < VAT_MIN:
            unpaid.append((end, owed))
    if not unpaid:
        return []
    lines = [f"Q.E. {end:%d/%m/%Y}: {'refund of ' if owed < 0 else ''}{_money(abs(owed))}" for end, owed in unpaid]
    return [_query("VT-01", CLIENT, f"VAT returns with no payment seen: {len(unpaid)}",
                   "No payment to HMRC (or refund from HMRC) can be seen for these VAT returns. Has each one been paid "
                   "(or the refund received)? If it was paid from another account, please send the bank statement; "
                   "if it is still unpaid it stays owed in the accounts.",
                   sum(abs(o) for _e, o in unpaid), lines=lines, rule="VT-01")]


def open_item_vat_queries(eng: ClientEngagement, profile, tb, lines) -> List[Dict[str, Any]]:
    """VT-02: on cash accounting, open invoices / bills with no VAT where the contact's other documents carry VAT."""
    from backend.app.services.ingestion.ageing_reports import outstanding_items, read_ageing_reports
    from backend.app.services.mapping.chart_lookup import VAT_CONTROL
    from backend.app.services.queries.query_list import CLIENT
    from backend.app.services.tax.open_items import (contacts_with_vat, documents_by_day, find_document,
                                                     ledger_documents, missing_vat)
    from backend.app.services.tax.vat_review import scheme_and_basis
    if not getattr(profile, "is_vat_registered", False):
        return []
    _scheme, basis = scheme_and_basis(getattr(profile, "vat_scheme", None))
    if basis != "CASH":
        return []
    reports = read_ageing_reports(str(eng.id), eng.period_end_date, tb)
    docs = ledger_documents(lines, VAT_CONTROL)
    found = []
    for side, word in (("AR", "invoice to"), ("AP", "bill from")):
        report = reports.get(side)
        with_vat = contacts_with_vat(docs, side)
        if report is None or not with_vat or report.as_at not in (None, eng.period_end_date):
            continue
        by_day = documents_by_day(docs, side)
        for it in outstanding_items(report):
            if missing_vat(it, find_document(it, by_day), with_vat):
                found.append((word, it))
    if not found:
        return []
    found.sort(key=lambda x: (-abs(x[1].amount), x[1].contact, x[1].number))
    lines_out = [f"{word} {it.contact}{' ' + it.number if it.number else ''} of {it.when:%d/%m/%Y}: "
                 f"{_money(it.amount)}" for word, it in found]
    return [_query("VT-02", CLIENT, f"Unpaid invoices and bills with no VAT: {len(found)}",
                   "These invoices and bills were still unpaid at the year end and have no VAT on them, although the "
                   "same customer's or supplier's other invoices carry VAT. On cash accounting the VAT is due (or "
                   "claimed) when they are paid, so please check whether each one should carry VAT before the next "
                   "return.", sum(abs(it.amount) for _w, it in found), lines=lines_out, rule="VT-02")]
