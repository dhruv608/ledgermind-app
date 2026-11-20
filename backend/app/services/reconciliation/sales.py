"""The VAT sales reconciliation: sales per the VAT returns (Box 6 for the year) to sales in the profit and loss account.

  Sales per VAT returns                               Box 6, a return straddling the year end by its days (V-F02)
  Net sales on outstanding closing debtors            cash accounting only: unpaid invoices are not on the returns yet
  Net sales on outstanding opening debtors            cash accounting only: last year's invoices paid this year, taken off
  Adjustments                                        journals approved in the app on the sales accounts
  Unidentified difference                             what is left
  Balance as per P&L                                  the sales accounts with the approved journals

Under cash accounting (Notice 731) Box 6 counts sales when paid, the accounts when invoiced: the trade debtors at the
year end are added and those at the start taken off, net of VAT at the standard rate (five sixths of the gross, as G9
takes a sixth for the VAT). Under the flat rate scheme Box 6 includes VAT, so the difference is not a true one."""

from datetime import timedelta
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord, VAT100Record
from backend.app.services.mapping.chart_lookup import ChartLookup

TRADE_DEBTORS = 4400
NET_OF_VAT = 5 / 6
r2 = lambda v: round(v, 2) + 0.0      # no -0.00


def sales_reconciliation(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.reconciliation.rows import _last_year_balances
    from backend.app.services.tax.ct_computation import final_balances
    from backend.app.services.tax.vat_review import _months_back, box6_in_year, scheme_and_basis

    ped = engagement.period_end_date
    year_start = (engagement.prior_period_end_date + timedelta(days=1)) if engagement.prior_period_end_date \
        else _months_back(ped, 12) + timedelta(days=1)
    scheme, basis = scheme_and_basis(getattr(getattr(engagement, "profile", None), "vat_scheme", None))
    chart = ChartLookup(db)
    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    final = final_balances(str(engagement.id), tb_records, db)
    tb: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code is not None:
            tb[t.std_code] = tb.get(t.std_code, 0.0) + float(t.net_amount or 0)
    sales_codes = [c for c in final if chart.section(c) == "Sales"]
    per_pl = -sum(final[c] for c in sales_codes)
    adjustments = -sum(final[c] - tb.get(c, 0.0) for c in sales_codes)     # the approved journals on sales

    returns = sorted((r for r in db.execute(select(VAT100Record).where(VAT100Record.engagement_id == engagement.id)).scalars()
                      if r.period_end and r.period_end >= year_start and (r.period_start or r.period_end) <= ped),
                     key=lambda r: r.period_end)
    spans, previous = [], None
    for r in returns:
        start = r.period_start or (previous + timedelta(days=1) if previous else _months_back(r.period_end, 3) + timedelta(days=1))
        spans.append((start, r.period_end, float(r.box6_total_sales_ex_vat or 0)))
        previous = r.period_end
    box6, covered = box6_in_year(spans, year_start, ped)
    year_days = (ped - year_start).days + 1
    box6_given = bool(spans) and all(abs(v) >= 0.005 for _, _, v in spans)

    cash = basis == "CASH"
    last = _last_year_balances(engagement, db, tb_records)
    closing_debtors = final.get(TRADE_DEBTORS, 0.0) * NET_OF_VAT if cash else 0.0
    opening_debtors = (float(last.get(TRADE_DEBTORS, 0.0)) if last is not None else 0.0) * NET_OF_VAT if cash else 0.0
    explained = box6 + closing_debtors - opening_debtors + adjustments
    lines: List[Dict[str, Any]] = [
        {"key": "box6", "label": "Sales per VAT returns", "amount": r2(box6),
         "note": f"Box 6 of {len(spans)} return(s), a return straddling the year end by its days"},
        {"key": "closing", "label": "Net sales on outstanding closing debtors", "amount": r2(closing_debtors),
         "note": "five sixths of the trade debtors at the year end (cash accounting)" if cash else "accruals basis: not needed"},
        {"key": "opening", "label": "Net sales on outstanding opening debtors", "amount": r2(-opening_debtors),
         "note": "five sixths of last year's trade debtors, taken off (cash accounting)" if cash else "accruals basis: not needed"},
        {"key": "adjustments", "label": "Adjustments", "amount": r2(adjustments),
         "note": "journals approved in the app on the sales accounts"},
        {"key": "unidentified", "label": "Unidentified difference", "amount": r2(per_pl - explained),
         "note": "to explain: zero-rated, exempt or outside-the-scope income, sales in other income, cut-off"},
        {"key": "pl", "label": "Balance as per P&L", "amount": r2(per_pl), "note": f"{len(sales_codes)} sales account(s)"},
    ]
    return {
        "lines": lines,
        "ready": box6_given and covered >= year_days - 31,
        "why_not": ("" if spans and box6_given and covered >= year_days - 31
                    else "No VAT returns for this year yet" if not spans
                    else "A return has no Box 6: type it on the VAT returns screen" if not box6_given
                    else "The returns do not cover the whole year"),
        "basis": basis, "flat_rate": scheme == "FLAT_RATE",
    }
