"""
CIS: what was filed with HMRC, typed per tax month, beside the books on a cash basis.

The figures come from the CIS300 monthly returns (contractor side), the contractors' payment and deduction statements
and the EPS (subcontractor side), and the HMRC PAYE / CIS account. They are kept in the reconciliation_inputs table
under "cis_hmrc:<tax month>", "cis_hmrc:year" and "cis_hmrc:mode". checks.py compares them with the books.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement
from backend.app.services.cis.cash import cis_cash, tax_month_number, tax_month_start, tax_year

MODES = ("MANUAL", "NOT_AVAILABLE")
FILED = ("YES", "NIL", "NO")
# Per tax month: contractor (CIS300), subcontractor (statements, EPS), PAYE and the HMRC account
MONEY_FIELDS = ("gross", "materials", "deducted", "suffered_statements", "claimed_eps",
                "paye_tax", "employer_nic", "employee_nic", "student_loan", "allowance", "paid_to_hmrc", "interest")
YEAR_MONEY_FIELDS = ("balance_bf", "balance_cf", "repayment_amount")
PREFIX = "cis_hmrc:"


def period_of(engagement: ClientEngagement) -> Tuple[date, date]:
    end = engagement.period_end_date
    if engagement.prior_period_end_date:
        return engagement.prior_period_end_date + timedelta(days=1), end
    start = date(end.year - 1, end.month, 28 if (end.month, end.day) == (2, 29) else end.day) + timedelta(days=1)
    return start, end


def tax_months(start: date, end: date) -> List[date]:
    """Every tax month (dated by its 6th) with a day in the period."""
    months, m = [], tax_month_start(start)
    last = tax_month_start(end)
    while m <= last:
        months.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 6)
    return months


def month_label(m: date) -> str:
    to = date(m.year + (m.month == 12), m.month % 12 + 1, 5)
    return f"{m:%d %b %Y} – {to:%d %b %Y}"


def _number(v: Any) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return round(float(str(v).replace(",", "").replace("£", "")), 2)
    except ValueError:
        raise ValueError(f"'{v}' is not an amount")


def _date(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    return date.fromisoformat(str(v)[:10]).isoformat()


def hmrc_screen(engagement: ClientEngagement, db: Session, setup_cis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from backend.app.services.reconciliation.control_accounts import entered_inputs
    cash = cis_cash(engagement, db, setup_cis or {})
    if not cash.on:
        return {"on": False}
    saved = {k[len(PREFIX):]: v for k, v in entered_inputs(db, engagement.id).items() if k.startswith(PREFIX)}
    books: Dict[str, Dict[str, float]] = {}
    for side in cash.sides:
        for m in side.months():
            books.setdefault(m["tax_month"], {})[side.name] = m["amount"]
    start, end = period_of(engagement)
    months = []
    for m in tax_months(start, end):
        key = m.isoformat()
        months.append({"tax_month": key, "label": month_label(m), "month_no": tax_month_number(m), "tax_year": tax_year(m),
                       "books": {"deducted": books.get(key, {}).get("deducted"), "suffered": books.get(key, {}).get("suffered")},
                       "hmrc": saved.get(key) or {}})
    # Cash in a tax month outside the period's months (e.g. paid on the 1st-5th after the year end) is shown too
    outside = sorted(set(books) - {m["tax_month"] for m in months})
    return {"on": True, "sides": [s.name for s in cash.sides], "mode": (saved.get("mode") or {}).get("mode", "MANUAL"),
            "months": months, "year": saved.get("year") or {}, "books_outside_months": {k: books[k] for k in outside}}


def save_hmrc(db: Session, engagement: ClientEngagement, body: Dict[str, Any], user_id: Optional[int]) -> None:
    """body: {mode?, months: {tax month: {field: value}}, year?: {...}}. An empty month removes it."""
    from backend.app.services.reconciliation.control_accounts import save_input
    start, end = period_of(engagement)
    allowed = {m.isoformat() for m in tax_months(start, end)}
    if body.get("mode") is not None:
        if body["mode"] not in MODES:
            raise ValueError("Unknown input mode")
        save_input(db, engagement.id, PREFIX + "mode", {"mode": body["mode"]}, user_id)
    for key, values in (body.get("months") or {}).items():
        if key not in allowed:
            raise ValueError(f"{key} is not a tax month of this period")
        clean: Dict[str, Any] = {}
        for f in MONEY_FIELDS:
            n = _number((values or {}).get(f))
            if n is not None:
                clean[f] = n
        filed = (values or {}).get("filed")
        if filed:
            if filed not in FILED:
                raise ValueError("Return filed must be Yes, Nil or No")
            clean["filed"] = filed
        if (values or {}).get("filed_on"):
            clean["filed_on"] = _date(values["filed_on"])
        if (values or {}).get("note"):
            clean["note"] = str(values["note"])[:300]
        save_input(db, engagement.id, PREFIX + key, clean or None, user_id)
    if body.get("year") is not None:
        y = body["year"] or {}
        clean = {f: _number(y.get(f)) for f in YEAR_MONEY_FIELDS if _number(y.get(f)) is not None}
        if y.get("repayment_date"):
            clean["repayment_date"] = _date(y["repayment_date"])
        save_input(db, engagement.id, PREFIX + "year", clean or None, user_id)
