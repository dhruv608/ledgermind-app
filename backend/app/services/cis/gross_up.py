"""IND-CON-04 (construction industry rule): sales grossed up for CIS. A subcontractor's sale is the gross
invoice; the contractor pays it less the CIS it deducts and hands to HMRC (FA 2004 s61; CISR15000), which the company
gets back against its PAYE or as a repayment. When the contractors' payment and deduction statements typed on the CIS
screen show more CIS suffered for the period than the books hold, the difference never reached the books: the sales
were posted at the net amount received. Proposed: Dr CIS suffered (4421) / Cr sales, for the difference (the
accountant approves it). Nothing is proposed before the statements are typed."""

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.cis.codes import CIS_SUFFERED

MIN_GAP = 1.0


def statements_v_books(engagement: ClientEngagement, db: Session, setup_cis) -> Optional[Tuple[float, float, int]]:
    """(CIS suffered per the statements typed, per the books, months typed) for the period; None with none typed."""
    from backend.app.services.cis.hmrc import hmrc_screen
    screen = hmrc_screen(engagement, db, setup_cis or {})
    if not screen.get("on"):
        return None
    typed = [m for m in screen["months"] if m["hmrc"].get("suffered_statements") is not None]
    if not typed:
        return None
    statements = round(sum(float(m["hmrc"]["suffered_statements"]) for m in typed), 2)
    books = round(sum(float(m["books"].get("suffered") or 0) for m in typed), 2)
    return statements, books, len(typed)


def sales_code(tb_records: List[TBRecord], chart) -> int:
    """The sales account the gross-up goes to: the one with the most sales in the trial balance."""
    sales = [t for t in tb_records if t.std_code is not None and t.std_code < 1000 and float(t.net_amount or 0) < 0]
    return int(min(sales, key=lambda t: float(t.net_amount or 0)).std_code) if sales else 0


def gross_up(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session, setup_cis, chart,
             counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.review.yearend_journals import _entry, _journal, _point
    found = statements_v_books(engagement, db, setup_cis)
    if found is None:
        return [], []
    statements, books, months = found
    gap = round(statements - books, 2)
    if gap < MIN_GAP:
        return [], []
    sales = sales_code(tb_records, chart)
    entry = _entry(CIS_SUFFERED, sales, gap, chart)
    point = _point(
        engagement, "IND-CON-04", "CIS: sales grossed up",
        f"CIS suffered £{gap:,.2f} per the contractors' statements is not in the books: sales posted net",
        (f"The contractors' payment and deduction statements typed for {months} tax month(s) show CIS suffered of "
         f"£{statements:,.2f}; the books hold £{books:,.2f}. The £{gap:,.2f} difference was deducted by the "
         f"contractors and paid to HMRC for the company, so the sale is the gross invoice and the CIS is recoverable "
         f"(FA 2004 s61; CISR15000): the sales were posted at the net amount received. A journal is proposed "
         f"(Journals tab): {entry}. Reject it if a statement belongs to another year."), gap, entry)
    return [point], [_journal(engagement, counter, "CIS: sales grossed up for the CIS deducted by contractors",
                              CIS_SUFFERED, sales, gap, chart, point)]
