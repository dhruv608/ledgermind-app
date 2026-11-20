"""Is the payroll report for this accounting year? One rule for the Data check and every payroll step of the review.

A report for another period is not read as this year's payroll: the client is asked for the right one (no payroll
file for the year: a client query for the payroll summary, and stop). Off period: 2 or more of its months fall
outside the year and it leaves 2 or more months of the year out at the start or the end (or has none inside it). This
stops a stale calendar-year report from being read as missing payroll for an April to March year. A month either side
is a pay date's lag, not another period; a report that covers the whole year and more is used for the year's
months."""

from datetime import date
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, PayrollP32Record

OFF_MONTHS = 2


def _key(d: date) -> int:
    return d.year * 12 + d.month - 1


def _said(k: int) -> str:
    return date(k // 12, k % 12 + 1, 1).strftime("%b %Y")


def off_period(engagement: ClientEngagement, records: List[PayrollP32Record]) -> Optional[str]:
    """Why the report is not this year's, or None when it is (or has no dates to tell)."""
    months = sorted({_key(r.period_end or r.period_start) for r in records if (r.period_end or r.period_start)})
    if not months:
        return None
    from backend.app.services.review.paye_check import _year
    start, end = _year(engagement)
    first, last = _key(start), _key(end)
    inside = [k for k in months if first <= k <= last]
    outside = [k for k in months if not first <= k <= last]
    if inside and len(outside) < OFF_MONTHS:
        return None
    if inside and min(inside) - first < OFF_MONTHS and last - max(inside) < OFF_MONTHS:
        return None
    return (f"The payroll report is for {_said(months[0])} to {_said(months[-1])}, not this year ({_said(first)} to "
            f"{_said(last)})")


def usable(engagement: ClientEngagement, db: Session) -> Tuple[List[PayrollP32Record], Optional[str]]:
    """The uploaded payroll rows, or none when the report is for another period (with the reason)."""
    records = db.query(PayrollP32Record).filter(PayrollP32Record.engagement_id == engagement.id).all()
    why = off_period(engagement, records)
    return ([] if why else records), why
