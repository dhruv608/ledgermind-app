"""G3 overdrawn-loan tests, below the directors' confirmation:

  A-H  the reserves test: the DLA overdrawn at the year end, the distributable reserves (J2: brought forward, the year's
       profit after tax and every journal, less the dividends in the year), the further dividend that would clear it
       (the lower of the two, nil when reserves are nil or negative), what is left, and s455 on it unless repaid
       within nine months (CTA 2010 s455; 33.75% for loans from 6 April 2022, 35.75% from 6 April 2026, CTM61505). All formulas on the ETB / J2.
  The highest overdrawn balance in the year, from the ledger lines in date order from the opening balance: over
       £10,000 at any time is a benefit in kind at the official rate unless interest is charged (ITEPA 2003 s180).
  Repayments of £5,000 or more with £5,000 or more drawn again within 30 days (CTA 2010 s464C, 'bed and breakfasting').

With other shareholders a dividend goes to every holder of the class (J1): the line F is what the director must
receive, the dividend declared is larger."""

from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

S455_RATE = 0.3375          # loans 6 April 2022 to 5 April 2026 (the rate by date: s455_rate_for)


def s455_rate_for(year_end: Optional[date]) -> Tuple[float, str]:
    """The s455 rate on what is left overdrawn: the year's latest loans make up the balance (repayments clear the oldest
    first, tax/s455.py), so the rate for loans made at the year end (HMRC CTM61505: 35.75% from 6 April 2026, 33.75%
    from 6 April 2022). The CT computation splits the balance by each advance's date (H1)."""
    from backend.app.services.tax.s455 import s455_rates
    prior, current, starts = s455_rates()
    if year_end is not None and year_end >= starts:
        return current, f"loans from {starts:%d %B %Y}; H1 splits the balance by loan date"
    return prior, "loans from 6 April 2022"
BIK_LIMIT = 10_000.0
MATCHING_AMOUNT = 5_000.0
MATCHING_DAYS = 30


def _when(text) -> Optional[date]:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text)[:10], fmt).date()
        except ValueError:
            continue
    return None


def dla_lines(tx_rows, code: str = "5400") -> List[Tuple[date, float, str]]:
    """(date, debit less credit, description) of the loan's ledger lines, in date order."""
    out = []
    for tx in tx_rows or []:
        if str(tx[1]) != code:
            continue
        when = _when(tx[0])
        if when is not None:
            out.append((when, round(float(tx[7] or 0) - float(tx[8] or 0), 2), str(tx[5] or tx[3] or "")[:80]))
    return sorted(out, key=lambda x: x[0])


def highest_overdrawn(opening: float, lines) -> Tuple[float, Optional[date]]:
    """The highest debit (overdrawn) balance reached, from the opening (debit +), and when."""
    bal, top, when = opening, max(opening, 0.0), None
    for d, amount, _t in lines:
        bal += amount
        if bal > top:
            top, when = bal, d
    return round(top, 2), when


def bed_and_breakfast(lines) -> List[Tuple[date, float, float]]:
    """(date repaid, amount repaid, drawn again within 30 days) for each repayment of £5,000 or more followed within
    30 days by new drawings of £5,000 or more."""
    out = []
    for d, amount, _t in lines:
        if -amount < MATCHING_AMOUNT:
            continue
        drawn = sum(a for d2, a, _t2 in lines if a > 0 and d < d2 <= d + timedelta(days=MATCHING_DAYS))
        if drawn >= MATCHING_AMOUNT:
            out.append((d, round(-amount, 2), round(drawn, 2)))
    return out


def add_dla_tests(ctx, ws, cf: str, top: int) -> int:
    """Writes the tests from row `top` on the G3 tab (column B labels, column D amounts). cf: the c/fwd cell, owed to
    the directors +. Returns the row after them."""
    from backend.app.services.workbook.balance_tabs.common import BOLD, _money
    bold = BOLD
    ws.cell(row=top, column=1, value="Overdrawn loan: reserves, dividend and s455").font = bold
    j2 = "'J2 - Reserves'!"
    has_j2 = "J2 - Reserves" in ws.parent.sheetnames
    rate, rate_note = s455_rate_for(ctx.engagement.period_end_date)
    rows = [
        ("A", "DLA overdrawn at the year end (ETB final)", f"=MAX(0,-({cf}))"),
        ("B", "Retained earnings brought forward (J2)", f"={j2}E8" if has_j2 else 0),
        ("C", "Profit for the year after tax and every journal (J2)", f"={j2}E10" if has_j2 else 0),
        ("D", "Dividends already in the year (J2)", f"=-{j2}E12" if has_j2 else 0),
        ("E", "Distributable reserves (B + C - D)", "={B}+{C}-{D}"),
        ("F", "Further dividend to clear the loan: the lower of A and E (nil when E is nil or negative)",
         "=IF({E}<=0,0,MIN({A},{E}))"),
        ("G", "Left overdrawn after that dividend (A - F)", "={A}-{F}"),
        ("H", f"s455 at {rate:.2%} on G, unless repaid within nine months of the year end ({rate_note})",
         f"=ROUND({{G}}*{rate},2)"),
    ]
    refs = {k: f"D{top + 1 + i}" for i, (k, _l, _f) in enumerate(rows)}
    for i, (k, label, formula) in enumerate(rows):
        r = top + 1 + i
        ws.cell(row=r, column=1, value=k)
        ws.cell(row=r, column=2, value=label)
        value = formula.format(**refs) if isinstance(formula, str) else formula
        _money(ws.cell(row=r, column=4, value=value), bold=k in ("E", "H"))
    r = top + 1 + len(rows)
    ws.cell(row=r, column=2, value=("A dividend goes to every shareholder of the class by holding (J1): with other "
                                    "shareholders the dividend declared is larger than F. Only one declared on or "
                                    "before the year end clears the loan in these accounts."))
    # The highest overdrawn balance and 30-day redrawing, from the ledger in date order
    lines = dla_lines(getattr(ctx, "tx_rows", None))
    opening = float((getattr(ctx, "opening_by_code", None) or {}).get("5400", 0.0) or 0.0)
    high, when = highest_overdrawn(opening, lines)
    r += 2
    ws.cell(row=r, column=2, value="Highest overdrawn balance in the year (ledger lines in date order from b/fwd)")
    _money(ws.cell(row=r, column=4, value=high))
    if when:
        cell = ws.cell(row=r, column=5, value=when)
        cell.number_format = "dd/mm/yyyy"
    r += 1
    ws.cell(row=r, column=2, value=(f"Over £{BIK_LIMIT:,.0f} at any time: a benefit in kind at the official rate "
                                    f"unless interest is charged (P11D query)" if high > BIK_LIMIT else
                                    f"Not over £{BIK_LIMIT:,.0f} in the year: no benefit in kind on the loan"))
    matched = bed_and_breakfast(lines)
    r += 1
    if matched:
        for d, repaid, drawn in matched:
            ws.cell(row=r, column=2, value=(f"Repaid £{repaid:,.2f} on {d:%d/%m/%Y} and £{drawn:,.2f} drawn again within "
                                            f"{MATCHING_DAYS} days: the repayment may not count for s455 (CTA 2010 "
                                            f"s464C)"))
            r += 1
    else:
        ws.cell(row=r, column=2, value=f"No repayment of £{MATCHING_AMOUNT:,.0f} or more drawn again within "
                                       f"{MATCHING_DAYS} days")
        r += 1
    return r
