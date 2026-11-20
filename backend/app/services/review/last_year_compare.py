"""Last year v this year: each balance beside last year's, and the big changes as client questions (PY-MOVE)."""

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.services.review.point_figures import amounts
from backend.app.models.database import AuditFinding, ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, account_name_keys
from backend.app.services.review.last_year_common import Comparison, LastYearLine, _from_job, last_year_job, logger, pick_account
from backend.app.services.review.last_year_read import _from_files

CHANGE_SHARE = 0.5              # a change of more than 50%...
CHANGE_AMOUNT = 1000.0          # ...and more than £1,000 is asked about; so is a new or gone balance of £1,000 or more
# Balances that always change or are worked out by the app: not asked about
NOT_COMPARED = {"Profit and loss account", "Share capital", "Share premium account", "Revaluation reserve",
                "Capital redemption reserve", "Current tax", "Deferred tax", "Depreciation"}
TRANSFERS = 9998                # Bank + Dext: money between the client's own accounts (asked about on its own)


def compare(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session) -> Comparison:
    """Last year's balance for each of this year's accounts: by account name first, then by firm code. A closing TB
    with the profit already moved to reserves has no P&L: then P&L accounts are not compared."""
    last = last_year_job(engagement, db)
    if last is not None:
        source, lines = f"last year in the app (year ended {last.period_end_date:%d/%m/%Y})", _from_job(last, db)
    else:
        try:
            source, lines = _from_files(engagement, db)
        except Exception:
            logger.exception("Last year's TB could not be read")
            source, lines = "", []
    out = Comparison(source=source)
    if not source:
        return out
    names: Dict[str, str] = {}
    for t in tb_records:
        for k in account_name_keys(t.raw_account_name):
            names.setdefault(k, t.raw_account_name)
    left: List[LastYearLine] = []
    from backend.app.services.bank_only.books import is_books_client
    if (last is None and not is_books_client(engagement)
            and any(t.opening_amount is not None and abs(float(t.opening_amount or 0)) >= 0.005 for t in tb_records)
            and lines and all(line.code is not None for line in lines)):
        # Last year's TB gave the openings by code: compare each code with the account that took its opening
        for line in lines:
            same = [t for t in tb_records if t.std_code == line.code]
            if not same:
                left.append(line)
                continue
            hit = pick_account(line, same, by_opening=True).raw_account_name
            out.by_account[hit] = round(out.by_account.get(hit, 0.0) + line.amount, 2)
        lines_by_name: List[LastYearLine] = []
    else:
        lines_by_name = lines
    for line in lines_by_name:
        hit = next((names[k] for k in account_name_keys(line.name) if line.name and k in names), None)
        if hit is None:
            left.append(line)
        else:
            out.by_account[hit] = round(out.by_account.get(hit, 0.0) + line.amount, 2)
    # By code: to the biggest account on that code this year that no name took
    for line in left:
        same = [t for t in tb_records if line.code is not None and t.std_code == line.code]
        free = [t for t in same if t.raw_account_name not in out.by_account] or same
        if free:
            hit = max(free, key=lambda t: abs(float(t.net_amount or 0.0))).raw_account_name
            out.by_account[hit] = round(out.by_account.get(hit, 0.0) + line.amount, 2)
        elif abs(line.amount) >= 0.005:
            out.gone.append(line)
    # A line of last year's TB with no code is P&L when this year's account of the same name is (otherwise a closing
    # TB of names only reads as all balance sheet, and every cost shows as 'nothing last year')
    code_of = {t.raw_account_name: t.std_code for t in tb_records}

    def is_pl_line(line: LastYearLine) -> bool:
        if line.code is not None:
            return chart.is_pl(line.code)
        hit = next((names[k] for k in account_name_keys(line.name) if line.name and k in names), None)
        return hit is not None and chart.is_pl(code_of.get(hit))

    has_pl = any(is_pl_line(line) for line in lines if abs(line.amount) >= 0.005)
    from backend.app.services.bank_only.books import is_books_client
    openings_in = any(t.opening_amount is not None for t in tb_records)     # balances already include the opening
    if (last is None and not is_books_client(engagement) and not openings_in and lines
            and all(line.code is not None for line in lines)):
        # Firm codes: a TB of movements, unless it repeats last year's unchanged balances to the penny (a closing TB)
        this_year: Dict[int, float] = {}
        for t in tb_records:
            if t.std_code is not None:
                this_year[t.std_code] = this_year.get(t.std_code, 0.0) + float(t.net_amount or 0.0)
        by_code: Dict[int, float] = {}
        for line in lines:
            by_code[line.code] = by_code.get(line.code, 0.0) + line.amount
        out.movements = sum(1 for c, v in by_code.items() if abs(v) >= 1 and abs(this_year.get(c, 0.0) - v) < 0.01) < 2
    if out.movements:
        out.gone = []       # a balance with no movement this year is still there, unchanged
    for t in tb_records:
        # Not compared: P&L against a closing TB with no P&L, and accounts not yet given a code
        if not has_pl and (chart.is_pl(t.std_code) or t.std_code is None or t.std_code not in chart.accounts
                           or t.std_code == 9999):
            out.by_account[t.raw_account_name] = None
        else:
            out.by_account.setdefault(t.raw_account_name, 0.0)
    if not has_pl:
        out.gone = [g for g in out.gone if not chart.is_pl(g.code)]
    return out


