"""U-DLA-002 A director's loan over £10,000 at any time in the year: a beneficial loan (ITEPA 2003 s175, s180). The
director is taxed on the interest the official rate would have charged, less any interest paid, and the company pays
Class 1A NIC on it (P11D). The test is the balance at any time, not at the year end, so the
loan is followed day by day through the ledger, director's loan account by account."""

from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, TBRecord

BENEFICIAL_LOAN_LIMIT = 10000.0          # ITEPA 2003 s180: no charge while all loans stay at or under £10,000
# The official rate of interest (EIM26104): from the date it applies
OFFICIAL_RATES = ((date(2025, 4, 6), 0.0375), (date(2023, 4, 6), 0.0225), (date(2021, 4, 6), 0.02))


def official_rate(day: date) -> float:
    return next((rate for start, rate in OFFICIAL_RATES if day >= start), OFFICIAL_RATES[-1][1])


def peak_balances(tb_records: List[TBRecord], lines, dla_codes) -> List[Tuple[str, float, Optional[date], float, float]]:
    """Per director's loan account: (account, highest overdrawn balance, its date, opening, closing). Overdrawn is a
    debit (the director owes the company). The opening is the TB's when it has one, else the closing less the year's
    ledger lines."""
    out = []
    for t in tb_records:
        if t.std_code not in dla_codes:
            continue
        mine = sorted((l for l in lines if l.code in dla_codes and l.account == t.raw_account_name), key=lambda l: l.when)
        closing = float(t.net_amount or 0)
        opening = (float(t.opening_amount) if t.opening_amount is not None
                   else closing - sum(l.debit - l.credit for l in mine))
        running, peak, when = opening, opening, None
        by_day: Dict[date, float] = {}
        for l in mine:
            by_day[l.when] = by_day.get(l.when, 0.0) + l.debit - l.credit
        for day in sorted(by_day):
            running += by_day[day]
            if running > peak:
                peak, when = running, day
        out.append((t.raw_account_name, round(peak, 2), when, round(opening, 2), round(closing, 2)))
    return out


def beneficial_loan_points(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session,
                           dla_codes) -> List[AuditFinding]:
    from backend.app.services.sop.common import gl_lines
    lines = gl_lines(str(engagement.id), tb_records, db)
    findings = []
    for account, peak, when, opening, closing in peak_balances(tb_records, lines, dla_codes):
        if peak <= BENEFICIAL_LOAN_LIMIT:
            continue
        rate = official_rate(when or engagement.period_end_date)
        average = max(0.0, (max(opening, 0.0) + max(closing, 0.0)) / 2)
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-DLA-002",
            procedure_name="Director's loan over £10,000 (beneficial loan)", severity="MEDIUM",
            source_row_ref=account[:100],
            finding_title=(f"{account}: the director owed the company up to £{peak:,.2f}"
                           + (f" on {when:%d/%m/%Y}" if when else " at the start of the year")
                           + ", over £10,000")[:255],
            finding_details=(
                f"A loan to a director of more than £10,000 at any time in the tax year is a beneficial loan (ITEPA 2003 "
                f"s175, s180), even if it is repaid by the year end (here £{max(closing, 0.0):,.2f} at the year end). "
                f"Unless interest was paid at the official rate ({rate:.2%} at that date, HMRC EIM26104), the director "
                f"is taxed on the interest not paid and the company pays Class 1A NIC on it: report it on the P11D for "
                f"each tax year. On the average of the opening and closing balance the benefit would be about "
                f"£{average * rate:,.2f} a year; the exact figure is worked per tax year (averaging or day by day, "
                f"EIM26215). It does not apply to money that was a dividend declared before it was taken (an interim "
                f"dividend paid as drawn), or if interest was charged at the official rate: check, and add it to the "
                f"P11D if not."),
            quantified_amount=peak, status="OPEN"))
    return findings
