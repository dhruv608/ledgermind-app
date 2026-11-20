"""Accruals and prepayments from the lines the accountant enters (models/yearend_adjustments.py): this year's are
booked, last year's are reversed cost by cost. Last year's lines come from last year's client in the app when it has
them (its this-year lines), else from what was typed for last year here.

A reversal larger than what is still brought forward on 5360 / 4900 (the client's software already reversed some)
is not proposed: a point says how much is left, so nothing is reversed twice."""

import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.models.yearend_adjustments import YearEndAdjustment
from backend.app.services.mapping.chart_lookup import ChartLookup

ACCRUALS, PREPAYMENTS = 5360, 4900
ACCOUNTANCY_FEES = 3301
MIN_AMOUNT = 1.0
KINDS, PERIODS = ("ACCRUAL", "PREPAYMENT"), ("THIS_YEAR", "LAST_YEAR")


def last_year_lines(engagement: ClientEngagement, db: Session) -> Tuple[List[YearEndAdjustment], str]:
    """Last year's accruals and prepayments to reverse, and where they came from: last year's client in the app
    ('last year in the app'), else the lines typed for last year on this client ('entered'), else none."""
    from backend.app.services.review.last_year import last_year_job
    try:
        last = last_year_job(engagement, db)
    except Exception:
        last = None
    if last is not None:
        rows = db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == last.id,
                                                  YearEndAdjustment.period == "THIS_YEAR").all()
        if rows:
            return rows, "last year in the app"
    rows = db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == engagement.id,
                                              YearEndAdjustment.period == "LAST_YEAR").all()
    from backend.app.services.ingestion.last_year_adjustments import SOURCE
    if rows and all((r.description or "").endswith(SOURCE) for r in rows):
        return rows, "last year's final WP"
    return rows, ("entered" if rows else "")


def _journal(engagement, counter, description, dr, cr, amount, chart, point) -> ProposedJournal:
    j = ProposedJournal(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{counter[0]:02d}",
                        description=description[:255], debit_code=dr, debit_name=chart.name(dr), credit_code=cr,
                        credit_name=chart.name(cr), amount=round(amount, 2), status="PROPOSED")
    counter[0] += 1
    j._point = point
    return j


