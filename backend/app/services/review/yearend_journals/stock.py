"""Stock journals: last year's closing stock reversed, the year-end count booked, and opening / closing stock
shown in the P&L when the stock account moved during the year."""

from typing import Dict, List, Optional, Tuple

from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.setup_checks import setup_of
from backend.app.services.review.yearend_journals.common import (CLOSING_STOCK_PL, MIN_AMOUNT, OPENING_STOCK_PL,
                                                                STOCK_LINES, _entry, _journal, _point)

# ---------------------------------------------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------------------------------------------
def last_year_stock(engagement: ClientEngagement, db) -> float:
    """Stock in last year's closing TB: last year's job in the app, else the last year's TB uploaded in the firm's
    codes. A client's Xero TB often has no stock line at all (the stock was only in last year's accounts), so this
    year's TB alone does not show it."""
    from backend.app.services.review.last_year import last_year_job, prior_balances_by_code
    stock_codes = set(STOCK_LINES) | set(range(4304, 4311))
    try:
        last = last_year_job(engagement, db)
        if last is not None:
            held = sum(float(t.net_amount or 0) for t in db.query(TBRecord).filter(
                TBRecord.engagement_id == last.id, TBRecord.std_code.in_(stock_codes)))
            if abs(held) >= MIN_AMOUNT:
                return round(held, 2)
        return round(sum(v for c, v in prior_balances_by_code(engagement, db).items() if c in stock_codes), 2)
    except Exception:
        db.rollback()
        return 0.0


def stock_journals(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                   chart: ChartLookup, counter: List[int], after: Dict[int, float], db=None
                   ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    findings, journals = [], []
    opening = {code: round(sum(float(t.opening_amount or 0) for t in tb_records if t.std_code == code), 2)
               for code in STOCK_LINES}
    reversed_now: Dict[int, float] = {}
    entered = (setup_of(profile).get("policies") or {}).get("closing_stock")
    try:
        entered = float(entered) if entered not in (None, "") else None
    except (TypeError, ValueError):
        entered = None
    # Opening stock reversed, unless the books (or an approved journal) already carry an opening stock line. Not an
    # account that moved during the year: the software tracks stock there (purchases in, cost of sales out), so its
    # balance is already this year's, opening included (reversing it would leave only the year's movement). The
    # year-end count, when entered, then adjusts it (FRS 102 s13).
    # Only with the count: reversed alone it leaves no closing stock, so the whole stock falls into cost of sales.
    # Without it the stock stays as it is until counted, and U-STK-003 asks for the count (S-001)
    if entered is not None and abs(sum(after.get(c, 0.0) for c in OPENING_STOCK_PL)) < MIN_AMOUNT:
        for code, amount in opening.items():
            if amount < MIN_AMOUNT or abs(after.get(code, 0.0) - amount) >= MIN_AMOUNT:
                continue
            dr = STOCK_LINES[code][0]
            entry = _entry(dr, code, amount, chart)
            f = _point(engagement, "U-STK-001", "Stock: opening stock reversed",
                       f"Last year's closing stock £{amount:,.2f} is not yet in this year's cost of sales",
                       f"{chart.name(code)} brought forward £{amount:,.2f} (last year's closing stock). It is this year's "
                       f"opening stock: reverse it into cost of sales. A journal is proposed (Journals tab): {entry}.",
                       amount, entry)
            findings.append(f)
            journals.append(_journal(engagement, counter, "Opening stock reversed (last year's closing stock)",
                                     dr, code, amount, chart, f))
            reversed_now[code] = amount
    # Closing stock is the year-end count (FRS 102 s13, S-001: require a closing stock figure). The books' stock after
    # the opening reversal is adjusted to the count entered on the setup, by the difference: a client whose software
    # tracks stock already holds it (no journal), one whose bills were only coded to stock holds purchases there
    # (moved to purchases)
    in_books = {c: round(after.get(c, 0.0) - reversed_now.get(c, 0.0), 2) for c in STOCK_LINES}
    books_stock = round(sum(in_books.values()), 2)
    posted = round(sum(after.get(c, 0.0) - opening.get(c, 0.0) for c in STOCK_LINES), 2)   # coded to stock this year
    if entered is not None:
        diff = round(entered - books_stock, 2)
        if abs(diff) >= MIN_AMOUNT:
            code = max((c for c in STOCK_LINES if abs(opening.get(c, 0)) >= MIN_AMOUNT or abs(after.get(c, 0)) >= MIN_AMOUNT),
                       key=lambda c: abs(in_books.get(c, 0)) or abs(opening.get(c, 0)), default=4300)
            cr = STOCK_LINES[code][1]
            dr, cr = (code, cr) if diff > 0 else (cr, code)
            entry = _entry(dr, cr, abs(diff), chart)
            f = _point(engagement, "U-STK-002", "Stock: closing stock recorded",
                       f"Stock adjusted to the year-end count £{entered:,.2f} (books £{books_stock:,.2f})",
                       f"The closing stock entered on the client setup is £{entered:,.2f}; the books hold £{books_stock:,.2f} "
                       f"on the stock accounts" + (" after last year's stock is reversed" if reversed_now else "")
                       + ". Stock at the year end is the count (FRS 102 s13), so the books are "
                       + ("raised" if diff > 0 else "reduced") + f" by £{abs(diff):,.2f} through cost of sales"
                       + (" (bills coded to the stock account that are not stock at the year end)" if diff < 0 and posted >= MIN_AMOUNT else "")
                       + f". A journal is proposed (Journals tab): {entry}.", abs(diff), entry)
            findings.append(f)
            journals.append(_journal(engagement, counter, "Closing stock recorded (stock count at the year end)",
                                     dr, cr, abs(diff), chart, f))
    elif (any(v >= MIN_AMOUNT for v in opening.values()) or abs(posted) >= MIN_AMOUNT
          or (db is not None and last_year_stock(engagement, db) >= MIN_AMOUNT)):
        why = (f"£{posted:,.2f} was posted to the stock accounts this year, so the books show stock of "
               f"£{books_stock:,.2f} at the year end. If the software tracks stock that is the count; if bills were only "
               f"coded there, it is purchases. " if abs(posted) >= MIN_AMOUNT else
               "Last year's TB has stock, so this year will normally have some too. ")
        why += ("Until the count is entered the stock is left as it is (last year's figure, no effect on profit): "
                "last year's stock is reversed and the count booked together once it is known. ")
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-STK-003",
            procedure_name="Stock: closing stock not entered", severity="HIGH" if abs(posted) >= 1000 else "MEDIUM",
            source_row_ref="Client setup",
            finding_title="Closing stock at the year end not entered (client setup, Policies)",
            finding_details=(f"{why}Enter the year-end stock count on the client setup (Policies: closing stock), or 0 "
                             f"if there is none; the books are then adjusted to it. Client question: Please provide the "
                             f"stock count at the year end, with how it was valued (lower of cost and selling price)."),
            quantified_amount=abs(books_stock) if abs(posted) >= MIN_AMOUNT else 0.0, status="OPEN"))
    stock_in_pl(engagement, tb_records, chart, counter, after, opening, in_books, reversed_now, db, findings, journals)
    return findings, journals