def firm_change_limit(db: Optional[Session]) -> float:
    """The firm's amount a change on last year must pass to be asked about (Firm settings), £1,000 when the firm
    has not set one."""
    if db is None:
        return CHANGE_AMOUNT
    import json
    from backend.app.models.firm_settings import FirmSetting
    row = db.get(FirmSetting, "change_question_limit")
    try:
        amount = json.loads(row.value).get("amount") if row is not None else None
    except ValueError:
        amount = None
    return float(amount) if amount is not None else CHANGE_AMOUNT


def is_big_change(this_year: float, last_year: float, amount: float = CHANGE_AMOUNT) -> bool:
    change = abs(this_year - last_year)
    if change < amount:
        return False
    return abs(last_year) < 0.005 or abs(this_year) < 0.005 or change > CHANGE_SHARE * abs(last_year)


def asked(chart: ChartLookup, code: Optional[int], this_year: float, last_year: Optional[float],
          amount: float = CHANGE_AMOUNT) -> bool:
    """The change is put to the client (amount: the firm's limit, firm_change_limit)."""
    # Depreciation is the accountant's own year-end entry, not a question for the client
    return (last_year is not None and code != TRANSFERS and chart.section(code) not in NOT_COMPARED
            and "depreciation" not in chart.name(code).lower() and is_big_change(this_year, last_year, amount))


def _money(v: float) -> str:
    return f"£{abs(v):,.2f}" + (" Cr" if v < -0.004 else "")


def year_on_year_points(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                        db: Session) -> List[AuditFinding]:
    """A client question for each balance that changed by more than 50% and the firm's limit (£1,000 unless set) on
    last year, is new, or is gone."""
    cmp = compare(engagement, tb_records, chart, db)
    if not cmp.source:
        return []
    limit = firm_change_limit(db)

    def point(label: str, code: Optional[int], now: float, before: Optional[float]) -> Optional[AuditFinding]:
        if not asked(chart, code, now, before, limit):
            return None
        if abs(before) < 0.005:
            what = f"{label}: {_money(now)} this year, nothing last year"
            ask = "What is it?"
        elif abs(now) < 0.005:
            what = f"{label}: nothing this year, {_money(before)} last year"
            ask = "Why is there nothing this year?"
        else:
            share = abs(now - before) / abs(before) * 100
            way = "up" if abs(now) > abs(before) else "down"
            what = f"{label}: {_money(now)} this year against {_money(before)} last year ({way} {share:,.0f}%)"
            ask = "What caused the change?"
        return AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="PY-MOVE",
            procedure_name="Last year vs this year", severity="MEDIUM",
            source_row_ref=label[:100], finding_title=f"{what}. {ask}"[:255],
            finding_details=(f"Compared with {cmp.source}. Changes of more than {CHANGE_SHARE:.0%} and "
                             f"£{limit:,.0f}, and new or gone balances, are asked about. Ask the client, or "
                             f"clear the point with the reason if you know it."),
            quantified_amount=round(abs(now - before), 2), status="OPEN",
            figures=amounts([("This year", now), ("Last year", before), ("Change", now - before, True)]),
        )

    def now(t: TBRecord) -> float:
        before = cmp.by_account.get(t.raw_account_name) or 0.0
        return float(t.net_amount or 0.0) + (before if cmp.movements else 0.0)

    found = [point(t.raw_account_name, t.std_code, now(t), cmp.by_account.get(t.raw_account_name, 0.0))
             for t in tb_records]
    found += [point(g.name or chart.name(g.code) or f"Account {g.code}", g.code, 0.0, g.amount) for g in cmp.gone]
    return [f for f in found if f is not None]