def adjustment_journals(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                        counter: List[int], after: Dict[int, float]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    findings: List[AuditFinding] = []
    journals: List[ProposedJournal] = []
    this_year = db.query(YearEndAdjustment).filter(YearEndAdjustment.engagement_id == engagement.id,
                                                   YearEndAdjustment.period == "THIS_YEAR").all()
    last, source = last_year_lines(engagement, db)
    # A journal already approved for a line is not proposed again on the next run
    approved = {((j.description or "").strip(), round(float(j.amount or 0), 2)) for j in db.query(ProposedJournal).filter(
        ProposedJournal.engagement_id == engagement.id, ProposedJournal.status == "APPROVED")}

    # Last year's: reverse, cost by cost, only up to what is still brought forward on the control account
    for kind, control in (("ACCRUAL", ACCRUALS), ("PREPAYMENT", PREPAYMENTS)):
        lines = [l for l in last if l.kind == kind and float(l.amount or 0) >= MIN_AMOUNT]
        if not lines:
            continue
        total = round(sum(float(l.amount) for l in lines), 2)
        # What is still on the account: an accrual is a credit (owed), a prepayment a debit
        on_account = round(-after.get(control, 0.0) if kind == "ACCRUAL" else after.get(control, 0.0), 2)
        word = "accruals" if kind == "ACCRUAL" else "prepayments"
        if total > on_account + MIN_AMOUNT:
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ADJ-002",
                procedure_name=f"Last year's {word}", severity="MEDIUM", source_row_ref=chart.name(control)[:100],
                finding_title=f"Last year's {word} £{total:,.2f} are more than the £{max(on_account, 0):,.2f} still on "
                              f"{control}",
                finding_details=(f"Last year's {word} ({source}) total £{total:,.2f}, but {control} {chart.name(control)} "
                                 f"only holds £{max(on_account, 0):,.2f}: the client's books have probably reversed "
                                 f"some already. They are not reversed again automatically; check which are left and "
                                 f"adjust the lines."),
                quantified_amount=total, status="OPEN"))
            continue
        for l in lines:
            amount = round(float(l.amount), 2)
            if not l.cost_code:
                continue                 # no cost account found on last year's paper: not reversed
            if source == "last year's final WP" and kind == "ACCRUAL" and l.cost_code == ACCOUNTANCY_FEES:
                continue                 # the fee: released and accrued again nets to nil; asked below (U-ADJ-003)
            text = f"Reverse last year's {kind.lower()}: {l.description or chart.name(l.cost_code)}"
            if (text[:255].strip(), amount) in approved:
                continue
            dr, cr = (control, l.cost_code) if kind == "ACCRUAL" else (l.cost_code, control)
            entry = f"Dr {dr} {chart.name(dr)} / Cr {cr} {chart.name(cr)} £{amount:,.2f}"
            f = AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ADJ-001",
                procedure_name=f"Last year's {word} reversed", severity="LOW", source_row_ref=(l.description or "")[:100],
                finding_title=f"Last year's {kind.lower()} reversed: {l.description or chart.name(l.cost_code)} "
                              f"£{amount:,.2f}"[:255],
                finding_details=(f"Last year's {kind.lower()} for {chart.name(l.cost_code)} ({source}) is reversed this "
                                 f"year, so the cost is not counted twice. A journal is proposed (Journals tab): {entry}."),
                quantified_amount=amount, suggested_journal=entry, status="OPEN")
            findings.append(f)
            journals.append(_journal(engagement, counter, text, dr, cr, amount, chart, f))

    # This year's: book each one
    for l in this_year:
        amount = round(float(l.amount or 0), 2)
        text = f"{l.kind.title()}: {l.description or chart.name(l.cost_code)}"
        if amount < MIN_AMOUNT or (text[:255].strip(), amount) in approved:
            continue
        dr, cr = (l.cost_code, ACCRUALS) if l.kind == "ACCRUAL" else (PREPAYMENTS, l.cost_code)
        entry = f"Dr {dr} {chart.name(dr)} / Cr {cr} {chart.name(cr)} £{amount:,.2f}"
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ADJ-001",
            procedure_name="This year's accruals and prepayments", severity="LOW",
            source_row_ref=(l.description or "")[:100],
            finding_title=f"{l.kind.title()}: {l.description or chart.name(l.cost_code)} £{amount:,.2f}"[:255],
            finding_details=(f"{l.kind.title()} entered on the client's accruals and prepayments: "
                             f"{l.description or chart.name(l.cost_code)}. A journal is proposed (Journals tab): {entry}."),
            quantified_amount=amount, suggested_journal=entry, status="OPEN")
        findings.append(f)
        journals.append(_journal(engagement, counter, text, dr, cr, amount, chart, f))
    # The accountancy fee accrual (the most usual one in the working papers): a reminder while it is not entered
    if not any(l.kind == "ACCRUAL" and l.cost_code == ACCOUNTANCY_FEES for l in this_year):
        last_fee = round(sum(float(l.amount) for l in last if l.kind == "ACCRUAL" and l.cost_code == ACCOUNTANCY_FEES), 2)
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ADJ-003",
            procedure_name="Accruals: accountancy fee", severity="LOW", source_row_ref=chart.name(ACCOUNTANCY_FEES)[:100],
            finding_title="Accountancy fee accrual for this year's accounts not entered",
            finding_details=("This year's accounts and CT600 are prepared after the year end, so their fee is normally "
                             "accrued. Enter it as an accrual line (Accounts tab, accruals and prepayments: Accountancy "
                             f"fee, {ACCOUNTANCY_FEES})"
                             + (f"; last year's was £{last_fee:,.2f}" if last_fee >= MIN_AMOUNT else "")
                             + (". Last year's fee accrual (last year's final WP) is still on 5360: if this year's fee "
                                "is about the same, nothing needs posting (released and accrued again nets to nil); "
                                "if it differs, post the difference" if source == "last year's final WP"
                                and last_fee >= MIN_AMOUNT else "")
                             + ". It is reversed automatically next year. See A4 for the fees invoiced this year."),
            quantified_amount=last_fee, status="OPEN"))
    return findings, journals


# U-ADJ-004 Use of home: the director's home used as the office, paid back through the director's loan (Dr 3100 Rent /
# Cr 5400 Director's loan; £312 = HMRC's £6 a week flat rate, or the share of the bills the client gives)
USE_OF_HOME = 3100
DIRECTORS_LOAN = 5400
FLAT_RATE = 312.0
HOME_WORDS = re.compile(r"\b(?:use\s+of\s+(?:the\s+)?home|work(?:ing)?\s+from\s+home|wfh)\b", re.I)