COST_OF_SALES = 1100


def stock_in_pl(engagement, tb_records, chart, counter, after, opening, in_books, reversed_now, db, findings,
                journals) -> None:
    """Opening and closing stock shown in the P&L when the stock account moved during the year (the software, or the
    client's monthly journals, ran the stock through purchases): opening stock (last year's) to the P&L opening stock
    line, the stock now in the books to the closing stock line, the difference back to cost of sales. Profit and the
    balance sheet do not change; the P&L shows opening stock, purchases and closing stock (opening
    reversed, closing posted). A count entered on the setup still adjusts the closing line on top (U-STK-002)."""
    if reversed_now or any(abs(after.get(c, 0.0)) >= MIN_AMOUNT for c in OPENING_STOCK_PL + CLOSING_STOCK_PL):
        return                               # the books (or the opening reversal) already show stock in the P&L
    prior: Dict[int, float] = {}
    if db is not None and not any(abs(v) >= MIN_AMOUNT for v in opening.values()):
        try:
            from backend.app.services.review.last_year import prior_balances_by_code
            prior = prior_balances_by_code(engagement, db)
        except Exception:
            db.rollback()
    start = {c: (opening.get(c, 0.0) if abs(opening.get(c, 0.0)) >= MIN_AMOUNT else round(prior.get(c, 0.0), 2))
             for c in STOCK_LINES}
    end = {c: in_books.get(c, 0.0) for c in STOCK_LINES}
    if not any(abs(end[c] - start[c]) >= MIN_AMOUNT and (start[c] >= MIN_AMOUNT or end[c] >= MIN_AMOUNT)
               for c in STOCK_LINES):
        return                               # no stock, or a stock account that did not move (U-STK-001 / 002)
    lines: List[Tuple[int, float, float]] = []
    for code, (open_pl, close_pl) in STOCK_LINES.items():
        if start[code] >= MIN_AMOUNT:
            lines.append((open_pl, start[code], 0.0))
        if end[code] >= MIN_AMOUNT:
            lines.append((close_pl, 0.0, end[code]))
    if not lines:
        return
    gap = round(sum(dr for _c, dr, _cr in lines) - sum(cr for _c, _dr, cr in lines), 2)
    if abs(gap) >= 0.005:
        lines.append((COST_OF_SALES, 0.0, gap) if gap > 0 else (COST_OF_SALES, -gap, 0.0))
    opened = round(sum(dr for c, dr, _cr in lines if c in OPENING_STOCK_PL), 2)
    closed = round(sum(cr for c, _dr, cr in lines if c in CLOSING_STOCK_PL), 2)
    entry = "; ".join(f"{'Dr' if dr else 'Cr'} {c} {chart.name(c)} £{(dr or cr):,.2f}" for c, dr, cr in lines)
    f = _point(engagement, "U-STK-004", "Stock: opening and closing stock in the P&L",
               f"Opening stock £{opened:,.2f} and closing stock £{closed:,.2f} shown in the P&L",
               f"The stock accounts moved during the year (the stock was run through purchases), so the P&L shows no "
               f"opening or closing stock. Opening stock (last year's, £{opened:,.2f}) and closing stock (in the books "
               f"now, £{closed:,.2f}) go to their P&L lines and the difference back to cost of sales: profit and the "
               f"balance sheet do not change. A journal is proposed (Journals tab): {entry}.", max(opened, closed), entry,
               severity="LOW")
    findings.append(f)
    from backend.app.services.review.payroll_journals import _journal_lines
    journals.append(_journal_lines(engagement, counter, "Opening and closing stock in the P&L", lines, chart, f))
