"""
Accruals and prepayments posted, not only flagged (otherwise a bank-only job would carry no accruals at all).

When the accountant has not entered the year's accruals and prepayments line by line (models/yearend_adjustments.py,
which win), the review proposes journals for approval on the Journals tab:
  1. the accountancy fee accrual: last year's released; a new one only on a known basis (last year's approved fee
     accrual in the app, else the firm's standard fee on the Firm settings page) and never for a client paying its
     accountant monthly
  2. prepayments the Prepayments SOP finds (a yearly payment running past the year end): the future portion
  3. a regular monthly cost with no cost in the final month (cost in 11 of 12 months): one average month accrued
Each journal is proposed, never posted: the accountant approves or rejects it.
"""

import re
from datetime import timedelta
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.models.yearend_adjustments import YearEndAdjustment
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.adjustments import ACCOUNTANCY_FEES, ACCRUALS, PREPAYMENTS, _journal

MIN_PORTION = 25.0          # a prepaid portion or accrual under this is not worth a journal
# The client's own deferred income account by its name ('Accruals - Deferred Income', 'Income in advance')
DEFERRED_INCOME_NAME = re.compile(r"deferred (income|revenue)|income (received )?in advance|revenue in advance", re.I)
ACCRUED_INCOME = 4950
FINAL_MONTH_MIN = 11        # months with a cost before the final month's missing one is accrued
FEE_MARGIN = 1.25           # a brought forward accrual up to this times the year's accountancy fees is taken as the fee


def firm_accountancy_fee(db: Session) -> Optional[float]:
    """The firm's standard accountancy fee for a year's accounts (Firm settings page), when it has saved one."""
    import json
    from backend.app.models.firm_settings import FirmSetting
    row = db.get(FirmSetting, "accountancy_fee")
    try:
        amount = json.loads(row.value).get("amount") if row is not None else None
    except ValueError:
        amount = None
    return round(float(amount), 2) if amount else None


def _approved(engagement_id: str, db: Session) -> Set[Tuple[str, float]]:
    return {((j.description or "").strip(), round(float(j.amount or 0), 2)) for j in db.query(ProposedJournal).filter(
        ProposedJournal.engagement_id == engagement_id, ProposedJournal.status == "APPROVED")}


def _point(engagement: ClientEngagement, ref: str, name: str, title: str, details: str, amount: float,
           entry: str, row: str = "") -> AuditFinding:
    return AuditFinding(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=ref,
                        procedure_name=name, severity="LOW", source_row_ref=row[:100], finding_title=title[:255],
                        finding_details=details, quantified_amount=round(amount, 2), suggested_journal=entry,
                        status="OPEN")


def _last_fee(engagement: ClientEngagement, db: Session, tb_records: List[TBRecord]) -> Tuple[float, str]:
    """Last year's accountancy fee accrual and where it came from: last year's job in the app (its approved fee
    accrual journal); else the accrual brought forward on 5360 when it is about the accountancy fees charged this
    year (last year's fee is paid this year); else the firm's standard fee (Firm settings); else those fees. A brought
    forward accrual well over the year's fees holds more than the fee and is not taken as it."""
    from backend.app.services.review.last_year import last_year_job
    try:
        last = last_year_job(engagement, db)
    except Exception:
        last = None
    if last is not None:
        fee = sum(float(j.amount or 0) for j in db.query(ProposedJournal).filter(
            ProposedJournal.engagement_id == last.id, ProposedJournal.status == "APPROVED",
            ProposedJournal.debit_code == ACCOUNTANCY_FEES, ProposedJournal.credit_code == ACCRUALS))
        if fee >= MIN_PORTION:
            return round(fee, 2), "last year's approved fee accrual"
    charged = sum(float(t.net_amount or 0) for t in tb_records if t.std_code == ACCOUNTANCY_FEES)
    brought = -sum(float(t.opening_amount or 0) for t in tb_records if t.std_code == ACCRUALS)
    if brought >= MIN_PORTION and charged >= MIN_PORTION and brought <= charged * FEE_MARGIN:
        return round(brought, 2), "the accrual brought forward on 5360, about this year's accountancy fees"
    standard = firm_accountancy_fee(db)
    if standard:
        return standard, "the firm's standard accountancy fee (Firm settings)"
    if charged >= MIN_PORTION:
        return round(charged, 2), "the accountancy fees charged this year, last year's fee paid this year"
    return 0.0, ""


# A client paying its accountant in this many months of the year is on a monthly fee: nothing to accrue at the year end
MONTHLY_FEE_MONTHS = 10
FEE_VAT_RATE = 0.20          # VAT on the accountant's fee (standard rate, VATA 1994 s2)