def _home_in_journals(journals) -> float:
    """The use of home a set of approved journals posts (their P&L debits), or 0."""
    total = 0.0
    for j in journals:
        words = " ".join([j.description or ""] + [l.narrative or "" for l in (j.lines or [])])
        if not HOME_WORDS.search(words):
            continue
        if j.lines:
            total += sum(float(l.debit or 0) for l in j.lines if int(l.account_code) < 4000)
        elif int(j.debit_code) < 4000:
            total += float(j.amount or 0)
    return round(total, 2)


def _approved(engagement_id: str, db: Session):
    return db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement_id,
                                            ProposedJournal.status == "APPROVED").all()


def firm_new_client_prepayments(db: Session) -> Optional[float]:
    """Prepayments for a client that had none last year (Firm settings): None = ask the
    accountant (the default); 0 = post every one; an amount = post those of at least it and ask about the rest."""
    import json
    from backend.app.models.firm_settings import FirmSetting
    row = db.get(FirmSetting, "new_client_prepayments")
    try:
        amount = json.loads(row.value).get("amount") if row is not None else None
    except ValueError:
        amount = None
    return round(float(amount), 2) if amount is not None else None


def director_answers(engagement: ClientEngagement) -> Dict[str, Optional[float]]:
    """The accountant's answers on the director (the questions after upload, Client details): the yearly use of home
    and the salary taken outside the payroll. None: not answered; 0: answered no."""
    import json
    profile = getattr(engagement, "profile", None)
    try:
        people = (json.loads(profile.setup) if profile is not None and profile.setup else {}).get("people") or {}
    except ValueError:
        people = {}
    out: Dict[str, Optional[float]] = {}
    for key in ("use_of_home", "director_salary", "dividends_declared"):
        value = people.get(key)
        out[key] = round(float(value), 2) if isinstance(value, (int, float)) else None
    return out


# U-DIV-003 Dividends declared in the year that the books do not hold (the board minutes / vouchers): posted at the
# year end, Dr 8011 Interim dividend / Cr 5400 Director's loan, where the ledger has none. The accountant gives the
# total declared on the questions after upload; nothing is assumed
INTERIM_DIVIDEND = 8011
DECLARED = "Dividends declared in the year, credited to the director's loan"


def dividends_declared(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                       counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    answered = director_answers(engagement)["dividends_declared"]
    if answered is None or answered < MIN_AMOUNT:
        return [], []
    if any((j.description or "").startswith(DECLARED) for j in _approved(engagement.id, db)):
        return [], []                         # already approved: in the books now
    entry = (f"Dr {INTERIM_DIVIDEND} {chart.name(INTERIM_DIVIDEND)} / Cr {DIRECTORS_LOAN} "
             f"{chart.name(DIRECTORS_LOAN)} £{answered:,.2f}")
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-DIV-003",
        procedure_name="Dividends declared, not in the books", severity="LOW", source_row_ref="Dividends declared",
        finding_title=f"Dividends declared £{answered:,.2f} as answered, not in the books",
        finding_details=(f"The client details say dividends of £{answered:,.2f} were declared in the year and are not in "
                         f"the books; they are credited to the director's loan. A journal is proposed (Journals tab): "
                         f"{entry}. Keep the board minute and dividend vouchers on file; the reserves test (U-DIV-001, "
                         f"J3) runs on the dividends once approved."),
        quantified_amount=answered, suggested_journal=entry, status="OPEN")
    return [f], [_journal(engagement, counter, DECLARED, INTERIM_DIVIDEND, DIRECTORS_LOAN, answered, chart, f)]


