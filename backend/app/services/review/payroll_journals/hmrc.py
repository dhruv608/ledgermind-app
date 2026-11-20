"""U-PAY-010 PAYE paid to HMRC but posted to net wages."""

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, NET_WAGES, PAYE_NIC
from typing import List, Tuple
from sqlalchemy.orm import Session
from datetime import date
import re

from backend.app.services.review.payroll_journals.common import MIN_AMOUNT, _lines, _report


# ---------------------------------------------------------------------------------------------------------------
# U-PAY-010 PAYE paid to HMRC but posted to net wages
# ---------------------------------------------------------------------------------------------------------------
# HMRC's PAYE payment: HMRC with PAYE / NI / the Cumbernauld office or Accounts Office, or the 13-character PAYE
# Accounts Office reference ('120PL01234567', often masked in bank feeds as '475PBXXXXXXXX1234')
HMRC_PAYE = re.compile(r"\bhmrc\b.*\b(paye|nics?|ni|cumb\w*|accounts of\w*|ndds)\b|\b\d{3}p[a-z][0-9x]{8}", re.I)


def _payroll_year(engagement: ClientEngagement, db: Session) -> Tuple[float, float]:
    """The payroll report's net pay and total due to HMRC (tax, employee and employer NI, student loan, less statutory
    pay recovered) for the pay periods ending in the accounting year."""
    from backend.app.services.setup.engagement_setup import period_of
    period = period_of(engagement)
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    rows = _report(engagement, db)
    inside = [r for r in rows if r.period_end and start <= r.period_end <= end] or rows
    net = sum(float(r.net_pay or 0) for r in inside)
    due = sum(float(r.total_hmrc_due or 0) for r in inside) or sum(
        float(r.tax_deducted or 0) + float(r.employee_nic or 0) + float(r.employer_nic or 0) + float(r.student_loan or 0)
        - float(r.statutory_pay_recovered or 0) for r in inside)
    return round(net, 2), round(due, 2)


def hmrc_in_net_wages(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                      counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """Payments to HMRC for PAYE and NI coded to net wages (5330) instead of PAYE (5320): a point for the accountant
    with the figures, no journal. What to move depends on how the books post the payroll: with net wages credited for
    the net pay only, the payments alone move; when net wages is one control for the net pay and the PAYE (PAYE due
    posted there too), the PAYE due moves with them. The two cannot be told apart reliably from the books and the
    payroll report, so the accountant decides."""
    lines = [g for code, g in _lines(engagement, tb_records, chart, db) if code == NET_WAGES]
    paid = [g for g in lines if float(g.debit_amount or 0) > 0
            and HMRC_PAYE.search(f"{g.description or ''} {g.reference or ''}")]
    total = round(sum(float(g.debit_amount or 0) for g in paid), 2)
    if total < MIN_AMOUNT:
        return [], []
    credited = round(sum(float(g.credit_amount or 0) for g in lines), 2)
    net, due = _payroll_year(engagement, db)
    shown = "; ".join(f"{g.transaction_date:%d/%m/%Y} £{float(g.debit_amount):,.2f}" for g in paid[:12] if g.transaction_date)
    payroll = (f" Net wages is credited with £{credited:,.2f} in the year; the payroll report shows net pay £{net:,.2f} "
               f"and £{due:,.2f} due to HMRC. Credits close to the net pay mean the payments alone move; close to net "
               f"pay plus the PAYE due mean the PAYE was posted to net wages too, and moves with them."
               if net >= MIN_AMOUNT else " There is no payroll report to show how the payroll is posted.")
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-010",
        procedure_name="Payroll: net wages", severity="HIGH" if total >= 1000 else "MEDIUM", source_row_ref="G6 Net wages",
        finding_title=f"{len(paid)} HMRC PAYE payment(s), £{total:,.2f}, are posted to net wages",
        finding_details=(f"Payments to HMRC for PAYE and NI are coded to net wages ({shown}"
                         f"{' and more' if len(paid) > 12 else ''}). They pay PAYE, not the staff's net pay, so they "
                         f"belong on PAYE ({PAYE_NIC}).{payroll} Move them with a journal (Dr {PAYE_NIC} / Cr "
                         f"{NET_WAGES}), with any PAYE the payroll posted to net wages."),
        quantified_amount=total, status="OPEN")], []