def _new_fee(engagement: ClientEngagement, db: Session, tb_records: List[TBRecord]) -> Tuple[float, str]:
    """This year's accountancy fee accrual: only on a known basis (last year's approved fee accrual in the app, or the
    firm's standard fee), and never for a client on a monthly fee. A fee accrual brought forward is released, not
    accrued again, and this year's fees paid are not a fee still owed."""
    fee, source = _last_fee(engagement, db, tb_records)
    if source not in ("last year's approved fee accrual", "the firm's standard accountancy fee (Firm settings)"):
        return 0.0, ""
    if _pays_monthly(engagement, db, tb_records):
        return 0.0, ""
    profile = getattr(engagement, "profile", None)
    from backend.app.services.setup.profile_service import confirmed_fields
    if (source.startswith("the firm's standard") and profile is not None and not profile.is_vat_registered
            and "is_vat_registered" in confirmed_fields(profile)):
        # The firm's fee is typed net of VAT; a client not VAT registered cannot reclaim the VAT, so its cost and what
        # it owes are gross (accountancy is standard rated)
        return round(fee * (1 + FEE_VAT_RATE), 2), source + f", plus VAT at {FEE_VAT_RATE:.0%} (not VAT registered)"
    return fee, source


def _pays_monthly(engagement: ClientEngagement, db: Session, tb_records: List[TBRecord]) -> bool:
    """The client pays its accountant in most months of the year (a monthly fee)."""
    from backend.app.services.sop.common import gl_lines
    months = {l.when.replace(day=1) for l in gl_lines(engagement.id, tb_records, db)
              if l.code == ACCOUNTANCY_FEES and l.debit >= MIN_PORTION and l.when}
    return len(months) >= MONTHLY_FEE_MONTHS


def _last_year_journals(engagement: ClientEngagement, db: Session) -> List[ProposedJournal]:
    """Last year's approved accrual and prepayment journals (last year's job in the app): what to reverse."""
    from backend.app.services.review.last_year import last_year_job
    try:
        last = last_year_job(engagement, db)
    except Exception:
        last = None
    if last is None:
        return []
    return [j for j in db.query(ProposedJournal).filter(ProposedJournal.engagement_id == last.id,
                                                        ProposedJournal.status == "APPROVED")
            if (j.credit_code == ACCRUALS and j.debit_code != ACCRUALS) or (j.debit_code == PREPAYMENTS and j.credit_code != PREPAYMENTS)]


def _brought_forward(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session) -> float:
    """Last year's prepayment still on the prepayments account: its opening balance (the TB's opening column, else its
    balance less this year's ledger movement), when nothing moved on it during the year; 0 otherwise."""
    from backend.app.services.sop.common import code_matcher, ledger_rows
    rows = [t for t in tb_records if t.std_code == PREPAYMENTS]
    if not rows:
        return 0.0
    code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))
    moved = sum(float(tx.net_amount or 0) for tx in ledger_rows(str(engagement.id), db)
                if code_of(tx.raw_account_name) == PREPAYMENTS)
    if abs(moved) >= MIN_PORTION:
        return 0.0
    closing = sum(float(t.net_amount or 0) for t in rows)
    opening = (sum(float(t.opening_amount or 0) for t in rows) if any(t.opening_amount is not None for t in rows)
               else closing - moved)
    return round(opening, 2) if abs(closing - opening) < MIN_PORTION else 0.0


def _had_prepayments(engagement: ClientEngagement, db: Session) -> bool:
    """Last year's closing TB (or last year's job) carried prepayments: the client has them worked."""
    from backend.app.services.review.last_year import last_year_job, prior_balances_by_code
    from backend.app.services.tax.ct_computation import final_balances
    try:
        last = last_year_job(engagement, db)
        if last is not None:
            ly_tb = db.query(TBRecord).filter(TBRecord.engagement_id == last.id).all()
            if abs(final_balances(str(last.id), ly_tb, db).get(PREPAYMENTS, 0.0)) >= MIN_PORTION:
                return True
        return abs(prior_balances_by_code(engagement, db).get(PREPAYMENTS, 0.0)) >= MIN_PORTION
    except Exception:
        return False


