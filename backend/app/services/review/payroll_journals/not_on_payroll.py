"""U-PAY-025 an account named as wages that the payroll does not hold: people paid outside the payroll.

The payroll report covers the year and its gross pay is already in the other pay accounts (staff, directors), so a
further account named 'Direct Wages', 'Casual Wages' or 'Wages - not on payroll' is pay to people the payroll does
not run: instructors, casual or labour-only workers paid from the bank. Paid with no PAYE, they are taken as
self-employed, so the cost is subcontractors (1440 in cost of sales, 3020 in employee costs, the firm's codes), not
employees' wages (FRS 102 s28 covers employees only). Their status is the first question (BIM66200 labour-only
subcontractors; ESM: if they are employees, PAYE should have been run), so the journal comes with a client query.
Typically 'Direct Wages' of instructors go to 1440, 'Casual Wages' and 'Wages - not on payroll' to 3020. U-SUB-003
lists the people by name; this moves the cost."""

import re
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.payroll_journals.common import (
    DIRECTOR_PAY_NAME, MIN_AMOUNT, WAGE_COST_CODES, _entry, _journal, _lines, _month, _names_person)

# Staff pay accounts that can hold pay outside the payroll; where it goes (the firm's subcontractor codes)
TO_SUBCONTRACTORS = {1500: 1440, 3000: 3020, 3004: 3020}
PAY_NAME = re.compile(r"\b(?:wages?|salar(?:y|ies)|labou?r|casual|staff)\b", re.I)
NOT_PAY_NAME = re.compile(r"\b(?:payable|owed|accrued|accruals?|control|net|nic?s?|national insurance|pension|"
                          r"expenses?|costs? of sales|director)\b", re.I)
MONTHS_COVERED = 10             # the payroll report covers the year: pay runs in this many months at least
EXPLAINED = 0.01                # the other pay accounts hold the payroll's gross within this share (or £100)
NAMED_ON_PAYROLL = 0.10         # lines naming a payroll employee above this share of the account: on the payroll


def _moved_by(earlier: List[ProposedJournal]) -> Dict[int, float]:
    """Each code's change (debit +) from the journals this review has already proposed."""
    out: Dict[int, float] = {}
    for j in earlier:
        lines = list(getattr(j, "lines", None) or [])
        if lines:
            for l in lines:
                c = int(l.account_code)
                out[c] = out.get(c, 0.0) + float(l.debit or 0) - float(l.credit or 0)
            continue
        a = float(j.amount or 0)
        if j.debit_code is not None:
            out[j.debit_code] = out.get(j.debit_code, 0.0) + a
        if j.credit_code is not None:
            out[j.credit_code] = out.get(j.credit_code, 0.0) - a
    return out


def pay_not_on_payroll(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                       counter: List[int], earlier: List[ProposedJournal]
                       ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.review.payroll_period import usable
    records, _ = usable(engagement, db)
    months = {_month(r) for r in records if _month(r) is not None}
    gross = round(sum(float(r.gross_pay or 0) for r in records), 2)
    if len(months) < MONTHS_COVERED or gross < MIN_AMOUNT:
        return [], []
    moved = _moved_by(earlier)
    by_code: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code in WAGE_COST_CODES:
            by_code[t.std_code] = by_code.get(t.std_code, 0.0) + float(t.net_amount or 0)
    pay_total = sum(by_code.values()) + sum(moved.get(c, 0.0) for c in WAGE_COST_CODES)
    candidates = [t for t in tb_records if t.std_code in TO_SUBCONTRACTORS and PAY_NAME.search(t.raw_account_name or "")
                  and not NOT_PAY_NAME.search(t.raw_account_name or "")
                  and not DIRECTOR_PAY_NAME.search(t.raw_account_name or "")]
    for t in candidates:
        amount = round(float(t.net_amount or 0), 2)
        # Already moved off its code by this review (net pay paid into the costs): not this case
        if amount < max(1000.0, MIN_AMOUNT) or moved.get(t.std_code, 0.0) <= -0.5 * amount:
            continue
        others = round(pay_total - amount, 2)
        if abs(others - gross) > max(EXPLAINED * gross, 100.0):
            continue
        # The ledger's lines name someone the payroll pays: on the payroll after all
        people = {r.employee_name for r in records if r.employee_name}
        named = sum(float(g.debit_amount or 0) for code, g in _lines(engagement, tb_records, chart, db)
                    if code == t.std_code and any(_names_person(g.description or "", p) for p in people))
        if named > NAMED_ON_PAYROLL * amount:
            continue
        target = TO_SUBCONTRACTORS[t.std_code]
        entry = _entry(target, t.std_code, amount, chart)
        name = t.raw_account_name.strip()
        point = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-025",
            procedure_name="Payroll: pay outside the payroll", severity="MEDIUM", source_row_ref=name[:100],
            quantified_amount=amount, suggested_journal=entry, status="OPEN",
            finding_title=f"'{name}' £{amount:,.2f} is not in the payroll: people paid outside it"[:255],
            finding_details=(
                f"The payroll report covers {len(months)} months with gross pay of £{gross:,.2f}, and the other pay "
                f"accounts already hold £{others:,.2f} of it. '{name}' (£{amount:,.2f}) is on top: pay to people the "
                f"payroll does not run, with no PAYE. They are taken as self-employed, so the cost is moved to "
                f"subcontractors (Journals tab): {entry}. If they are employees, PAYE should have been run on this pay "
                f"(BIM66200, ESM): the client confirms.\n\nQuery to the client: Payments of £{amount:,.2f} were made "
                f"to people not on the payroll ('{name}'). Please confirm they are self-employed (their invoices or "
                f"contracts), or whether they should have been on the payroll."))
        return [point], [_journal(engagement, counter, f"Pay outside the payroll ('{name}') moved to subcontractors",
                                  target, t.std_code, amount, chart, point)]
    return [], []
