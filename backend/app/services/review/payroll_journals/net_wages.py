"""U-PAY-006 net wages cleared from another account."""

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, NET_WAGES
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
import re

from backend.app.services.review.payroll_journals.common import WAGE_COST_CODES, _entry, _journal, _lines


NET_WAGES_MONTHS = 1.5          # owed at the year end above this many months' net pay: not just the last payroll
NET_WAGES_MATCH = 0.10          # the bank payments on the wage costs within this share of what is owed: the cause


def net_wages_cleared_elsewhere(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                                db: Session, counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """Net wages left owed at the year end that the payroll does not explain. The payroll journals credit net wages;
    when the pay goes out of the bank coded to the wage costs instead of net wages, net wages is never cleared (and
    the wage costs hold the pay twice). Bank payments on the wage cost accounts that match what is owed are proposed
    as the clearing journal (Dr net wages / Cr the wage cost); otherwise a point to look at. Net wages overdrawn (paid
    out more than posted) is the other way round: payroll journals missing or posted elsewhere."""
    from backend.app.services.reconciliation.control_accounts import JOURNAL_SOURCE
    from backend.app.services.tax.ct_computation import final_balances
    matched = _net_pay_paid_into_costs(engagement, tb_records, chart, db, counter)
    if matched[0]:
        return matched
    owed = -round(final_balances(engagement.id, tb_records, db).get(NET_WAGES, 0.0), 2)
    posted: Dict[Tuple[int, int], float] = {}
    bank_on_costs: Dict[int, float] = {}
    for code, g in _lines(engagement, tb_records, chart, db):
        when = g.transaction_date
        if code == NET_WAGES and when and float(g.credit_amount or 0) > 0:
            posted[(when.year, when.month)] = posted.get((when.year, when.month), 0.0) + float(g.credit_amount or 0)
        elif code in WAGE_COST_CODES and float(g.debit_amount or 0) > 0 and not JOURNAL_SOURCE.search(g.source or "") \
                and not re.search(r"payroll|journal", f"{g.source or ''} {g.description or ''}", re.I):
            bank_on_costs[code] = bank_on_costs.get(code, 0.0) + float(g.debit_amount or 0)
    if not posted:
        return [], []
    month = sum(posted.values()) / len(posted)
    if abs(owed) < max(NET_WAGES_MONTHS * month, 1000.0):
        return [], []
    if owed < 0:
        return [AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-006",
            procedure_name="Payroll: net wages", severity="HIGH" if -owed >= 5000 else "MEDIUM", source_row_ref="G6 Net wages",
            finding_title=f"Net wages overdrawn by £{-owed:,.2f} at the year end: more paid out than the payroll posted",
            finding_details=(f"Net pay posted averages £{month:,.2f} a month, but the net wages account ends £{-owed:,.2f} "
                             f"in debit. Payroll journals are missing, or were posted to another account (wages expense, "
                             f"the director's loan). Check the payroll journals month by month (G6)."),
            quantified_amount=-owed, status="OPEN")], []
    paid = round(sum(bank_on_costs.values()), 2)
    if paid and abs(paid - owed) <= NET_WAGES_MATCH * owed:
        cost = max(bank_on_costs, key=bank_on_costs.get)
        amount = round(min(owed, paid), 2)
        entry = _entry(NET_WAGES, cost, amount, chart)
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-006",
            procedure_name="Payroll: net wages", severity="HIGH", source_row_ref="G6 Net wages",
            finding_title=f"Net wages £{owed:,.2f} still owed: the pay went out of the bank coded to wage costs",
            finding_details=(f"The payroll journals credit net wages (about £{month:,.2f} a month), but net wages is never "
                             f"paid down: £{owed:,.2f} is left at the year end. Bank payments of £{paid:,.2f} were coded "
                             f"straight to the wage cost accounts instead, so the wages are in the costs twice. A journal "
                             f"clears it (Journals tab): {entry}. Check a few of the bank payments are the staff's net pay."),
            quantified_amount=amount, suggested_journal=entry, status="OPEN")
        return [f], [_journal(engagement, counter, "Net wages paid from the bank coded to wage costs", NET_WAGES, cost,
                              amount, chart, f)]
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-006",
        procedure_name="Payroll: net wages", severity="HIGH" if owed >= 5000 else "MEDIUM", source_row_ref="G6 Net wages",
        finding_title=f"Net wages £{owed:,.2f} still owed at the year end: more than the last payroll",
        finding_details=(f"Net pay posted averages £{month:,.2f} a month, but £{owed:,.2f} is left on net wages. The pay "
                         f"probably went out of another account: bank payments coded to wage costs (£{paid:,.2f} found), "
                         f"the director's loan, or a second bank. Find where the net pay was paid and clear net wages "
                         f"with a journal (Dr net wages / Cr that account)."),
        quantified_amount=owed, status="OPEN")], []


