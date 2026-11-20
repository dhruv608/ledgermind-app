"""The director-shareholder checks (R-DIR-02, -03, -04, -06), from the linked company's own books in LedgerMind;
each is a point for the accountant, never a change to the figures (dividends come in by R-DIR-01, sa/income):

  reserves      dividends paid while the company's profit and loss reserve is negative: an unlawful dividend or a
                loan, an accountant's decision (CA 2006 s830)
  loan          the director's loan account (5400 / 5401) overdrawn by over £10,000 at any time in the tax year with
                interest below the official rate: a beneficial loan benefit (ITEPA s175, averaging method; official
                rate P-ORI-01), unless it is on the P11D; overdrawn at the company's year end: s455 on the company
  personal      the company paid the director's personal tax or bills: a debit on the loan account, not a cost"""

import re
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from backend.app.sa.engine.calc import rates_for

DLA_CODES = (5400, 5401)
RESERVE_CODES = tuple(range(8000, 8071))
LOAN_LIMIT = 10000.0
PERSONAL = re.compile(r"self[- ]assessment|personal tax|\bsa tax\b|council tax|\btv licen|netflix|sky tv|gym|holiday",
                      re.I)


def balances(opening: float, moves: List[Tuple[date, float]]) -> List[Tuple[date, float]]:
    """The loan account's balance after each move (debit positive: the director owes the company)."""
    out, bal = [], opening
    for on, amount in sorted(moves):
        bal = round(bal + amount, 2)
        out.append((on, bal))
    return out


def at(path: List[Tuple[date, float]], opening: float, day: date) -> float:
    bal = opening
    for on, b in path:
        if on <= day:
            bal = b
    return bal


def loan_points(opening: float, moves: List[Tuple[date, float]], start: date, end: date, rate: float,
                company_year_end: Optional[date]) -> List[str]:
    """The beneficial loan and s455 points for the tax year start..end."""
    path = balances(opening, moves)
    first = at(path, opening, start - timedelta(days=1))
    in_year = [b for on, b in path if start <= on <= end] + [first]
    peak = max(in_year) if in_year else first
    out = []
    if peak > LOAN_LIMIT:
        last = at(path, opening, end)
        average = (max(first, 0.0) + max(last, 0.0)) / 2
        benefit = round(average * rate, 2)
        out.append(f"The director's loan account was overdrawn by up to £{peak:,.2f} in the tax year (over £{LOAN_LIMIT:,.0f}): "
                   f"a beneficial loan, about £{benefit:,.2f} at the official rate of {rate:.2%} (average of £{first:,.2f} and "
                   f"£{last:,.2f}), less any interest the director paid. Enter it on SA102 box 15 unless the P11D shows it "
                   f"(R-DIR-03).")
    if company_year_end is not None and at(path, opening, company_year_end) > 0:
        out.append(f"The director owed the company £{at(path, opening, company_year_end):,.2f} at its year end "
                   f"({company_year_end:%d/%m/%Y}): s455 tax on the company file unless repaid within nine months (R-DIR-03).")
    return out


def points(db, job) -> List[Dict]:
    """The director checks for a return linked to a company in LedgerMind."""
    from backend.app.models.database import ClientEngagement, GLTransaction, MasterCOA, TBRecord
    from backend.app.sa.income import director_dividends, tax_year_dates
    if not job.company_engagement_id:
        return []
    linked = db.get(ClientEngagement, job.company_engagement_id)
    if linked is None:
        return []
    start, end = tax_year_dates(job.tax_year)
    rate = rates_for(job.tax_year).get("official_rate", 0.0375)
    years = db.query(ClientEngagement).filter(ClientEngagement.owner_user_id == linked.owner_user_id,
                                              ClientEngagement.client_name == linked.client_name).all()
    pl_codes = {c for (c,) in db.query(MasterCOA.std_code).filter(MasterCOA.financial_class == "Profit and Loss")}
    out: List[Dict] = []
    paid = sum(d["amount"] for d in director_dividends(db, job))
    for eng in years:
        tb = db.query(TBRecord).filter(TBRecord.engagement_id == eng.id).all()
        ye = _year_end(eng)
        # R-DIR-02 reserves: the profit and loss account at the year end, dividends taken off
        if paid and ye and start <= ye <= end + timedelta(days=366):
            reserve = -sum(float(t.net_amount or 0) for t in tb if t.std_code in pl_codes or t.std_code in RESERVE_CODES)
            if reserve < 0:
                out.append({"key": f"reserves:{eng.id}", "text": f"Dividends of £{paid:,.2f} were paid this tax year, but the "
                            f"company's profit and loss reserve at {ye:%d/%m/%Y} is £{reserve:,.2f}: the dividends may "
                            f"be unlawful (CA 2006 s830) and so a loan to the director. Accountant decision (R-DIR-02)."})
        # R-DIR-03 the director's loan account
        names = [t.raw_account_name for t in tb if t.std_code in DLA_CODES]
        if names:
            lines = db.query(GLTransaction).filter(GLTransaction.engagement_id == eng.id,
                                                   GLTransaction.raw_account_name.in_(names)).all()
            moves = [(l.transaction_date, float(l.debit_amount or 0) - float(l.credit_amount or 0))
                     for l in lines if l.transaction_date]
            closing = sum(float(t.net_amount or 0) for t in tb if t.std_code in DLA_CODES)
            opening = round(closing - sum(m for _, m in moves), 2)
            for n, text in enumerate(loan_points(opening, moves, start, end, rate, ye)):
                out.append({"key": f"loan:{eng.id}:{n}", "text": text})
            # R-DIR-04 / -06 personal costs the company paid
            personal = [l for l in lines if PERSONAL.search(f"{l.description or ''} {l.reference or ''}")
                        and l.transaction_date and start <= l.transaction_date <= end]
            if personal:
                out.append({"key": f"personal:{eng.id}", "text": f"{len(personal)} payment(s) on the loan account look "
                            f"personal (e.g. {personal[0].description[:60]}): a debit to the director, not a company "
                            f"cost; a benefit in kind if not charged to the loan account (R-DIR-04, R-DIR-06)."})
    return out


def _year_end(eng) -> Optional[date]:
    v = getattr(eng, "period_end_date", None)
    if isinstance(v, date):
        return v
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
