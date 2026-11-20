"""U-PRE-002 / U-ACC-003 last year's prepayment or accrual not released."""

from backend.app.models.database import AuditFinding, ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, PREPAYMENTS
from typing import List
from sqlalchemy.orm import Session

from backend.app.services.review.payroll_journals.common import MIN_AMOUNT, _lines


# ---------------------------------------------------------------------------------------------------------------
# U-PRE-002 / U-ACC-003 Last year's prepayment or accrual not released
# ---------------------------------------------------------------------------------------------------------------
ACCRUALS = 5360


def _brought_forward_not_released(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                                  db: Session, code: int, sign: int, make) -> List[AuditFinding]:
    """Accounts on `code` whose balance brought forward (debit for sign=1, credit for sign=-1) is still there unchanged
    at the year end, with no ledger line and no approved journal releasing it."""
    from backend.app.services.tax.ct_computation import final_balances
    rows = [t for t in tb_records if t.std_code == code and t.opening_amount is not None]
    if not rows:
        return []
    moved_names = {(g.raw_account_name or "").lower().strip() for c, g in _lines(engagement, tb_records, chart, db)
                   if c == code and abs(float(g.net_amount or 0)) >= 0.01
                   and "opening" not in (g.description or "").lower()}
    after = final_balances(engagement.id, tb_records, db)
    journal_effect = after.get(code, 0.0) - sum(float(t.net_amount or 0) for t in tb_records if t.std_code == code)
    out = []
    for t in rows:
        opening, closing = float(t.opening_amount or 0) * sign, float(t.net_amount or 0) * sign
        name = t.raw_account_name.lower().strip()
        if opening < MIN_AMOUNT or abs(closing - opening) >= 0.01 or name in moved_names or name.split(":")[-1].strip() in moved_names:
            continue
        if journal_effect * sign <= -MIN_AMOUNT:    # an approved journal already released some of it
            continue
        out.append(make(t, opening))
    return out


def accrual_not_released(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                         db: Session) -> List[AuditFinding]:
    def make(t: TBRecord, amount: float) -> AuditFinding:
        return AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ACC-003",
            procedure_name="Accruals: last year's accrual", severity="MEDIUM" if amount < 1000 else "HIGH",
            source_row_ref=t.raw_account_name[:100],
            finding_title=f"{t.raw_account_name[:80]}: last year's accrual £{amount:,.2f} has not been released",
            finding_details=(f"The accrual brought forward (£{amount:,.2f}) is still in the books unchanged at the year "
                             f"end. Its cost was charged last year; when the bill came in this year it was charged again, "
                             f"so this year's costs are likely overstated. Release it: Dr {ACCRUALS} {chart.name(ACCRUALS)} "
                             f"£{amount:,.2f} / Cr the cost it was for (see last year's accruals schedule), then add this "
                             f"year's accruals (the accruals points). Enter last year's accruals line by line in the "
                             f"Accruals and prepayments area: each is then reversed to its cost, and next year they come "
                             f"forward by themselves.\n\nQuery to the client: Please send last year's accruals list "
                             f"(each supplier, what the bill was for and the amount)."),
            quantified_amount=round(amount, 2), suggested_journal=None, status="OPEN")
    return _brought_forward_not_released(engagement, tb_records, chart, db, ACCRUALS, -1, make)


# ---------------------------------------------------------------------------------------------------------------
# U-PRE-002 Last year's prepayment not released
# ---------------------------------------------------------------------------------------------------------------
def prepayment_not_released(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                            db: Session) -> List[AuditFinding]:
    def make(t: TBRecord, opening: float) -> AuditFinding:
        return AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PRE-002",
            procedure_name="Prepayments: last year's prepayment", severity="MEDIUM" if opening < 1000 else "HIGH",
            source_row_ref=t.raw_account_name[:100],
            finding_title=f"{t.raw_account_name[:80]}: last year's prepayment £{opening:,.2f} has not been released",
            finding_details=(f"The prepayment brought forward (£{opening:,.2f}) is still in the books unchanged at the year "
                             f"end: the costs it paid in advance belong to this year. Release it: Dr the cost it was for "
                             f"(see last year's prepayment schedule) / Cr {PREPAYMENTS} {chart.name(PREPAYMENTS)} £{opening:,.2f}, "
                             f"then add this year's prepayments (the prepayments points). The cost is not guessed: in "
                             f"practice it is insurance, rent, wages or a fixed asset, never the same one. Enter last "
                             f"year's prepayments line by line in the Accruals and prepayments area: each is then released "
                             f"to its cost, and next year they come forward by themselves.\n\nQuery to the client: Please "
                             f"send last year's prepayments list (each supplier, what was paid in advance and the amount)."),
            quantified_amount=round(opening, 2), suggested_journal=None, status="OPEN")
    return _brought_forward_not_released(engagement, tb_records, chart, db, PREPAYMENTS, 1, make)