def accrual_prepayment_journals(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup,
                                db: Session, counter: List[int]
                                ) -> Tuple[List[AuditFinding], List[ProposedJournal], Set[str]]:
    """The proposed journals and their points, and the refs of the reminder points they replace ('U-ADJ-003' the
    fee reminder, 'U-ACC-003' / 'U-PRE-002' last year's accrual / prepayment not released)."""
    from backend.app.services.review.payroll_journals import accrual_not_released, prepayment_not_released
    findings: List[AuditFinding] = []
    journals: List[ProposedJournal] = []
    replaces: Set[str] = set()
    entered = {l.kind for l in db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == engagement.id,
                                                                  YearEndAdjustment.period == "THIS_YEAR")}
    approved = _approved(engagement.id, db)
    year_end = engagement.period_end_date
    from backend.app.services.review.adjustments import last_year_lines
    last_entered = {l.kind for l in last_year_lines(engagement, db)[0]}

    def worked(code: int) -> bool:
        """The books already hold this year's work on the account: a balance at the year end that is not last year's
        (the accountant's accruals or prepayments are posted), so nothing is proposed again. A balance released to nil
        is only last year's reversal: this year's items are still to be found (FRS 102 s2)."""
        rows = [t for t in tb_records if t.std_code == code]
        closing = sum(float(t.net_amount or 0) for t in rows)
        # (A TB of closing balances only is taken as this year's work: a balance the ledger never moved can still be
        # the client's own year-end journal, posted outside the ledger)
        opening = sum(float(t.opening_amount or 0) for t in rows)
        return abs(closing) >= MIN_PORTION and abs(closing - opening) >= MIN_PORTION

    def propose(ref: str, name: str, text: str, dr: int, cr: int, amount: float, why: str, row: str = "",
                figures: Optional[str] = None) -> None:
        amount = round(amount, 2)
        if amount < MIN_PORTION or (text[:255].strip(), amount) in approved:
            return
        approved.add((text[:255].strip(), amount))      # the same flag twice (a bill posted twice) proposed once
        entry = f"Dr {dr} {chart.name(dr)} / Cr {cr} {chart.name(cr)} £{amount:,.2f}"
        f = _point(engagement, ref, name, f"{text} £{amount:,.2f}", f"{why} A journal is proposed for approval "
                                                                      f"(Journals tab): {entry}.", amount, entry, row)
        f.figures = figures
        findings.append(f)
        journals.append(_journal(engagement, counter, text, dr, cr, amount, chart, f))

    # Last year's accruals and prepayments still on 5360 / 4900 unchanged: released, journal by journal when last
    # year's job in the app has them, else (an accrual) as last year's accountancy fee
    last_journals = _last_year_journals(engagement, db)
    for kind, unreleased, ref in (("ACCRUAL", accrual_not_released, "U-ACC-003"),
                                  ("PREPAYMENT", prepayment_not_released, "U-PRE-002")):
        if kind in entered or kind in last_entered:
            continue
        left = round(sum(float(f.quantified_amount or 0) for f in unreleased(engagement, tb_records, chart, db)), 2)
        if left < MIN_PORTION:
            continue
        mine = [j for j in last_journals if (j.credit_code == ACCRUALS) == (kind == "ACCRUAL")]
        if mine and abs(sum(float(j.amount or 0) for j in mine) - left) < 1.0:
            for j in mine:
                cost = j.debit_code if kind == "ACCRUAL" else j.credit_code
                dr, cr = (ACCRUALS, cost) if kind == "ACCRUAL" else (cost, PREPAYMENTS)
                propose(ref, f"Last year's {kind.lower()} released", f"Release last year's {j.description or kind.lower()}"[:255],
                        dr, cr, float(j.amount or 0),
                        f"Last year's {kind.lower()} ('{j.description}', approved in last year's job) is still on "
                        f"{ACCRUALS if kind == 'ACCRUAL' else PREPAYMENTS} at the year end: its cost belongs to "
                        f"{'last' if kind == 'ACCRUAL' else 'this'} year, so it is released.", chart.name(cost))
            replaces.add(ref)
        elif kind == "ACCRUAL" and not last_journals:
            fee, _ = _last_fee(engagement, db, tb_records)
            if fee and abs(fee - left) < 1.0 and not _new_fee(engagement, db, tb_records)[0]:
                # Released alone it cuts this year's fees, while the accountant releases it and accrues this year's
                # fee, which nets to nil (the fees and the accrual usually stay as in the TB). With this year's fee
                # not known, a question to the accountant, no journal
                findings.append(_point(
                    engagement, ref, "Accruals: accountancy fee",
                    f"Accountancy fee accrual: last year's £{left:,.2f} is still on {ACCRUALS}: confirm this year's fee",
                    f"Last year's accrual (£{left:,.2f}, taken as the accountancy fee) is still in the books unchanged. "
                    f"Usually it is released and this year's fee accrued, so the balance stays about the same and "
                    f"nothing needs posting. If this year's fee differs, post the difference (Dr {ACCOUNTANCY_FEES} "
                    f"{chart.name(ACCOUNTANCY_FEES)} / Cr {ACCRUALS} {chart.name(ACCRUALS)}, or the reverse); if no "
                    f"fee is owed for this year's accounts, release it (Dr {ACCRUALS} / Cr {ACCOUNTANCY_FEES}).",
                    left, "", chart.name(ACCRUALS)))
                replaces.add(ref)
            elif fee and abs(fee - left) < 1.0:
                propose(ref, "Last year's accountancy fee released", "Release last year's accountancy fee accrual",
                        ACCRUALS, ACCOUNTANCY_FEES, left,
                        f"Last year's accrual (£{left:,.2f}, taken as the accountancy fee) is still on {ACCRUALS} at "
                        f"the year end. The fee was charged last year and paid this year to the accountancy fees "
                        f"account, so it is released against the fees. If it was for another cost, reject this and "
                        f"release it to that cost.", chart.name(ACCRUALS))
                replaces.add(ref)

    # Last year's accrued income still on 4950 unchanged: work done last year, invoiced this year, so this year's sales
    # count it again; reversed to sales (FRS 102 s23, RV-005). Unlike an accrual its account is known: it is always
    # reversed to sales
    from backend.app.services.review.payroll_journals import _brought_forward_not_released
    sales = {}
    for t in tb_records:
        if t.std_code is not None and chart.is_sales(t.std_code):
            sales[t.std_code] = sales.get(t.std_code, 0.0) - float(t.net_amount or 0)
    if sales:
        sales_code = max(sales, key=sales.get)
        for t, amount in _brought_forward_not_released(engagement, tb_records, chart, db, ACCRUED_INCOME, 1,
                                                       lambda t, opening: (t, opening)):
            propose("U-ACI-001", "Accrued income: last year's reversed",
                    f"Reverse last year's accrued income ({t.raw_account_name[:80]})", sales_code, ACCRUED_INCOME,
                    amount,
                    f"Last year's accrued income (£{amount:,.2f}, work done last year and not yet invoiced then) is "
                    f"still on {ACCRUED_INCOME} unchanged at the year end. It was last year's income; once invoiced "
                    f"this year the invoice is in this year's sales too, so it is reversed against sales (FRS 102 s23). "
                    f"If part of it is still not invoiced, change the amount; then add this year's accrued income for "
                    f"work done by the year end and invoiced after it.", chart.name(sales_code))

    # Deferred income: a sales invoice whose wording gives a period running past the year end (a date range) is partly
    # next year's income: that part is a liability, not this year's sales (Dr Sales / Cr 5360; FRS 102 s23 RV-005;
    # BIM40070: taxed as the accounts recognise it). Only a date range the wording states: 'annual' alone is a guess.
    # E.g. a service invoiced before the year end for 17 Oct to 16 Jan: the days after the year end are deferred
    from backend.app.services.sop.common import gl_lines
    from backend.app.services.sop.prepayments import service_period
    # A client that runs its own deferred income account (credits to it in the year) already defers such invoices:
    # proposing them again would defer the income twice. Then one point lists them, for the accountant to check
    # against the client's schedule
    own_deferral = [t for t in tb_records if DEFERRED_INCOME_NAME.search(t.raw_account_name or "")
                    and (float(t.credit_amount or 0) >= MIN_PORTION or abs(float(t.net_amount or 0)) >= MIN_PORTION)]
    already: List[str] = []
    for l in gl_lines(str(engagement.id), tb_records, db):
        amount = round(l.credit - l.debit, 2)
        if (l.code is None or not chart.is_sales(l.code) or not l.when or l.when > year_end or amount < MIN_PORTION
                or "journal" in (l.source or "").lower()):
            continue
        period = service_period(l.description or "", l.when)
        # A date range only: a single month named on a sales invoice is usually its date ('dated January 2026'), not
        # a service period
        if period is None or period[2] != "date range in the description":
            continue
        start, end, basis = period
        if end <= year_end:
            continue
        days = (end - start).days + 1
        after = (end - max(start, year_end + timedelta(days=1))).days + 1
        deferred = round(amount * after / days, 2)
        if own_deferral:
            already.append(f"{l.when:%d/%m/%Y} {(l.description or '')[:90]}: £{deferred:,.2f} of £{amount:,.2f} after "
                           f"the year end")
            continue
        propose("U-DEF-001", "Deferred income: invoiced in advance",
                f"Deferred income: {(l.description or '')[:120]}", l.code, ACCRUALS, deferred,
                f"Sales invoice '{l.description}' of {l.when:%d/%m/%Y}, £{amount:,.2f}, covers {start:%d/%m/%Y} to "
                f"{end:%d/%m/%Y} ({basis}): {after} of its {days} days are after the year end, so £{deferred:,.2f} is "
                f"next year's income, a liability at the year end (deferred income). It is released to sales next "
                f"year.", chart.name(l.code))
    if already:
        names = ", ".join(t.raw_account_name for t in own_deferral[:3])
        findings.append(_point(
            engagement, "U-DEF-002", "Deferred income: invoiced in advance",
            f"Deferred income: {len(already)} invoice(s) run past the year end; the client defers income itself",
            f"These sales invoices cover periods running past the year end: {'; '.join(already[:12])}"
            f"{' and more' if len(already) > 12 else ''}. The client keeps its own deferred income account ({names}), "
            f"so no journal is proposed (it would defer the income twice). Check they are in the client's deferral "
            f"schedule; post only any that are missing (FRS 102 s23).", 0.0, "", names))

    if "ACCRUAL" not in entered and not worked(ACCRUALS):
        # 1. The accountancy fee: this year's accrual as last year's
        fee, source = _new_fee(engagement, db, tb_records)
        if fee:
            propose("U-ACC-004", "Accruals: accountancy fee",
                    f"Accrual: accountancy fee for the accounts to {year_end:%d/%m/%Y}", ACCOUNTANCY_FEES, ACCRUALS, fee,
                    f"This year's accounts and CT600 are prepared after the year end, so their fee is accrued: "
                    f"£{fee:,.2f} as last year ({source}). Change the amount to the fee agreed for this year's work "
                    f"if it differs.", chart.name(ACCOUNTANCY_FEES))
            replaces.add("U-ADJ-003")

        # 2. Power, water, phone: bills stating their own periods, the latest ending before the year end. The days
        # since are owed (FRS 102 s2). A point with the estimate, not a journal: the bill after the year end decides
        # the figure (a daily-rate estimate overshoots where use is uneven)
        from backend.app.services.sop.accruals import billed_to_before_year_end
        from backend.app.services.sop.common import gl_lines
        cost_sections = {"Distribution costs", "Employee costs", "Premises expenses", "General admin", "Cost of sales"}
        is_cost = lambda c: chart.section(c) in cost_sections
        arrears = billed_to_before_year_end(year_end, gl_lines(str(engagement.id), tb_records, db), is_cost)
        for b in arrears:
            if b.estimate < MIN_PORTION:
                continue
            findings.append(_point(
                engagement, "U-ACC-007", "Accruals: bill in arrears not yet received",
                f"{b.account[:60]}: bills cover to {b.covered_to:%d/%m/%Y}, about £{b.estimate:,.2f} owed for "
                f"{b.days} days to the year end",
                f"{b.account}'s bills state the periods they cover ({b.bills} bills this year); the latest covers to "
                f"{b.covered_to:%d/%m/%Y}, so the {b.days} days to {year_end:%d/%m/%Y} were used but not yet billed: "
                f"owed at the year end, about £{b.estimate:,.2f} at the bills' own cost (£{b.per_day:,.2f} a day). "
                f"Accrue the part of the next bill up to the year end (Dr {b.code} {chart.name(b.code)} / Cr "
                f"{ACCRUALS} {chart.name(ACCRUALS)}). Query to the client: Please send the first {b.account} bill "
                f"after {year_end:%d/%m/%Y}.", b.estimate, "", b.account))
        arrears_accounts = {b.account for b in arrears}

        # 3. A regular monthly cost missing in the final month: one average month accrued
        from backend.app.services.sop.accruals import accrual_review
        for a in accrual_review(engagement.id, year_end, tb_records, db):
            months_with_cost = sum(1 for m in a.monthly if m >= 0.005)
            if not a.final_missing or months_with_cost < FINAL_MONTH_MIN or a.code == ACCOUNTANCY_FEES:
                continue
            if a.account in arrears_accounts:
                continue                        # accrued above from the bills' own periods
            # A question, not a journal: an average month accrued this way is usually wrong; the bill after the year
            # end decides it
            if a.average < MIN_PORTION:
                continue
            findings.append(_point(
                engagement, "U-ACC-005", "Accruals: regular cost missing in the final month",
                f"{a.account}: no cost in {year_end:%B %Y} (about £{a.average:,.2f} a month): check for a bill",
                f"{a.account} has a cost in {months_with_cost} of {len(a.monthly)} months but none in {year_end:%B %Y}. "
                f"If a bill for {year_end:%B %Y} came after the year end, accrue it (Dr {a.code} {chart.name(a.code)} / "
                f"Cr {ACCRUALS} {chart.name(ACCRUALS)}); if the cost stopped or is paid differently, clear this point. "
                f"Query to the client: Were there any {a.account.lower()} bills for {year_end:%B %Y} received after the "
                f"year end?", a.average, "", a.account))
        # 4. A quarterly bill in arrears (power, water, phone) last billed a month or more before the year end: the
        # months since are owed. A question with the estimate, as the monthly one (the next bill
        # decides the figure)
        from backend.app.services.sop.accruals import quarterly_in_arrears
        for q in quarterly_in_arrears(year_end, gl_lines(str(engagement.id), tb_records, db), is_cost):
            if q.estimate < MIN_PORTION or q.account in arrears_accounts:
                continue
            listed = ", ".join(f"{d:%d/%m/%Y} £{a:,.2f}" for d, a in q.bills)
            findings.append(_point(
                engagement, "U-ACC-006", "Accruals: quarterly bill in arrears",
                f"{q.supplier[:60]}: billed quarterly, last bill {q.bills[-1][0]:%d/%m/%Y}: about £{q.estimate:,.2f} "
                f"owed for {q.months_since} month(s) to the year end",
                f"{q.supplier} ({q.account}) bills every quarter for the quarter just gone: {listed}. The "
                f"{q.months_since} month(s) from the last bill to {year_end:%d/%m/%Y} are not billed yet, about "
                f"£{q.estimate:,.2f} at the average bill. Accrue the bill that covers them when it comes (Dr {q.code} "
                f"{chart.name(q.code)} / Cr {ACCRUALS} {chart.name(ACCRUALS)}, the part up to the year end). Query to "
                f"the client: Please send the first {q.supplier} bill after {year_end:%d/%m/%Y}.",
                q.estimate, "", q.account))

    if "PREPAYMENT" not in entered and not worked(PREPAYMENTS):
        # 2. Prepayments: the part of a yearly payment that is for next year
        # Only a period the wording shows (dates, annual words, business rates) is journalled: a single payment taken
        # as a yearly plan is a guess (often a one-off purchase), left as the G2 question; small portions stay in the
        # cost
        from backend.app.services.sop.prepayments import MONTHLY_WORDS, PREPAY_MIN_PORTION, period_is_stated, prepayment_review
        found = [p for p in prepayment_review(engagement.id, year_end, tb_records, db)
                 if not p.guessed and p.prepaid >= PREPAY_MIN_PORTION]
        # The client's own history decides: a client that carried prepayments last year has them worked every year,
        # so this year's are journalled; one that never had any is asked
        brought = _brought_forward(engagement, tb_records, db)
        asked = []
        if found and not (abs(brought) >= MIN_PORTION or _had_prepayments(engagement, db) or last_journals
                          or "PREPAYMENT" in last_entered):
            # A prepayment is posted whatever last year had when LM is sure of its period: a date range
            # on the bill, the rates year, the one month the bill names. A period assumed from 'annual' wording is
            # not sure: the firm's setting decides those (not set = ask, 0 = post, an amount = post from it)
            from backend.app.services.review.adjustments import firm_new_client_prepayments
            post_from = firm_new_client_prepayments(db)
            # A monthly bill crossing the year end stays in the cost for such a client
            asked = [p for p in found if not (period_is_stated(p.basis) and not MONTHLY_WORDS.search(p.description))
                     and (post_from is None or p.prepaid < post_from)]
            found = [p for p in found if p not in asked]
        if asked:
            found_after = found
            found = asked
            listing = "; ".join(f"{p.description[:70]} paid {p.when:%d/%m/%Y}, £{p.prepaid:,.2f} of £{p.amount:,.2f} "
                                f"({p.months_after} of {p.total_months} months after the year end)" for p in found[:12])
            total = round(sum(p.prepaid for p in found), 2)
            findings.append(_point(
                engagement, "U-PRE-004", "Prepayments: paid in advance (no prepayments last year)",
                f"{len(found)} payment(s) partly for next year, £{total:,.2f}: prepay them, or leave them in the costs",
                f"These payments cover a period running past the year end: {listing}. The client had no prepayments "
                f"last year, so nothing is journalled: if the firm sets up prepayments for this client, post them "
                f"(Dr {PREPAYMENTS} {chart.name(PREPAYMENTS)} / Cr the cost); if not (small or regular costs), clear "
                f"this point.", total, "", chart.name(PREPAYMENTS)))
            found = found_after
        # (last year's lines, typed or read from last year's paper, are reversed item by item already: not again)
        if found and brought >= MIN_PORTION and "U-PRE-002" not in replaces and "PREPAYMENT" not in last_entered:
            # Last year's prepayment still sits on the account unchanged: released to its cost as this year's are
            # set up, or it is counted twice (the opening prepayment is reversed, then this year's set up)
            # The cost it is released to: the only one this year's prepayments are on, or, with several, the one whose
            # prepayment this year is the same as last year's (the same rent or plan again)
            per_cost: Dict[int, float] = {}
            for p in found:
                per_cost[p.code] = per_cost.get(p.code, 0.0) + p.prepaid
            same = [c for c, v in per_cost.items() if abs(v - brought) < 1.0]
            cost = next(iter(per_cost)) if len(per_cost) == 1 else (same[0] if len(same) == 1 else None)
            if cost is not None:
                propose("U-PRE-002", "Prepayments: last year's released",
                        "Release last year's prepayment", cost, PREPAYMENTS, brought,
                        f"Last year's prepayment of £{brought:,.2f} is still on {PREPAYMENTS} unchanged: its cost "
                        f"belongs to this year, so it is released to {cost} {chart.name(cost)} as this year's "
                        f"prepayments are set up (otherwise both stay on the account).", chart.name(cost))
                replaces.add("U-PRE-002")
        for p in found:
            propose("U-PRE-003", "Prepayments: paid in advance",
                    f"Prepayment: {p.description[:120]} ({p.months_after} of {p.total_months} months after the year end)",
                    PREPAYMENTS, p.code, p.prepaid,
                    f"'{p.description}' paid on {p.when:%d/%m/%Y} for {p.start:%d/%m/%Y} to {p.end:%d/%m/%Y} ({p.basis}): "
                    f"{p.months_after} of its {p.total_months} months are after the year end, so £{p.prepaid:,.2f} of "
                    f"£{p.amount:,.2f} is prepaid. It is released to the cost next year.", p.account,
                    figures=_prepaid_figures(p))
        found_codes = {p.code for p in found}
    else:
        found_codes = set()
    _same_again(engagement, tb_records, chart, db, entered, found_codes, propose)
    findings += unpaid_remuneration(engagement, tb_records, db)
    findings += _accrued_income_question(engagement, tb_records, db, worked)
    return findings, journals, replaces


