"""
Loans and hire purchase review points (the loans check and the loan schedule's year-end journals):

  U-LOAN-001  Loan balances brought forward in the ledger but not in the TB: the TB holds this year's movement only
              and the ledger's opening balances could not be taken in (they do not add up). The loans tab (G4) shows
              each loan from them; the books need last year's balances posted.
  U-LOAN-002  Books against the agreement's schedule (loans register): owed less than the schedule -> interest / HP
              charges not charged to the loan (journal Dr interest / Cr the loan); owed more -> a payment or opening
              balance to find; HP booked with its future interest (gross) -> the deferred charges to take out.
  U-LOAN-003  The split due within / after one year in the books against the schedule: a reclassification journal.
"""

from typing import List, Tuple

from sqlalchemy.orm import Session

from backend.app.services.review.point_figures import amounts as _amounts
from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord

# Interest code by the kind of finance (firm chart)
INTEREST_CODE = {**dict.fromkeys((5000, 5001, 5002), 3641), **dict.fromkeys((5010, 5011, 5012), 3642),
                 **dict.fromkeys((5100, 5500), 3615)}
OTHER_INTEREST = 3618
# The within / after one year twin of each code
TWIN = {5000: 5001, 5001: 5000, 5010: 5011, 5011: 5010, 5100: 5500, 5500: 5100, 5110: 5510, 5510: 5110,
        5120: 5520, 5520: 5120, **dict.fromkeys(range(5350, 5360), 5510)}
MIN_AMOUNT = 1.0


def loan_openings_missing(engagement: ClientEngagement, db: Session) -> List[AuditFinding]:
    from backend.app.models.gl_openings import GLOpeningBalance
    from backend.app.services.workbook.balance_tabs import DEBTOR_NAME, GL_LOAN_NAME, NOT_A_LOAN
    # Only an account the TB does not hold, and whose balance no TB loan already opens with (the same loan renamed,
    # e.g. a ledger 'Hire Purchase >1 year' that is the opening of a named HP account on 5001)
    from backend.app.models.database import TBRecord
    from backend.app.services.workbook.balance_tabs import LOANS_AFTER_1_YEAR, LOANS_WITHIN_1_YEAR
    tb_openings = [float(t.opening_amount or 0) for t in db.query(TBRecord).filter(
        TBRecord.engagement_id == engagement.id, TBRecord.std_code.in_(LOANS_WITHIN_1_YEAR + LOANS_AFTER_1_YEAR))
        if abs(float(t.opening_amount or 0)) >= 0.005]
    loans = [o for o in db.query(GLOpeningBalance).filter(GLOpeningBalance.engagement_id == engagement.id)
             if float(o.amount) < -0.005 and GL_LOAN_NAME.search(o.account_name)
             and not NOT_A_LOAN.search(o.account_name) and not DEBTOR_NAME.search(o.account_name)
             and not o.in_tb and not any(abs(float(o.amount) - x) < 1.0 for x in tb_openings)]
    if not loans:
        return []
    total = round(-sum(float(o.amount) for o in loans), 2)
    listing = "; ".join(f"{o.account_name} £{-float(o.amount):,.2f}" for o in loans)
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-001",
        procedure_name="Loans: balances brought forward", severity="HIGH" if total >= 1000 else "MEDIUM",
        source_row_ref="Loans and HP (G4)",
        finding_title=f"Loan balances brought forward £{total:,.2f} are in the ledger but not in the TB",
        finding_details=(f"The ledger opens these loans with balances the trial balance does not hold (it holds this "
                         f"year's movement only): {listing}. The loans tab (G4) shows each loan from them. Post last "
                         f"year's closing balances (check them to last year's accounts or the lender statements), or "
                         f"upload last year's TB."),
        quantified_amount=total, status="OPEN",
        figures=_amounts([(o.account_name, -float(o.amount)) for o in loans] + [("Not in the TB", total, True)]))]


