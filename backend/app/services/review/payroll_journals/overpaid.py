"""U-PAY-012 net pay overpaid to a director."""

from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, NET_WAGES
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
import json
import re

from backend.app.services.review.payroll_journals.common import MIN_AMOUNT, _entry, _journal, _lines, _names_person
from backend.app.services.review.payroll_journals.hmrc import HMRC_PAYE, _payroll_year
from backend.app.services.review.payroll_journals.missing import DIRECTORS_LOAN


# ---------------------------------------------------------------------------------------------------------------
# U-PAY-012 Net pay overpaid to a director
# ---------------------------------------------------------------------------------------------------------------
DIRECTOR_OVERPAID = "Net pay paid to the director above the payroll moved to the director's loan"
OVERPAID_MIN = 50.0             # an overpayment below this is rounding, left to the accountant


def net_pay_overpaid_to_director(engagement: ClientEngagement, profile: Optional[ClientProfile],
                                 tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                                 counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """More paid out of net wages in the year than the payroll's net pay (with last year's unpaid pay), and the
    payments to the directors cover the excess: the director took more than the payroll paid, which the accountant
    moves to the director's loan (Dr 5400 / Cr 5330). Staff overpaid, or nobody named, is left to the other net
    wages points."""
    from backend.app.services.reconciliation.control_accounts import JOURNAL_SOURCE
    from backend.app.services.review.last_year import prior_balances_by_code
    directors = [d for d in (json.loads(profile.directors or "[]") if profile is not None else []) if d]
    net, _ = _payroll_year(engagement, db)
    if not directors or net < MIN_AMOUNT:
        return [], []
    paid = [g for code, g in _lines(engagement, tb_records, chart, db)
            if code == NET_WAGES and float(g.debit_amount or 0) > 0 and not JOURNAL_SOURCE.search(g.source or "")
            and not re.search(r"payroll|journal|allowance", g.description or "", re.I)
            and not HMRC_PAYE.search(f"{g.description or ''} {g.reference or ''}")]     # tax paid, not pay (U-PAY-010)
    out = round(sum(float(g.debit_amount or 0) for g in paid), 2)
    to_directors = round(sum(float(g.debit_amount or 0) for g in paid
                             if any(_names_person(g.description or "", d) for d in directors)), 2)
    rows = [t for t in tb_records if t.std_code == NET_WAGES]
    opening = (sum(float(t.opening_amount or 0) for t in rows) if rows and any(t.opening_amount is not None for t in rows)
               else prior_balances_by_code(engagement, db).get(NET_WAGES, 0.0))
    over = round(out - (net - opening), 2)          # opening is a credit (negative) when pay was still owed
    if over < OVERPAID_MIN or to_directors < over - MIN_AMOUNT:
        return [], []
    if db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement.id,
                                        ProposedJournal.status == "APPROVED",
                                        ProposedJournal.description == DIRECTOR_OVERPAID).first():
        return [], []
    entry = _entry(DIRECTORS_LOAN, NET_WAGES, over, chart)
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-012",
        procedure_name="Payroll: net wages", severity="HIGH" if over >= 1000 else "MEDIUM", source_row_ref="G6 Net wages",
        finding_title=f"£{over:,.2f} more paid to the director from net wages than the payroll's net pay",
        finding_details=(f"The payroll report's net pay for the year is £{net:,.2f}"
                         + (f" (plus £{-opening:,.2f} owed from last year)" if opening < -MIN_AMOUNT else "")
                         + f"; £{out:,.2f} was paid out of net wages, £{to_directors:,.2f} of it to the directors. The "
                           f"£{over:,.2f} above the payroll is the director's own drawing, not pay, so it goes to the "
                           f"director's loan (Journals tab): {entry}. Check no payroll month is missing first (a "
                           f"missing month would explain part of it)."),
        quantified_amount=over, suggested_journal=entry, status="OPEN")
    return [f], [_journal(engagement, counter, DIRECTOR_OVERPAID, DIRECTORS_LOAN, NET_WAGES, over, chart, f)]
