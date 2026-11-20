"""U-LOAN-REPAY: loan repayments posted to a profit and loss account (e.g. BBLS repayments sitting in a cost account).

Repaying a loan's principal is not a cost of the business: it takes the liability down (CTM61080, BIM35575: capital,
not revenue; capital repayments are never allowable). Each lender's repayments in a P&L account are one point with the
journal to the loan written in it; the accountant splits capital from interest with the lender's statement. Only a
named lender or a line that says it repays a loan: a charity 'loan' scheme, interest lines and fees stay where they
are."""

import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup

REF, NAME = "U-LOAN-REPAY", "Loans: repayments posted as a cost"
LENDER = re.compile(r"\bbbls?\b|bounce ?back loan|\bcbils\b|business loan|loan repay\w*|repay\w* (?:of )?(?:the )?loan|"
                    r"funding circle|\biwoca\b|\bfleximize\b|\bcapify\b|\byoulend\b|\bliberis\b|esme loans|"
                    r"\bthincats\b|marketfinance|boost capital|\bbbl\b", re.I)
NOT_REPAYMENT = re.compile(r"\binterest\b|\bfees?\b|\bcharges?\b|arrangement|\bcharity\b|\bdonation", re.I)
LOAN_CODES = (5100, 5500)                    # bank loans due within one year / after one year (firm chart)
MIN_AMOUNT = 100.0


def _lender(text: str) -> Optional[str]:
    m = LENDER.search(text or "")
    if not m or NOT_REPAYMENT.search(text or ""):
        return None
    word = m.group(0).lower()
    if "bbl" in word or "bounce" in word:
        return "BBLS loan"
    return word.capitalize() if "loan" in word else word.title()


def loan_account(tb_records: List[TBRecord]) -> Optional[int]:
    """The client's bank loan code with a balance (after one year first: a repayment takes the loan down)."""
    held = {}
    for t in tb_records:
        if t.std_code in LOAN_CODES or (t.std_code and 5501 <= t.std_code <= 5509):
            held[t.std_code] = held.get(t.std_code, 0.0) + float(t.net_amount or 0)
    for code in (5500, 5100) + tuple(sorted(c for c in held if c not in LOAN_CODES)):
        if abs(held.get(code, 0.0)) >= 1:
            return code
    return None


def loan_repayment_points(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                          counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.review.payroll_journals.common import _entry, _lines
    found: Dict[Tuple[str, int], List] = {}
    for code, g in _lines(engagement, tb_records, chart, db):
        # A cost, or an asset account (fixed assets, debtors); never the bank (a loan received is a bank debit) or a
        # liability
        if not (chart.is_pl(code) or 4000 <= code < 4800) or float(g.debit_amount or 0) <= 0:
            continue
        lender = _lender(f"{g.description or ''} {g.reference or ''}")
        if lender:
            found.setdefault((lender, code), []).append(g)
    findings: List[AuditFinding] = []
    journals: List[ProposedJournal] = []
    target = loan_account(tb_records)
    from backend.app.services.review.point_figures import row as _row, table as _table
    for (lender, code), lines in sorted(found.items()):
        amount = round(sum(float(g.debit_amount or 0) - float(g.credit_amount or 0) for g in lines), 2)
        if amount < MIN_AMOUNT:
            continue
        where = f"{code} {chart.name(code)}"
        detail = (f"{len(lines)} payment(s) to {lender}, £{amount:,.2f}, are in {where}, not the loan. Repaying a "
                  f"loan is not a cost: it takes the loan down (CTM61080; capital, not revenue). ")
        if target is not None:
            entry = _entry(target, code, amount, chart)
            detail += (f"Check them against the lender's statement: the capital part moves to the loan ({entry} for "
                       f"the whole), the interest part stays a cost.")
        else:
            entry = ""
            detail += "The books have no loan account with a balance: find the loan, then move the repayments to it."
        f = AuditFinding(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=REF,
                         procedure_name=NAME, severity="HIGH" if amount >= 1000 else "MEDIUM",
                         source_row_ref=where[:100], finding_title=f"{lender} repayments £{amount:,.2f} in {where}"[:255],
                         finding_details=detail, quantified_amount=amount, suggested_journal=entry or None,
                         status="OPEN",
                         figures=_table(["Paid", "Amount"],
                                        [_row(f"{g.transaction_date:%d/%m/%Y}" if g.transaction_date else "-",
                                              float(g.debit_amount or 0) - float(g.credit_amount or 0)) for g in lines]
                                        + [_row(f"Total in {where}", amount, strong=True)]))
        findings.append(f)
    # A point with the journal written in it, never a proposed journal: repayments often sit in the interest account
    # and stay there unless the lender's statement splits capital from interest
    return findings, journals
