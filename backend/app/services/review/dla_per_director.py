"""U-DLA-010: a director overdrawn while another is owed, hidden by the directors' net balance. Each director's loan is
their own: an amount owed by a director is a debtor and an amount owed to one a creditor, never set off in the accounts
(SI 2008/409 Sch 1 para 8; FRS 102 2.52), and s455 is charged on each participator's loan outstanding at the year end
unless repaid within nine months (CTA 2010 s455, s458). The tax computation works the s455 on the net balance, so a
director's overdrawn loan covered by another's credit gets none: the point names it and asks when it was repaid."""

from datetime import date
from typing import Dict, List

from backend.app.models.database import AuditFinding, ClientEngagement, TBRecord

MIN_AMOUNT = 100.0


def _nine_months_after(d: date) -> date:
    y, m = divmod(d.month - 1 + 9, 12)
    year, month = d.year + y, m + 1
    days = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(d.day, days[month - 1]))


def director_balances(tb_records: List[TBRecord], directors: List[str]) -> Dict[str, float]:
    """{director: their loan's balance, debit + (overdrawn)}, when two or more directors have their own account."""
    from backend.app.services.workbook.dla_directors import NOT_NAMED, director_groups
    groups = director_groups(tb_records, directors)
    out = {}
    for director, names in groups.items():
        if director == NOT_NAMED:
            continue
        out[director] = round(sum(float(t.net_amount or 0.0) for t in tb_records if t.raw_account_name in names), 2)
    return out


def overdrawn_hidden(engagement: ClientEngagement, tb_records: List[TBRecord]) -> List[AuditFinding]:
    from backend.app.services.tax.s455 import s455_rates
    from backend.app.services.workbook.dla_directors import DLA_CODES, _directors
    balances = director_balances(tb_records, _directors(engagement))
    overdrawn = {d: b for d, b in balances.items() if b >= MIN_AMOUNT}
    owed = {d: -b for d, b in balances.items() if b <= -MIN_AMOUNT}
    if not overdrawn or not owed:
        return []
    net = round(sum(float(t.net_amount or 0.0) for t in tb_records if t.std_code in DLA_CODES), 2)
    hidden = round(sum(overdrawn.values()) - max(net, 0.0), 2)
    if hidden < MIN_AMOUNT:
        return []
    rate = s455_rates()[1]
    deadline = _nine_months_after(engagement.period_end_date) if engagement.period_end_date else None
    listing = "; ".join(f"{d} £{b:,.2f}" for d, b in sorted(overdrawn.items(), key=lambda x: -x[1]))
    others = "; ".join(f"{d} £{b:,.2f}" for d, b in sorted(owed.items(), key=lambda x: -x[1]))
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-DLA-010",
        procedure_name="Directors' loans: each director on their own", severity="HIGH",
        source_row_ref="Director's loan (G3)",
        finding_title=f"Director overdrawn £{sum(overdrawn.values()):,.2f} hidden by another director's credit",
        finding_details=(
            f"Overdrawn at the year end: {listing}. Owed to: {others}. Together they net to "
            f"£{abs(net):,.2f} {'owed to the directors' if net < 0 else 'overdrawn'}, but each director's loan is their "
            f"own: the overdrawn balance is a debtor and the credit a creditor, not set off in the accounts (SI 2008/409 "
            f"Sch 1 para 8; the G3 lead shows both), and s455 is charged per director (CTA 2010 s455): about "
            f"£{hidden * rate:,.2f} at {rate:.2%} on £{hidden:,.2f}, unless repaid"
            + (f" by {deadline:%d/%m/%Y} (nine months after the year end)" if deadline else " within nine months")
            + ". The tax computation works s455 on the net balance, so it has none for this. Client question: has "
              "the overdrawn director repaid the loan, and on what date (or is a dividend or salary to clear it)? If "
              "not repaid in time, add the s455 to the CT600A."),
        quantified_amount=hidden, status="OPEN")]