def director_salary(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                    counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """The director's salary the accountant gave (taken outside the payroll, often £12,570 or £9,100 through the
    director's loan) against the directors' pay the books and approved journals hold:
    the rest is proposed, Dr directors' salaries / Cr director's loan."""
    from backend.app.services.review.payroll_journals import DIRECTOR_SALARY_CODES
    from backend.app.services.tax.ct_computation import final_balances
    salary = director_answers(engagement)["director_salary"]
    source = "as answered"
    if salary is None and not _payroll_this_year(engagement, db):
        # Not answered: last year's final working paper's salary through the director's loan, proposed as last year
        # for the accountant to confirm. Not when this year has a payroll (the director may have moved onto it)
        claims = last_year_claims(engagement, db, "SALARY")
        if claims:
            salary, source = round(sum(a for _w, a in claims), 2), "as last year"
    if not salary or not any(t.std_code == DIRECTORS_LOAN for t in tb_records):
        return [], []
    after = final_balances(engagement.id, tb_records, db)
    in_books = round(sum(after.get(c, 0.0) for c in DIRECTOR_SALARY_CODES), 2)
    short = round(salary - in_books, 2)
    if short < MIN_AMOUNT:
        return [], []
    cost = DIRECTOR_SALARY_CODES[0]
    entry = f"Dr {cost} {chart.name(cost)} / Cr {DIRECTORS_LOAN} {chart.name(DIRECTORS_LOAN)} £{short:,.2f}"
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ADJ-005",
        procedure_name="Director's salary", severity="MEDIUM", source_row_ref=f"Director's salary ({source})",
        finding_title=f"Director's salary £{salary:,.2f} {source}: £{short:,.2f} not in the books",
        finding_details=((f"The client details give the director's salary for the year as £{salary:,.2f}" if source == "as answered"
                          else f"Last year's final working paper recorded the director's salary of £{salary:,.2f} through "
                               f"the director's loan, and nothing is in the books this year; confirm this year's salary "
                               f"with the client (Client details)")
                         + f"; the directors' pay accounts hold £{in_books:,.2f}. The rest is proposed through the "
                           f"director's loan (Journals tab): {entry}. If it was paid through a payroll, record it as "
                           f"payroll instead."),
        quantified_amount=short, suggested_journal=entry, status="OPEN",
        figures=_salary_figures(salary, source, in_books, short))
    label = ("Director's salary as given in the client details" if source == "as answered"
             else "Director's salary recorded as per last year")
    return [f], [_journal(engagement, counter, label, cost, DIRECTORS_LOAN, short, chart, f)]


def _salary_figures(salary: float, source: str, in_books: float, short: float):
    """The director's salary point's figures: the salary (as answered, or last year's), the books, the rest."""
    from backend.app.services.review.point_figures import amounts
    return amounts([(f"Director's salary {source}", salary), ("In the directors' pay accounts", in_books),
                    ("Not in the books (proposed through the loan)", short, True)])


def last_year_claims(engagement: ClientEngagement, db: Session, kind: str) -> List[Tuple[str, float]]:
    """(narrative, amount) of last year's final WP's director's claims of this kind (models.LastYearClaim)."""
    from backend.app.models.yearend_adjustments import LastYearClaim
    return [(r.description or "", float(r.amount)) for r in db.query(LastYearClaim).filter(
        LastYearClaim.engagement_id == engagement.id, LastYearClaim.kind == kind) if float(r.amount or 0) >= MIN_AMOUNT]


def _payroll_this_year(engagement: ClientEngagement, db: Session) -> bool:
    """A payroll report is uploaded, for any year: the director may be on a payroll now, so last year's salary
    through the loan is not proposed (the payroll questions ask instead), even when the uploaded report
    is for the wrong year."""
    from backend.app.models.database import PayrollP32Record
    return db.query(PayrollP32Record).filter(PayrollP32Record.engagement_id == engagement.id).first() is not None