def loan_openings_by_code(engagement: ClientEngagement, tb_records: List[TBRecord]) -> List[AuditFinding]:
    """U-LOAN-007: last year's TB keeps a loan balance by code only ('Brought forward: Hire purchase ...') while the
    code holds several lenders this year, so whose balance it is cannot be told (review/last_year_openings
    .lender_unknown) and last year's working paper does not share it all out. Each lender's balance at last year's end
    is asked for: without it the lenders' balances and their split within / after one year cannot be checked (FRS 102
    s4, P-004; the balance carried forward agrees to the lender statement). The total is right: only its lenders are
    not known."""
    from backend.app.services.loans.agreements import last_year_loans, name_words
    from backend.app.services.workbook.balance_tabs.common import (
        BROUGHT_FORWARD, LOANS_AFTER_1_YEAR, LOANS_WITHIN_1_YEAR)
    from backend.app.services.workbook.balance_tabs.loans import LOAN_KIND
    codes = LOANS_WITHIN_1_YEAR + LOANS_AFTER_1_YEAR
    kept = [t for t in tb_records if t.std_code in codes and BROUGHT_FORWARD.search(t.raw_account_name or "")
            and abs(float(t.opening_amount or 0.0)) >= MIN_AMOUNT]
    if not kept:
        return []
    kind = lambda code: LOAN_KIND.get(code, str(code))
    kinds = {kind(t.std_code) for t in kept}
    lenders = [t for t in tb_records if t.std_code in codes and kind(t.std_code) in kinds
               and not BROUGHT_FORWARD.search(t.raw_account_name or "")]
    total = round(-sum(float(t.opening_amount or 0.0) for t in kept), 2)
    # Last year's working paper's balances for this year's lenders (matched by name) share it out on the loans tab
    shared = sum(v for n, v in last_year_loans(engagement).items()
                 if any(name_words(n) & name_words(t.raw_account_name) for t in lenders))
    left = round(total - shared, 2)
    if left < MIN_AMOUNT or len(lenders) < 2:
        return []
    listing = "; ".join(f"{t.raw_account_name}" for t in lenders[:12])
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-007",
        procedure_name="Loans: last year's balance per lender", severity="MEDIUM",
        source_row_ref="Loans and HP (G4)",
        finding_title=f"Last year's loan balances £{total:,.2f} are kept by code, not per lender"[:255],
        finding_details=(f"Last year's TB holds £{total:,.2f} on the loan codes ("
                         + "; ".join(f"{t.raw_account_name} £{-float(t.opening_amount or 0):,.2f}" for t in kept)
                         + f") but this year's ledger has {len(lenders)} lenders on them: {listing}. "
                         + (f"Last year's working paper gives £{shared:,.2f} of it by lender; " if shared >= MIN_AMOUNT
                            else "")
                         + f"£{left:,.2f} is not tied to a lender, so it is shown on the loans lead (G4) as brought "
                           f"forward. Ask the client for each lender's statement at last year's end (or last year's "
                           f"loan schedule) and move each balance to its lender on G4: then each loan's balance and "
                           f"its split within / after one year can be checked."),
        quantified_amount=left, status="OPEN",
        figures=_amounts([(f"Last year: {t.raw_account_name}", -float(t.opening_amount or 0)) for t in kept]
                         + ([("Given by lender in last year's working paper", shared)] if shared >= MIN_AMOUNT else [])
                         + [("Not tied to a lender", left, True)]))]


def _journal(engagement: ClientEngagement, counter: List[int], description: str, dr: int, cr: int, amount: float,
             chart, point: AuditFinding) -> ProposedJournal:
    j = ProposedJournal(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{counter[0]:02d}",
                        description=description[:255], debit_code=dr, debit_name=chart.name(dr), credit_code=cr,
                        credit_name=chart.name(cr), amount=round(amount, 2), status="PROPOSED")
    counter[0] += 1
    j._point = point
    return j


