"""Two working papers on screen, built from figures the app already has:

  Tax calculation   the corporation tax computation (tax/ct_computation.py) line by line, with the capital allowances
                    and what it is set against: the tax in the accounts
  Reserves          retained earnings: profit and loss account brought forward, the profit for the year, dividends,
                    carried forward; this year and last (last year from last year's job in the app when there is one)
"""

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup

DIVIDEND_CODES = (8010, 8011)       # final and interim dividends paid


def tax_calculation(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.tax.ct_computation import ct_computation
    tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    c = ct_computation(engagement, tb, db)
    line = lambda l: {"label": l.label, "amount": round(l.amount, 2), "box": l.box, "note": l.note}
    return {
        "lines": [line(l) for l in c.lines],
        "capital_allowances": [line(l) for l in c.capital_allowances],
        "corporation_tax": round(c.corporation_tax, 2), "s455_tax": round(c.s455_tax, 2),
        "total_tax": round(c.total_tax, 2), "tax_in_accounts": round(c.tax_in_accounts, 2),
        "difference": c.difference_to_accounts, "notes": c.notes,
    }


def _movement(bal: Dict[int, float], chart: ChartLookup) -> Dict[str, float]:
    """Brought forward, profit, dividends and carried forward from one year's final balances (credit +)."""
    reserve = -sum(v for c, v in bal.items() if chart.section(c) == "Profit and loss account" and c not in DIVIDEND_CODES)
    profit = -sum(v for c, v in bal.items() if chart.is_pl(c))
    dividends = sum(bal.get(c, 0.0) for c in DIVIDEND_CODES)
    return {"bf": round(reserve, 2), "profit": round(profit, 2), "dividends": round(dividends, 2),
            "cf": round(reserve + profit - dividends, 2)}


def reserves(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.review.last_year import last_year_job
    from backend.app.services.tax.ct_computation import final_balances
    chart = ChartLookup(db)
    tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    this_year = _movement(final_balances(str(engagement.id), tb, db), chart)
    last: Optional[Dict[str, float]] = None
    try:
        job = last_year_job(engagement, db)
    except Exception:
        job = None
    if job is not None:
        ly_tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == job.id)).scalars())
        if ly_tb:
            last = _movement(final_balances(str(job.id), ly_tb, db), chart)
    return {"this_year": this_year, "last_year": last,
            # Last year's carried forward should be this year's brought forward
            "difference": round(this_year["bf"] - last["cf"], 2) if last else None}