def use_of_home(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """Last year's use of home again this year (Dr 3100 / Cr 5400), for the accountant to confirm; with none last
    year but a director's loan, a reminder of the £312 flat rate. Nothing when this year's books or approved journals
    already hold it."""
    from backend.app.services.review.last_year import _from_files, _from_job, last_year_job
    from backend.app.services.review.payroll_journals import _lines
    if not any(t.std_code == DIRECTORS_LOAN for t in tb_records):
        return [], []
    # This year: an account, a ledger line or an approved journal
    if any(HOME_WORDS.search(t.raw_account_name or "") and abs(float(t.net_amount or 0)) >= MIN_AMOUNT for t in tb_records):
        return [], []
    if _home_in_journals(_approved(engagement.id, db)) >= MIN_AMOUNT:
        return [], []
    if any(code < 4000 and HOME_WORDS.search(f"{g.description or ''} {g.reference or ''}")
           for code, g in _lines(engagement, tb_records, chart, db)):
        return [], []

    # The accountant's answer comes first: no means nothing, an amount is journalled as given
    answered = director_answers(engagement)["use_of_home"]
    if answered is not None:
        if answered < MIN_AMOUNT:
            return [], []
        entry = f"Dr {USE_OF_HOME} {chart.name(USE_OF_HOME)} / Cr {DIRECTORS_LOAN} {chart.name(DIRECTORS_LOAN)} £{answered:,.2f}"
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ADJ-004",
            procedure_name="Use of home", severity="LOW", source_row_ref="Use of home (WFH)",
            finding_title=f"Use of home £{answered:,.2f} as answered, not yet recorded this year",
            finding_details=(f"The client details say the director works from home, £{answered:,.2f} for the year; nothing "
                             f"is in the books. A journal is proposed (Journals tab): {entry}."),
            quantified_amount=answered, suggested_journal=entry, status="OPEN")
        return [f], [_journal(engagement, counter, "Rent (WFH) as given in the client details", USE_OF_HOME,
                              DIRECTORS_LOAN, answered, chart, f)]

    # Last year: last year's client in the app (its approved journal or its accounts), else last year's TB
    last_amount, source = 0.0, ""
    try:
        last = last_year_job(engagement, db)
    except Exception:
        last = None
    if last is not None:
        last_amount = _home_in_journals(_approved(last.id, db))
        if last_amount < MIN_AMOUNT:
            last_amount = round(sum(l.amount for l in _from_job(last, db) if HOME_WORDS.search(l.name or "")), 2)
        source = "last year in the app"
    if last_amount < MIN_AMOUNT:
        # Last year's final working paper's own journal (its B2 tab: 'Being rent (WFH) recorded as per previous year')
        claims = last_year_claims(engagement, db, "HOME")
        if claims:
            last_amount, source = round(sum(a for _w, a in claims), 2), "last year's final WP: " + "; ".join(
                w[:60] for w, _a in claims)
    if last_amount < MIN_AMOUNT:
        try:
            _, lines = _from_files(engagement, db)
        except Exception:
            lines = []
        last_amount = round(sum(l.amount for l in lines if HOME_WORDS.search(l.name or "")), 2)
        source = "last year's TB"

    if last_amount >= MIN_AMOUNT:
        entry = f"Dr {USE_OF_HOME} {chart.name(USE_OF_HOME)} / Cr {DIRECTORS_LOAN} {chart.name(DIRECTORS_LOAN)} £{last_amount:,.2f}"
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ADJ-004",
            procedure_name="Use of home", severity="LOW", source_row_ref="Use of home (WFH)",
            finding_title=f"Use of home £{last_amount:,.2f} as last year, not yet recorded this year",
            finding_details=(f"Last year the director was paid back £{last_amount:,.2f} for using their home as the "
                             f"office ({source}); nothing is in the books this year. A journal is proposed as per last "
                             f"year (Journals tab): {entry}. Change the amount if the client gave this year's figures "
                             f"(the share of the household bills), or HMRC's flat rate of £6 a week (£{FLAT_RATE:,.0f} a "
                             f"year)."),
            quantified_amount=last_amount, suggested_journal=entry, status="OPEN")
        return [f], [_journal(engagement, counter, "Rent (WFH) recorded as per last year", USE_OF_HOME, DIRECTORS_LOAN,
                              last_amount, chart, f)]
    # Per director (£312 per director a year): the directors on the client setup
    count = _director_count(engagement)
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-ADJ-004",
        procedure_name="Use of home", severity="LOW", source_row_ref="Use of home (WFH)",
        finding_title="Use of home not claimed: ask whether the director works from home",
        finding_details=(f"No use of home in the books this year or last. If the director works from home, the company "
                         f"can pay them back through the director's loan: HMRC's flat rate of £6 a week (£{FLAT_RATE:,.0f} "
                         f"a year each, no bills needed"
                         + (f"; £{FLAT_RATE * count:,.0f} for the {count} directors on the client setup" if count > 1 else "")
                         + f") or the business share of the household bills. Journal: Dr "
                         f"{USE_OF_HOME} {chart.name(USE_OF_HOME)} / Cr {DIRECTORS_LOAN} {chart.name(DIRECTORS_LOAN)}. Add it from "
                         f"this point (or the client questions) when the director does; nothing is posted until then."),
        quantified_amount=FLAT_RATE * count, status="OPEN")], []


def _director_count(engagement: ClientEngagement) -> int:
    """The directors on the client setup (the Directors box), at least one."""
    import json
    profile = getattr(engagement, "profile", None)
    try:
        names = json.loads(profile.directors or "[]") if profile is not None and profile.directors else []
    except (TypeError, ValueError):
        names = []
    return max(len([n for n in names if str(n).strip()]), 1)
