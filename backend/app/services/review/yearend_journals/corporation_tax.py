"""Last year's corporation tax over or under provided: what is left on the CT creditor once this year's charge is
taken off."""

from typing import Dict, List, Tuple

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.yearend_journals.common import MIN_AMOUNT, _entry, _journal, _point

# ---------------------------------------------------------------------------------------------------------------
# Last year's corporation tax over / under provided (what is left on 5310 is cleared to 3810 before this year's
# charge)
# ---------------------------------------------------------------------------------------------------------------
CT_CREDITOR, CT_CHARGE_CODE, CT_PRIOR_YEAR = 5310, 3800, 3810
S455_DEBTORS = (4450, 4550)


def ct_prior_year(engagement: ClientEngagement, chart: ChartLookup, counter: List[int], after: Dict[int, float],
                  lines: list) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """What is left on the corporation tax creditor once this year's charge in the books is taken off is last year's
    tax over or under provided. A debit left (more paid than provided) goes to the P&L as prior year tax; a credit
    left after HMRC payments this year, and smaller than the balance brought forward, was over provided and is
    released; a credit with no payment this year may still be owed, so it is only a point."""
    owed = round(after.get(CT_CREDITOR, 0.0), 2)                     # credit negative
    charge = round(after.get(CT_CHARGE_CODE, 0.0), 2)                # this year's charge already in the books
    left = round(owed + charge, 2)                                   # debit positive: last year's part
    if abs(left) < MIN_AMOUNT:
        return [], []
    ct_lines = [l for l in lines if l.code == CT_CREDITOR]
    paid = round(sum(l.debit for l in ct_lines), 2)
    movement = round(sum(l.debit - l.credit for l in ct_lines), 2)
    brought_forward = round(owed - movement, 2)
    s455 = any(abs(after.get(c, 0.0)) >= MIN_AMOUNT for c in S455_DEBTORS)
    name = lambda c: chart.name(c, str(c))
    # The point's figures (one table for every outcome below): what came forward, what was paid, this year's charge,
    # what is left (credits owed in brackets)
    from backend.app.services.review.point_figures import amounts
    figures = amounts([("Brought forward from last year", brought_forward), ("Paid to HMRC this year", paid),
                       ("This year's charge in the books", charge), ("Left on the account", left, True)])
    # The client posted this year's own provision (a charge in the books): what is left on the account then mixes
    # this year's provision, last year's tax, interest and HMRC's reallocations, so it is not last year's over or under
    # provision. Last year's provision is checked against the CT600 / the HMRC account, so it is asked for instead
    # of guessing a journal
    if abs(charge) >= MIN_AMOUNT:
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-CT-002",
            procedure_name="Corporation tax: last year's tax", severity="MEDIUM", source_row_ref=name(CT_CREDITOR)[:100],
            finding_title=f"Corporation tax: last year's provision £{-brought_forward:,.2f} to check against the HMRC "
                          f"CT account"[:255],
            finding_details=(f"Last year's corporation tax brought forward was £{-brought_forward:,.2f}; £{paid:,.2f} was "
                             f"paid to HMRC this year and the books already hold this year's own charge (£{charge:,.2f}), "
                             f"so the £{abs(left):,.2f} left on the account cannot be read as last year's over or under "
                             f"provision. From the HMRC CT account for last year's period, take the liability, interest "
                             f"and any repayment or reallocation: last year's provision less that liability is the over "
                             f"(or under) provision to {CT_PRIOR_YEAR} {name(CT_PRIOR_YEAR)}; interest goes to the HMRC "
                             f"interest code."),
            quantified_amount=abs(left), status="OPEN", figures=figures)
        return [f], []
    if left > 0:
        entry = _entry(CT_PRIOR_YEAR, CT_CREDITOR, left, chart)
        f = _point(engagement, "U-CT-002", "Corporation tax: last year's tax",
                   f"Last year's corporation tax under provided by £{left:,.2f}",
                   f"After this year's charge (£{charge:,.2f}), the corporation tax account still shows a debit of "
                   f"£{left:,.2f}: more was paid to HMRC than last year's accounts provided. It is last year's tax, "
                   f"so it goes to {CT_PRIOR_YEAR} {name(CT_PRIOR_YEAR)} and the account then shows this year's tax "
                   f"only. A journal is proposed (Journals tab): {entry}. Check against the HMRC statement.",
                   left, entry)
        f.figures = figures
        return [f], [_journal(engagement, counter, "Corporation tax: last year's tax under provided", CT_PRIOR_YEAR,
                              CT_CREDITOR, left, chart, f)]
    over = -left
    if paid >= MIN_AMOUNT and over < -brought_forward and not s455:
        entry = _entry(CT_CREDITOR, CT_PRIOR_YEAR, over, chart)
        f = _point(engagement, "U-CT-002", "Corporation tax: last year's tax",
                   f"Last year's corporation tax over provided by £{over:,.2f}",
                   f"Last year's tax brought forward was £{-brought_forward:,.2f}; £{paid:,.2f} was paid to HMRC this "
                   f"year and, after this year's charge (£{charge:,.2f}), £{over:,.2f} of it is still on the account. "
                   f"Released to {CT_PRIOR_YEAR} {name(CT_PRIOR_YEAR)}: {entry} (Journals tab). Confirm with the HMRC "
                   f"statement that nothing more is due for last year.", over, entry)
        f.figures = figures
        return [f], [_journal(engagement, counter, "Corporation tax: last year's tax over provided", CT_CREDITOR,
                              CT_PRIOR_YEAR, over, chart, f)]
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-CT-002",
        procedure_name="Corporation tax: last year's tax", severity="HIGH" if over >= 1000 else "MEDIUM",
        source_row_ref=name(CT_CREDITOR)[:100],
        finding_title=f"Corporation tax: £{over:,.2f} from earlier years still owed at the year end",
        finding_details=(f"After this year's charge (£{charge:,.2f}), the corporation tax account still owes £{over:,.2f} "
                         + ("with no payment to HMRC this year" if paid < MIN_AMOUNT else
                            "(an s455 balance is in the books, so it is not released automatically)" if s455 else
                            "") + ". Either last year's tax is unpaid (check the HMRC statement and the due date) or it "
                         f"was over provided (release it to {CT_PRIOR_YEAR} {name(CT_PRIOR_YEAR)})."),
        quantified_amount=over, status="OPEN", figures=figures)
    return [f], []