def _prepaid_figures(p) -> Optional[str]:
    """A prepayment's figures: what was paid and when, the period it covers, the months after the year end, prepaid."""
    from backend.app.services.review import point_figures as pf
    return pf.table(["", ""], [pf.row(f"Paid on {p.when:%d/%m/%Y}", p.amount),
                               pf.row("Covers", f"{p.start:%d/%m/%Y} to {p.end:%d/%m/%Y}"),
                               pf.row("Months after the year end", f"{p.months_after} of {p.total_months}"),
                               pf.row("Prepaid at the year end", p.prepaid, strong=True)])


def _accrued_income_question(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session, worked
                             ) -> List[AuditFinding]:
    """U-ACI-002: last year had accrued income (work done, invoiced after the year end) and this year's books hold none
    of their own: a client question, since the same kind of work usually spans this year end too (FRS 102 s23, income
    recognised as the work is done). This year's figure comes from the client's answer or the post-year-end ledger."""
    from backend.app.services.review.last_year import prior_balances_by_code
    try:
        last = float(prior_balances_by_code(engagement, db).get(ACCRUED_INCOME, 0.0) or 0.0)
    except Exception:
        last = 0.0
    if last < 1 or worked(ACCRUED_INCOME):
        return []
    return [_point(engagement, "U-ACI-002", "Accrued income: this year's (client question)",
                   f"Last year's accounts had accrued income of £{last:,.2f}: any this year?",
                   f"Last year's accounts carried £{last:,.2f} of accrued income (work done before that year end and "
                   f"invoiced after it). The books hold none for this year end. Please tell us about any work done "
                   f"before {engagement.period_end_date:%d %B %Y} that was invoiced after it (send those invoices or "
                   f"the sales ledger after the year end); it is this year's income (FRS 102 s23).",
                   last, "", "Accrued income (4950)")]