NET_PAY_TOLERANCE = 1.0         # a bank payment is a month's net pay when it agrees to the pound


def _net_pay_paid_into_costs(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                             counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """The payroll's gross pay is already in the wage costs, and the net pay paid from the bank was coded to the wage
    costs as well (e.g. 'Direct Wages' holding each month's net pay beside the payroll's gross): the pay is in
    the costs twice. Found line by line: a bank payment on a wage cost
    account equal to a month's net pay in the payroll report (the company's, or one person's), that month or the one
    either side; each pay run used once, and never more than the wage costs hold above the report's gross. Moved to
    net wages, which the payroll credits (FRS 102 s28: the cost of the employees' service is the gross pay, once)."""
    from backend.app.services.reconciliation.control_accounts import JOURNAL_SOURCE
    from backend.app.services.review.payroll_period import usable
    from backend.app.services.tax.ct_computation import final_balances
    from backend.app.services.review.payroll_journals.common import (MIN_AMOUNT, _journal_lines, _month, _net_pay,
                                                                     employer_ni_on_wage_codes)
    records, _ = usable(engagement, db)
    records = [r for r in records if _month(r) is not None]
    if not records:
        return [], []
    after = final_balances(engagement.id, tb_records, db)
    books = round(sum(after.get(c, 0.0) for c in WAGE_COST_CODES) - employer_ni_on_wage_codes(tb_records), 2)
    gross = round(sum(float(r.gross_pay or 0) for r in records), 2)
    extra = round(books - gross, 2)
    if gross < MIN_AMOUNT or extra < max(500.0, 0.01 * gross):
        return [], []
    # The pay runs' net pay: the company's month, and each person's month
    runs: Dict[Tuple[str, Tuple[int, int]], float] = {}
    for r in records:
        for who in ("", r.employee_name or ""):
            key = (who, _month(r))
            runs[key] = runs.get(key, 0.0) + _net_pay(r)
    runs = {k: round(v, 2) for k, v in runs.items() if v >= MIN_AMOUNT}
    used, moved = set(), {}
    total = 0.0
    lines = sorted(((code, g) for code, g in _lines(engagement, tb_records, chart, db)
                    if code in WAGE_COST_CODES and g.transaction_date and float(g.debit_amount or 0) > 0
                    and not JOURNAL_SOURCE.search(g.source or "")
                    and not re.search(r"payroll|journal", f"{g.source or ''} {g.description or ''}", re.I)),
                   key=lambda x: x[1].transaction_date)
    step = lambda k, n: (k[0] + (k[1] - 1 + n) // 12, (k[1] - 1 + n) % 12 + 1)
    for code, g in lines:
        amount = round(float(g.debit_amount or 0), 2)
        when = (g.transaction_date.year, g.transaction_date.month)
        hit = next((k for n in (0, -1, 1) for k, v in runs.items()
                    if k not in used and k[1] == step(when, n) and abs(v - amount) <= NET_PAY_TOLERANCE), None)
        if hit is None or total + amount > extra + NET_PAY_TOLERANCE:
            continue
        # A person's run and the company's run of the same month are the same money: use both up
        used.update(k for k in runs if k[1] == hit[1] and (k[0] in ("", hit[0]) or hit[0] == ""))
        moved[code] = round(moved.get(code, 0.0) + amount, 2)
        total = round(total + amount, 2)
    if total < max(500.0, 0.01 * gross):
        return [], []
    lines_j = [(NET_WAGES, total, 0.0)] + [(c, 0.0, a) for c, a in moved.items()]
    entry = "; ".join(f"{'Dr' if dr else 'Cr'} {c} {chart.name(c)} £{(dr or cr):,.2f}" for c, dr, cr in lines_j)
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-006",
        procedure_name="Payroll: net wages", severity="HIGH", source_row_ref="G6 Net wages",
        finding_title=f"Net pay £{total:,.2f} paid from the bank was coded to wage costs as well as the payroll"[:255],
        finding_details=(f"The wage costs hold £{books:,.2f}, £{extra:,.2f} more than the payroll report's gross pay "
                         f"(£{gross:,.2f}). Bank payments of £{total:,.2f} on the wage costs each equal a month's net "
                         f"pay in the payroll report: the net pay paid out, coded to the costs instead of net wages, "
                         f"so the pay is in the costs twice. A journal moves it to net wages (Journals tab): {entry}."),
        quantified_amount=total, suggested_journal=entry[:1000], status="OPEN")
    return [f], [_journal_lines(engagement, counter, "Net pay paid from the bank coded to wage costs, moved to net wages",
                                lines_j, chart, f)]
