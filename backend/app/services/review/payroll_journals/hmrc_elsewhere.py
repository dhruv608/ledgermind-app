"""U-PAY-024 PAYE paid to HMRC but posted to a wage cost or the corporation tax account.

A payment of PAYE and NI to HMRC settles the PAYE owed (5320): the employer's costs are the gross pay and the employer's
NI the payroll charges, not the payment (NIM12201: the employer pays over the PAYE and NICs it owes). Bookkeepers
often code the HMRC payment to directors' pay, wages or employer's NI, or to the corporation tax account; they are
re-analysed to PAYE. HMRC payments go to the right liability, by the payment's reference and wording. (Payments on
the VAT account are moved by the VAT stage; on net wages, U-PAY-010.)

The journal (Dr 5320 / Cr the account) is proposed only when the PAYE owed can take the payments: with them moved,
5320 still holds a credit (the payroll set the liability up). Books that only expense HMRC payments (no payroll journal)
would push 5320 into debit: there part of the payment is the employer's NI cost, so the accountant decides (a point
with the figures, the payroll then recorded from the payroll report)."""

from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import CT_CREDITOR, PAYE_NIC, ChartLookup
from backend.app.services.review.payroll_journals.common import (
    EMPLOYER_NI_CODES, MIN_AMOUNT, WAGE_COST_CODES, _entry, _journal, _lines, paye_after)
from backend.app.services.review.payroll_journals.hmrc import HMRC_PAYE

# Where an HMRC PAYE payment is wrongly coded: the pay and employer's NI costs, and the corporation tax owed
WRONG_HOMES = tuple(WAGE_COST_CODES) + tuple(EMPLOYER_NI_CODES) + (CT_CREDITOR,)


def hmrc_paye_elsewhere(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                        counter: List[int], earlier: List[ProposedJournal]
                        ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    paid: Dict[int, list] = {}
    for code, g in _lines(engagement, tb_records, chart, db):
        if (code in WRONG_HOMES and float(g.debit_amount or 0) > 0
                and HMRC_PAYE.search(f"{g.description or ''} {g.reference or ''}")):
            paid.setdefault(code, []).append(g)
    findings, journals = [], []
    room = -paye_after(tb_records, earlier)          # the PAYE owed (a credit) the payments can clear
    for code in sorted(paid):
        lines = paid[code]
        from backend.app.services.review.point_figures import row as _row, table as _table
        total = round(sum(float(g.debit_amount or 0) for g in lines), 2)
        if total < MIN_AMOUNT:
            continue
        shown = "; ".join(f"{g.transaction_date:%d/%m/%Y} £{float(g.debit_amount):,.2f}"
                          for g in lines[:12] if g.transaction_date)
        more = " and more" if len(lines) > 12 else ""
        where = chart.name(code)
        fits = total <= room + MIN_AMOUNT
        details = (f"Payments to HMRC for PAYE and NI are coded to {code} {where} ({shown}{more}). Paying HMRC settles "
                   f"the PAYE owed; it is not a cost or corporation tax (NIM12201), so they belong on {PAYE_NIC} "
                   f"{chart.name(PAYE_NIC)}. ")
        if fits:
            details += (f"PAYE owed holds £{room:,.2f} before them, so they are moved: {_entry(PAYE_NIC, code, total, chart)}.")
        else:
            details += (f"PAYE owed holds only £{max(room, 0):,.2f}, less than the £{total:,.2f} paid: the books may "
                        f"expense HMRC payments with no payroll journal, so part of them is the employer's NI cost. "
                        f"Record the payroll from the payroll report (gross pay, employer's NI, PAYE owed), then move "
                        f"the payments (Dr {PAYE_NIC} / Cr {code}).")
        point = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-024",
            procedure_name="Payroll: PAYE paid", severity="HIGH" if total >= 1000 else "MEDIUM",
            source_row_ref="G8 PAYE", quantified_amount=total, status="OPEN",
            finding_title=f"{len(lines)} HMRC PAYE payment(s), £{total:,.2f}, posted to {code} {where}",
            finding_details=details,
            figures=_table(["Paid to HMRC", "Amount"],
                           [_row(f"{g.transaction_date:%d/%m/%Y}", float(g.debit_amount)) for g in lines if g.transaction_date]
                           + [_row("PAYE owed before them", room, strong=not fits)]))
        findings.append(point)
        if fits:
            journals.append(_journal(engagement, counter, f"HMRC PAYE payments moved from {where} to PAYE",
                                     PAYE_NIC, code, total, chart, point))
            room -= total
    return findings, journals