def loan_schedule_points(engagement: ClientEngagement, tb_records: List[TBRecord], chart, db: Session,
                         counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """U-LOAN-002 / 003 for each agreement on the loans register found in the ledger."""
    from backend.app.services.loans.agreements import agreement_schedules, link
    from backend.app.services.workbook.balance_tabs import (
        CREDITOR_LOAN_CODES, LOAN_NAME, LOANS_AFTER_1_YEAR, LOANS_WITHIN_1_YEAR, NOT_A_LOAN)
    schedules = agreement_schedules(engagement, db)
    if not schedules:
        return [], []
    accounts = [t for t in tb_records if t.std_code in LOANS_WITHIN_1_YEAR + LOANS_AFTER_1_YEAR
                or (t.std_code in CREDITOR_LOAN_CODES and LOAN_NAME.search(t.raw_account_name or "")
                    and not NOT_A_LOAN.search(t.raw_account_name or ""))]
    findings, journals = [], []
    within_codes = set(LOANS_WITHIN_1_YEAR) | set(CREDITOR_LOAN_CODES)
    for i, j in link(schedules, [t.raw_account_name for t in accounts]).items():
        agreement, sched = schedules[i]
        t = accounts[j]
        code = int(t.std_code)
        books = round(-float(t.net_amount or 0.0), 2)
        diff = round(books - sched.balance_ye, 2)
        where = f"{t.raw_account_name} ({code})"
        source = (f"The loans register's agreement {agreement.lender} ({agreement.method}, payment "
                  f"£{sched.payment:,.2f}, {sched.made_ye} of {agreement.payments} paid by the year end) leaves "
                  f"£{sched.balance_ye:,.2f} owed at the year end; the books show £{books:,.2f} on {where}")
        if diff <= -MIN_AMOUNT and -diff > sched.interest_in_year + MIN_AMOUNT:
            # Short by more than the year's interest: last year's balance or a drawdown is missing, not interest
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-002",
                procedure_name="Loans: books against the agreement", severity="HIGH" if -diff >= 1000 else "MEDIUM",
                source_row_ref=where[:100],
                finding_title=f"{agreement.lender}: books owe £{-diff:,.2f} less than the agreement"[:255],
                finding_details=(source + f". That is more than the year's interest (£{sched.interest_in_year:,.2f}): "
                                 f"last year's balance or the drawdown is probably missing from this account (see the "
                                 f"loans tab, G4). Post it, then the interest."),
                quantified_amount=-diff, status="OPEN"))
            continue
        if diff <= -MIN_AMOUNT:
            interest_code = INTEREST_CODE.get(code, OTHER_INTEREST)
            entry = (f"Dr {interest_code} {chart.name(interest_code)} (£{-diff:,.2f}) / "
                     f"Cr {code} {chart.name(code)} (£{-diff:,.2f})")
            f = AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-002",
                procedure_name="Loans: books against the agreement", severity="HIGH" if -diff >= 1000 else "MEDIUM",
                source_row_ref=where[:100],
                finding_title=f"{agreement.lender}: interest / charges £{-diff:,.2f} not charged to the loan"[:255],
                finding_details=(source + f". The books owe £{-diff:,.2f} less: interest / finance charges for the "
                                 f"year (£{sched.interest_in_year:,.2f} per the schedule) not charged to the loan. A "
                                 f"journal is proposed (Journals tab): {entry}. If the books are right, check the "
                                 f"agreement's terms on the loans register."),
                quantified_amount=-diff, suggested_journal=entry, status="OPEN")
            findings.append(f)
            journals.append(_journal(engagement, counter, f"Interest / charges on {agreement.lender} (schedule)",
                                     interest_code, code, -diff, chart, f))
            books = sched.balance_ye
        elif diff >= MIN_AMOUNT:
            gross = sched.future_charges >= MIN_AMOUNT and abs(diff - sched.future_charges) < MIN_AMOUNT
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-002",
                procedure_name="Loans: books against the agreement", severity="MEDIUM", source_row_ref=where[:100],
                finding_title=(f"{agreement.lender}: HP booked with its future interest (£{diff:,.2f})" if gross else
                               f"{agreement.lender}: books owe £{diff:,.2f} more than the agreement")[:255],
                finding_details=(source + (
                    f". The difference equals the future finance charges (£{sched.future_charges:,.2f}): the HP was "
                    f"posted gross. Take the deferred interest out of the liability (Dr deferred HP interest 5005 / "
                    f"Cr {code})." if gross else
                    ". Find the missing payment or opening balance, or check the agreement's terms on the loans "
                    "register.")),
                quantified_amount=diff, status="OPEN"))
            continue                    # the split is left until the balance agrees
        # The split: the books hold the balance on a within or an after one year code
        twin = TWIN.get(code)
        if twin is None:
            continue
        books_within = books if code in within_codes else 0.0
        move = round(min(sched.within_1_year, books) - books_within, 2)
        if abs(move) < MIN_AMOUNT:
            continue
        within_code, after_code = (code, twin) if code in within_codes else (twin, code)
        dr, cr = (after_code, within_code) if move > 0 else (within_code, after_code)
        entry = f"Dr {dr} {chart.name(dr)} (£{abs(move):,.2f}) / Cr {cr} {chart.name(cr)} (£{abs(move):,.2f})"
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-003",
            procedure_name="Loans: due within / after one year", severity="MEDIUM", source_row_ref=where[:100],
            finding_title=f"{agreement.lender}: £{abs(move):,.2f} to move {'into' if move > 0 else 'out of'} "
                          f"due within one year"[:255],
            finding_details=(f"The schedule ({agreement.lender}) has £{sched.within_1_year:,.2f} of capital due in the "
                             f"next twelve months and £{sched.one_to_five + sched.after_five:,.2f} after; the books "
                             f"hold £{books_within:,.2f} within one year on {where}. A reclassification journal is "
                             f"proposed (Journals tab): {entry}."),
            quantified_amount=abs(move), suggested_journal=entry, status="OPEN")
        findings.append(f)
        journals.append(_journal(engagement, counter, f"{agreement.lender}: due within / after one year", dr, cr,
                                 abs(move), chart, f))
    return findings, journals


