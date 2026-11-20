"""A VAT return (the VAT 100 boxes from HMRC, the bookkeeping software or the firm's VAT working) for a VAT-registered
sole trader (R-SA103-16). The output VAT the trader charges is not their income: they collect it for HMRC
(BIM31525), so the trade is worked net of VAT. The bank statements show takings and costs with VAT in them, so the
returns' box 1 (VAT due on sales) comes off the takings and box 4 (VAT reclaimed on purchases) off the costs; box 6
(net sales) is the check on the net turnover. Under the flat rate or the margin scheme box 1 is still what is owed to
HMRC, so the same holds.

A return in a company's name (a Ltd the person runs) is not the sole trade's: kept out, noted."""

import re
from typing import Any, Dict, List, Optional, Tuple

PROMPT = """This is a UK VAT return (VAT 100 boxes), a bookkeeping report of one, or an accountant's VAT working for
one return period. Reply with one JSON object only:
{"trader": "the business or person the return is for, as printed, or null",
 "vrn": "the VAT registration number or null",
 "period_from": "YYYY-MM-DD or null", "period_to": "YYYY-MM-DD or null",
 "scheme": "STANDARD", "FLAT_RATE", "MARGIN", "CASH" or "ANNUAL" (what the paper says; STANDARD when it does not say),
 "box1": number (VAT due on sales and other outputs), "box2": number, "box3": number (total VAT due),
 "box4": number (VAT reclaimed on purchases and other inputs), "box5": number (net VAT to pay or reclaim),
 "box6": number (total value of sales, excluding VAT), "box7": number (total value of purchases, excluding VAT),
 "box8": number, "box9": number}
Money as plain numbers (no £ or commas); a box not shown is null. Only one return: if several periods are shown, the
latest complete one."""

COMPANY = re.compile(r"\b(ltd|limited|plc|llp)\b", re.I)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return round(float(str(v).replace(",", "").replace("£", "").strip()), 2)
    except ValueError:
        return None


def clean(answer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    a = answer or {}
    f = {"trader": (a.get("trader") or "").strip() or None, "vrn": (a.get("vrn") or "").strip() or None,
         "period_from": a.get("period_from"), "period_to": a.get("period_to"),
         "scheme": str(a.get("scheme") or "STANDARD").upper()}
    for n in range(1, 10):
        f[f"box{n}"] = _num(a.get(f"box{n}"))
    return f


def overlap(f: Dict[str, Any], start: str, end: str) -> float:
    """The part of the return's period inside start..end (by days), 0 to 1."""
    from datetime import date
    try:
        a, b = date.fromisoformat(f["period_from"]), date.fromisoformat(f["period_to"])
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError, KeyError):
        return 0.0
    days = (b - a).days + 1
    inside = (min(b, e) - max(a, s)).days + 1
    return max(0.0, min(1.0, inside / days)) if days > 0 else 0.0


def checks(f: Dict[str, Any], tax_year: str, person: Optional[str] = None,
           second: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    from backend.app.sa.income import tax_year_dates
    if f.get("box1") is None and f.get("box6") is None:
        return "CHECK", ["The VAT return's boxes could not be read: enter the VAT figures on Self-employment by hand."]
    if f.get("trader") and COMPANY.search(f["trader"]):
        f["other_person"] = True
        return "CHECK", [f"A VAT return for {f['trader']}, a company: not this person's sole trade, so not used on the "
                         f"return. If the person trades on their own as well, check which return is theirs."]
    # (a trading name such as 'Smith Plumbing' is not a person's name, so no owner check on it)
    assumed = ""
    if f.get("period_to") and not f.get("period_from"):
        # Only the period end shown: a VAT quarter is assumed (three months to it), and said
        from datetime import date, timedelta
        try:
            to = date.fromisoformat(f["period_to"])
            m = to.month - 2
            y = to.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            f["period_from"] = date(y, m, 1).isoformat() if to.day >= 28 else (to - timedelta(days=91)).isoformat()
            assumed = " Its start date is not shown: a quarter is assumed, check it."
        except ValueError:
            pass
    start, end = (x.isoformat() for x in tax_year_dates(tax_year))
    # the year's own returns, plus the quarters either side that overlap it (the trade's period may differ)
    part = overlap(f, (start[:4] + "-01-01"), (str(int(end[:4]) + 1) + "-03-31"))
    if not part:
        return "OTHER_YEAR", [f"This VAT return ({f.get('period_from')} to {f.get('period_to')}) is not near {tax_year}: not used."]
    return "CHECK", [f"VAT return {f.get('period_from')} to {f.get('period_to')} ({f['scheme'].lower().replace('_', ' ')} "
                     f"scheme): output VAT £{f.get('box1') or 0:,.2f}, input VAT £{f.get('box4') or 0:,.2f}, net sales "
                     f"£{f.get('box6') or 0:,.2f}. Takings and costs from the bank are worked net of VAT with it "
                     f"(R-SA103-16)." + assumed]