def _same_again(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                entered: Set[str], found_codes: Set[int], propose) -> None:
    """U-ACC-008 / U-PRE-005: last year's accruals and prepayments read from last year's final WP are reversed item by
    item (review/adjustments.py); a cost that comes back this year (the same rent, insurance or interest) is owed or
    paid ahead again at this year end, so it is proposed again at last year's amount for the accountant to confirm
    (FRS 102 s2; reversed alone, the account would go to nil). Not for the accountancy fee (asked, never assumed), not
    when this year's lines are entered, and a prepayment the prepayments check found on
    the same cost is not proposed twice."""
    from backend.app.services.ingestion.last_year_adjustments import SOURCE
    from backend.app.services.review.adjustments import last_year_lines
    lines, source = last_year_lines(engagement, db)
    if source != "last year's final WP":
        return
    cost: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code is not None:
            cost[int(t.std_code)] = cost.get(int(t.std_code), 0.0) + float(t.net_amount or 0)
    # Interest builds up on a loan still owed whether or not any was charged this year: a loan owed at the year end
    # stands in for 'the cost comes back'
    from backend.app.services.review.loan_statements import loan_codes
    owed = sum(-float(t.net_amount or 0) for t in tb_records if t.std_code in loan_codes(tb_records))
    for l in lines:
        code, amount = int(l.cost_code), round(float(l.amount or 0), 2)
        name = (l.description or "").replace(SOURCE, "") or chart.name(code)
        again = cost.get(code, 0.0) >= MIN_PORTION or (
            chart.section(code) == "Interest payable and similar charges" and owed >= MIN_PORTION)
        if l.kind in entered or code == ACCOUNTANCY_FEES or amount < MIN_PORTION or not again:
            continue                     # no such cost this year: nothing owed or paid ahead again
        if l.kind == "ACCRUAL":
            propose("U-ACC-008", "Accruals: the same as last year", f"Accrual (as last year): {name}"[:255],
                    code, ACCRUALS, amount,
                    f"Last year's paper accrued £{amount:,.2f} for {name}, reversed this year, and {code} "
                    f"{chart.name(code)} has costs again this year, so the same is likely owed at this year end. "
                    f"Proposed at last year's amount: change it to this year's figure (the bill after the year end), or "
                    f"reject it if nothing is owed.", chart.name(code))
        elif code not in found_codes:
            propose("U-PRE-005", "Prepayments: the same as last year", f"Prepayment (as last year): {name}"[:255],
                    PREPAYMENTS, code, amount,
                    f"Last year's paper prepaid £{amount:,.2f} for {name}, reversed this year, and {code} "
                    f"{chart.name(code)} has costs again this year, so part of this year's payment is likely for next "
                    f"year again. Proposed at last year's amount: change it to this year's part (months after the "
                    f"year end), or reject it if nothing is paid ahead.", chart.name(code))