LEASES_AFTER = tuple(range(5750, 5760))       # other creditors after one year: a lease liability on some clients
RATE_MIN_PAYMENTS = 3


def _rate_lines(engagement, tb_records, db):
    """{(account, code): ledger lines as the loans tab reads them} for the loan, HP, lease and other-creditors-after-
    one-year codes."""
    from collections import defaultdict
    from backend.app.services.sop.common import gl_lines
    out = defaultdict(list)
    for g in gl_lines(engagement.id, tb_records, db):
        if g.code in TWIN or g.code in LEASES_AFTER:
            out[(g.account, g.code)].append((g.when.strftime("%d/%m/%Y"), 0, 0, g.account, 0, g.description, 0,
                                             g.debit or None, g.credit or None))
    return out


def rate_splits(engagement: ClientEngagement, tb_records: List[TBRecord], chart, db: Session,
                counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """The capital due in the next twelve months of each loan, HP or lease whose ledger shows the lender's interest
    each month: the rate that interest shows on the falling balance (FRS 102 20.62; the loans tab's method).
      U-LOAN-003  a within / after one year code pair where every loan's split is worked out so: the books' split
                  reclassified to it by journal (FRS 102 s4, P-004). Any loan on the pair with no rate (an estimate,
                  or a balance whose lender is not known) leaves the pair as the books have it: the loans tab
                  suggests, nothing is posted.
      U-LOAN-009  a lease or loan on the other creditors after one year codes (5750-5759, the firm's own slots): the
                  part due within one year named, for the accountant to move to the client's within-one-year slot.
    Not with a loans register: its schedules decide (loan_schedule_points)."""
    from collections import Counter
    from backend.app.services.loans.agreements import agreement_schedules
    from backend.app.services.mapping.chart_lookup import account_name_keys
    from backend.app.services.workbook.balance_tabs.loans import _capital_in_twelve, _monthly_rate
    if db is not None and agreement_schedules(engagement, db):
        return [], []
    ye = engagement.period_end_date
    if ye is None:
        return [], []
    since = engagement.prior_period_end_date or ye.replace(year=ye.year - 1)
    by_key = {k: t for t in tb_records for k in account_name_keys(t.raw_account_name or "")}
    splits = {}                                   # (account, code) -> (owed, within) ; within None: no rate
    for (account, code), lines in _rate_lines(engagement, tb_records, db).items():
        t = next((by_key[k] for k in account_name_keys(account) if k in by_key), None)
        if t is None:
            continue
        owed = round(-float(t.net_amount or 0.0), 2)
        paid = [round(l[7], 2) for l in lines if l[7]]
        payment, times = Counter(paid).most_common(1)[0] if paid else (0.0, 0)
        rate = _monthly_rate(lines, payment, since) if times >= RATE_MIN_PAYMENTS else None
        splits[(account, code)] = (owed, _capital_in_twelve(owed, payment, rate) if rate and owed > 0 else None)
    findings, journals, done = [], [], set()
    # U-LOAN-003 on each code pair
    for code, twin in TWIN.items():
        if code in done or twin not in TWIN or code not in TWIN.values():
            continue
        done |= {code, twin}
        within_code = code if code in (5000, 5010, 5100, 5110, 5120) or code in range(5350, 5360) else twin
        after_code = twin if within_code == code else code
        on_pair = [t for t in tb_records if t.std_code in (within_code, after_code)
                   and abs(float(t.net_amount or 0.0)) >= MIN_AMOUNT]
        if not on_pair:
            continue
        known = {}
        for t in on_pair:
            hit = next((v for (a, c), v in splits.items() if c == t.std_code
                        and set(account_name_keys(a)) & set(account_name_keys(t.raw_account_name or ""))), None)
            if hit is None or hit[1] is None:
                known = None
                break
            known[t.raw_account_name] = hit[1]
        if not known:
            continue
        target = round(sum(known.values()), 2)
        books_within = round(-sum(float(t.net_amount or 0.0) for t in on_pair if t.std_code == within_code), 2)
        move = round(target - books_within, 2)
        if abs(move) < MIN_AMOUNT:
            continue
        dr, cr = (after_code, within_code) if move > 0 else (within_code, after_code)
        entry = f"Dr {dr} {chart.name(dr)} (£{abs(move):,.2f}) / Cr {cr} {chart.name(cr)} (£{abs(move):,.2f})"
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-003",
            procedure_name="Loans: due within / after one year", severity="MEDIUM",
            source_row_ref=f"{within_code} / {after_code}",
            finding_title=f"£{abs(move):,.2f} to move {'into' if move > 0 else 'out of'} due within one year "
                          f"({within_code} / {after_code})"[:255],
            finding_details=("Capital due in the next twelve months, from the rate each loan's monthly interest shows "
                             "(loans tab, G4): " + "; ".join(f"{n} £{v:,.2f}" for n, v in known.items())
                             + f": £{target:,.2f} in all; the books hold £{books_within:,.2f} within one year. A "
                               f"reclassification journal is proposed (Journals tab): {entry}."),
            quantified_amount=abs(move), suggested_journal=entry, status="OPEN")
        findings.append(f)
        journals.append(_journal(engagement, counter, f"Loans due within / after one year ({within_code} / {after_code})",
                                 dr, cr, abs(move), chart, f))
    # U-LOAN-009 on the other creditors after one year slots
    leases = {a: v for (a, c), v in splits.items() if c in LEASES_AFTER and v[1] is not None and v[1] >= MIN_AMOUNT}
    if leases:
        total = round(sum(v[1] for v in leases.values()), 2)
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-LOAN-009",
            procedure_name="Leases: due within / after one year", severity="MEDIUM",
            source_row_ref="Other creditors after one year",
            finding_title=f"£{total:,.2f} of the leases on creditors after one year falls due within one year"[:255],
            finding_details=("Each lease's capital due in the next twelve months, from the rate its monthly interest "
                             "shows (FRS 102 20.62): " + "; ".join(f"{a} £{v[1]:,.2f} of £{v[0]:,.2f}"
                                                                    for a, v in sorted(leases.items()))
                             + f". Creditors are split by when they fall due (FRS 102 s4): move £{total:,.2f} to the "
                               f"client's other creditors within one year line by journal."),
            quantified_amount=total, status="OPEN"))
    return findings, journals
