"""U-BS-SIDE: a debtor code that ends the year in credit (e.g. an intercompany balance on 4470 'Amounts owed by group
undertakings').

FRS 102 s2: assets and liabilities are not offset unless a rule allows it, so money the company owes is shown in
creditors, not as a negative debtor. Raises a point with the reclassification to the matching creditor code; no
journal is proposed, as the firm decides whether to move the balance by journal or leave it with a note."""

from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup

REF, NAME = "U-BS-SIDE", "Balance sheet: a debtor in credit"
# Debtor code -> the creditor code of the same kind (firm chart)
CREDITOR_OF: Dict[int, int] = {4420: 5350, 4470: 5410, 4471: 5411, 4472: 5413, 4473: 5414, 4474: 5415}
MIN_AMOUNT = 100.0


def wrong_side_points(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                      db: Session) -> List[AuditFinding]:
    from backend.app.services.tax.ct_computation import final_balances
    after = final_balances(engagement.id, tb_records, db)
    out: List[AuditFinding] = []
    for debtor, creditor in CREDITOR_OF.items():
        balance = round(after.get(debtor, 0.0), 2)
        if balance > -MIN_AMOUNT:
            continue
        names = sorted({t.raw_account_name for t in tb_records if t.std_code == debtor and t.raw_account_name})
        entry = (f"Dr {debtor} {chart.name(debtor)} (£{-balance:,.2f}) / Cr {creditor} {chart.name(creditor)} "
                 f"(£{-balance:,.2f})")
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=REF, procedure_name=NAME,
            severity="MEDIUM", source_row_ref=f"{debtor} {chart.name(debtor)}"[:100],
            finding_title=f"{debtor} {chart.name(debtor)} is £{-balance:,.2f} in credit: money owed by the company"[:255],
            finding_details=(f"{', '.join(names) or chart.name(debtor)} ends the year £{-balance:,.2f} in credit on a "
                             f"debtor code: the company owes this money. It belongs in creditors ({creditor} "
                             f"{chart.name(creditor)}), as assets and liabilities are not offset (FRS 102 s2). "
                             f"Reclassification: {entry}. Check the balance with the other party first."),
            quantified_amount=-balance, suggested_journal=entry, status="OPEN"))
    return out