# Pay accounts (firm chart): wages, employer NI and pensions, bonuses, directors' pay (overheads, cost of sales,
# distribution)
REMUNERATION_CODES = set(range(3000, 3014)) | set(range(1500, 1514)) | set(range(2500, 2514))
ACCRUED_PAY_NAME = re.compile(r"bonus|holiday pay|accrued (wages|salar\w*|pay|remuneration)|"
                              r"(wages|salar\w*|pay|remuneration) accru", re.I)
UNPAID_PAY_MIN = 100.0


def unpaid_remuneration(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session) -> List[AuditFinding]:
    """U-ACC-007: pay accrued at the year end (a bonus, holiday pay, wages or directors' pay owed but not paid) is
    deductible this year only if paid within 9 months of the year end; otherwise in the year it is paid (CTA 2009
    s1288; a director's pay credited to the loan account counts as paid, EIM42310). A bonus is accrued only if the
    company was bound to pay it at the year end (FRS 102 s28)."""
    year_end = engagement.period_end_date
    if year_end is None:
        return []
    items: List[Tuple[str, float]] = []
    for a in db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == engagement.id,
                                                YearEndAdjustment.period == "THIS_YEAR",
                                                YearEndAdjustment.kind == "ACCRUAL"):
        if a.cost_code in REMUNERATION_CODES and float(a.amount or 0) >= UNPAID_PAY_MIN:
            items.append((a.description or "Pay accrued", float(a.amount)))
    for t in tb_records:
        owed = -float(t.net_amount or 0)
        if (owed >= UNPAID_PAY_MIN and ACCRUED_PAY_NAME.search(t.raw_account_name or "")
                and (t.std_code or 0) not in REMUNERATION_CODES):
            items.append((t.raw_account_name or "Accrued pay", owed))
    if not items:
        return []
    deadline = year_end
    for _ in range(9):                                   # 9 months after the year end, the same day of the month
        deadline = (deadline.replace(day=1) + timedelta(days=32)).replace(day=1)
    import calendar
    deadline = deadline.replace(day=min(year_end.day, calendar.monthrange(deadline.year, deadline.month)[1]))
    total = round(sum(a for _n, a in items), 2)
    listed = "; ".join(f"{n[:60]} £{a:,.2f}" for n, a in items[:8])
    return [_point(
        engagement, "U-ACC-007", "Accruals: pay accrued at the year end (9-month rule)",
        f"Pay accrued at the year end £{total:,.2f}: deductible this year only if paid by {deadline:%d/%m/%Y}",
        f"Accrued pay: {listed}. Pay charged in the accounts but not paid within 9 months of the year end (by "
        f"{deadline:%d/%m/%Y}) is not deductible this year: add it back in the corporation tax computation and deduct "
        f"it in the year it is paid (CTA 2009 s1288; a director's pay credited to the loan account counts as paid). A "
        f"bonus is accrued only if the company was bound to pay it at the year end (a contract, or a decision made "
        f"before it; FRS 102 s28). Query to the client: Was this pay (or bonus) paid by {deadline:%d/%m/%Y}, and was "
        f"the bonus agreed before the year end?", total, "", "Accruals")]
