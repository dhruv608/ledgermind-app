"""U-PAY-004 / U-PAY-007 directors' pay in the staff accounts, and per the payroll file."""

from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from typing import Dict, Iterable, List, Optional, Tuple
from sqlalchemy.orm import Session
import json

from backend.app.services.review.payroll_journals.common import (
    DIRECTOR_PAY_NAME, DIRECTOR_PENSION_CODES, DIRECTOR_SALARY_CODES, MIN_AMOUNT, PENSION_TO_DIRECTORS,
    SALARY_TO_DIRECTORS, _entry, _journal, _lines, _names_person, _report)


def director_pay(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                 chart: ChartLookup, db: Session, counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.tax.ct_computation import final_balances
    directors = [d for d in (json.loads(profile.directors or "[]") if profile else []) if d]
    if not directors:
        return [], []
    tb_bal: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code is not None:
            tb_bal[t.std_code] = tb_bal.get(t.std_code, 0.0) + float(t.net_amount or 0)
    after = final_balances(engagement.id, tb_records, db)
    moved_already = lambda code: max(after.get(code, 0.0) - tb_bal.get(code, 0.0), 0.0)   # by approved journals

    found: Dict[Tuple[int, int], Dict[str, float]] = {}      # (staff code, directors' code) -> {director: amount}
    for code, g in _lines(engagement, tb_records, chart, db):
        target = SALARY_TO_DIRECTORS.get(code) or PENSION_TO_DIRECTORS.get(code)
        if target is None:
            continue
        who = next((d for d in directors if _names_person(g.description or "", d)), None)
        if who:
            found.setdefault((code, target), {}).setdefault(who, 0.0)
            found[(code, target)][who] += float(g.net_amount or 0)

    # Directors' pension goes where it went last year for this client (the accountant keeps clients consistent)
    from backend.app.services.mapping.mapping_service import MappingService
    used_last_year = {c for c, _ in MappingService.last_year_codes(engagement.id, db).values()}
    pension_to = dict(PENSION_TO_DIRECTORS)
    if 3013 in used_last_year and 3012 not in used_last_year:
        pension_to[3002] = 3013
    if 1453 in used_last_year and 1452 not in used_last_year:
        pension_to[1502] = 1453
    found = {(code, pension_to.get(code, target)): people for (code, target), people in found.items()}

    findings, journals = [], []
    for (code, target), people in found.items():
        total = round(sum(people.values()), 2)
        already = moved_already(target) if target not in DIRECTOR_PENSION_CODES else sum(moved_already(c) for c in DIRECTOR_PENSION_CODES)
        amount = round(total - already, 2)
        if amount < MIN_AMOUNT:
            continue
        kind = "salary" if code in SALARY_TO_DIRECTORS else "pension"
        listing = "; ".join(f"{d} £{v:,.2f}" for d, v in people.items())
        entry = _entry(target, code, amount, chart)
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-004",
            procedure_name="Payroll: directors' pay in the staff accounts", severity="MEDIUM",
            source_row_ref=f"{chart.name(code)} ({code})"[:100],
            finding_title=f"Directors' {kind} £{amount:,.2f} is in {chart.name(code)}",
            finding_details=(f"Ledger lines on {code} {chart.name(code)} name directors: {listing}"
                             + (f" (£{already:,.2f} already moved by an approved journal)" if already >= MIN_AMOUNT else "")
                             + f". Directors' pay is shown on its own in the accounts. A journal is proposed (Journals tab): {entry}."),
            quantified_amount=amount, suggested_journal=entry, status="OPEN")
        findings.append(f)
        journals.append(_journal(engagement, counter, f"Directors' {kind} moved from {chart.name(code)}", target, code,
                                 amount, chart, f))

    # Employer pension paid outside the payroll while the payroll report shows none for the directors
    report = _report(engagement, db)
    if report:
        report_pension = sum(float(p.pension_employer or 0) for p in report)
        director_report_pension = sum(float(p.pension_employer or 0) for p in report
                                      if any(_names_person(p.employee_name or "", d) for d in directors))
        for code, target in pension_to.items():
            if (code, target) in found:
                continue
            books = after.get(code, 0.0)
            outside = round(books - report_pension - sum(moved_already(c) for c in DIRECTOR_PENSION_CODES), 2)
            if books < MIN_AMOUNT or outside < MIN_AMOUNT or director_report_pension >= MIN_AMOUNT:
                continue
            entry = _entry(target, code, outside, chart)
            f = AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-004",
                procedure_name="Payroll: directors' pay in the staff accounts", severity="MEDIUM",
                source_row_ref=f"{chart.name(code)} ({code})"[:100],
                finding_title=f"Pension £{outside:,.2f} paid outside the payroll: usually the directors' own",
                finding_details=(f"{code} {chart.name(code)} holds £{books:,.2f}; the payroll report shows employer pension "
                                 f"of £{report_pension:,.2f} and none for the directors, so £{outside:,.2f} was paid "
                                 f"directly. That is usually the directors' own pension. If so, a journal is proposed "
                                 f"(Journals tab): {entry}. Client question: please confirm whose pension this is."),
                quantified_amount=outside, suggested_journal=entry, status="OPEN")
            findings.append(f)
            journals.append(_journal(engagement, counter, "Directors' pension paid outside the payroll", target, code,
                                     outside, chart, f))
    return findings, journals


def _directors_last_year(engagement: ClientEngagement, after: Dict[int, float], this_year: float, chart: ChartLookup,
                         db: Session) -> List[AuditFinding]:
    """No directors' pay in the payroll file or the books this year, but last year's TB had some (likely all on
    wages this year): a question, as the amount is not known."""
    from backend.app.services.review.last_year import _from_files
    if this_year >= MIN_AMOUNT:
        return []
    staff = sum(after.get(c, 0.0) for c in SALARY_TO_DIRECTORS)
    try:
        _, lines = _from_files(engagement, db)
    except Exception:
        return []
    last = round(sum(l.amount for l in lines if (l.code in DIRECTOR_SALARY_CODES if l.code is not None
                                                 else bool(DIRECTOR_PAY_NAME.search(l.name or "")))), 2)
    if last < MIN_AMOUNT or staff < MIN_AMOUNT:
        return []
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-007",
        procedure_name="Payroll: directors' pay in the staff accounts", severity="MEDIUM",
        source_row_ref="Directors' pay: none this year",
        finding_title=f"No directors' pay this year; last year £{last:,.2f}",
        finding_details=(f"Last year's TB shows directors' pay of £{last:,.2f}; this year the directors' accounts are nil "
                         f"and staff wages hold £{staff:,.2f}. If the directors were paid through the payroll, their pay "
                         f"is in staff wages: move it to directors' salaries (3010). The payroll file does not say "
                         f"which pay is the directors': client question, or upload a payroll report naming them."),
        quantified_amount=last, status="OPEN")]


def directors_per_payroll(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                          counter: List[int], proposed: Iterable[ProposedJournal] = ()
                          ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """The payroll file gives the directors' pay for the year (a 'Director Salary' line, a block per director, a
    director column) and the books hold less of it in the directors' accounts: the rest is in the staff wages (often
    everything on 3000). Proposes moving it, net of what U-PAY-004 or approved
    journals already move."""
    from backend.app.models.director_pay import PayrollDirectorPay
    from backend.app.services.tax.ct_computation import final_balances
    dp = db.query(PayrollDirectorPay).filter(PayrollDirectorPay.engagement_id == engagement.id).first()
    after = final_balances(engagement.id, tb_records, db)
    in_books = sum(after.get(c, 0.0) for c in DIRECTOR_SALARY_CODES)
    moving = sum(sum(float(l.debit or 0) for l in j.lines if l.account_code in DIRECTOR_SALARY_CODES) if j.lines
                 else float(j.amount or 0) if j.debit_code in DIRECTOR_SALARY_CODES else 0.0 for j in proposed)
    if dp is None or float(dp.gross_pay or 0) < MIN_AMOUNT:
        return _directors_last_year(engagement, after, in_books + moving, chart, db), []
    per_payroll = round(float(dp.gross_pay), 2)
    short = round(per_payroll - in_books - moving, 2)
    people = json.loads(dp.people or "{}")
    named = "; ".join(f"{d} £{v:,.2f}" for d, v in people.items())
    source = (f"The payroll file ({dp.filename}) gives directors' pay of £{per_payroll:,.2f}"
              + (f" ({named})" if named else "") + f", from its {dp.how}. ")
    extra = []
    if dp.employer_nic:
        extra.append(f"employer NI £{float(dp.employer_nic):,.2f}")
    if dp.pension_employer:
        extra.append(f"employer pension £{float(dp.pension_employer):,.2f}")
    extras = f" The file also gives the directors' {' and '.join(extra)}: check them on the directors' lines." if extra else ""
    ref = "Directors' pay per the payroll file"
    # The point's figures (every outcome below): the payroll's directors' pay against the directors' accounts
    from backend.app.services.review.point_figures import amounts
    figures = amounts([(f"Directors' pay per the payroll ({d})", v) for d, v in people.items()]
                      + [("Directors' pay per the payroll", per_payroll), ("In the directors' accounts", in_books)]
                      + ([("Moved by another journal", moving)] if moving >= MIN_AMOUNT else [])
                      + [("Difference", short, True)])
    if short >= MIN_AMOUNT:
        # From the staff account holding the wages (employee costs, or cost of sales)
        staff = max(SALARY_TO_DIRECTORS, key=lambda c: after.get(c, 0.0))
        spare = after.get(staff, 0.0)
        # Staff wages already equal to the staff pay per the payroll (its total less the directors'): the books are
        # split already and the difference is elsewhere
        payroll_gross = sum(float(p.gross_pay or 0) for p in _report(engagement, db))
        staff_books = sum(after.get(c, 0.0) for c in SALARY_TO_DIRECTORS)
        if payroll_gross > per_payroll and abs(staff_books - (payroll_gross - per_payroll)) < MIN_AMOUNT:
            spare = 0.0
        if spare < MIN_AMOUNT:
            f = AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-007",
                procedure_name="Payroll: directors' pay in the staff accounts", severity="LOW", source_row_ref=ref,
                finding_title=f"Directors' accounts hold £{short:,.2f} less than the payroll's directors' pay",
                finding_details=(source + f"The directors' accounts hold £{in_books:,.2f}, and staff wages hold no more "
                                 f"than the staff pay per the payroll, so the difference is not in staff wages. Check "
                                 f"the payroll journals (an allowance or a month missing)." + extras),
                quantified_amount=short, status="OPEN", figures=figures)
            return [f], []
        amount = min(short, round(spare, 2))
        target = SALARY_TO_DIRECTORS[staff]
        entry = _entry(target, staff, amount, chart)
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-007",
            procedure_name="Payroll: directors' pay in the staff accounts", severity="MEDIUM", source_row_ref=ref,
            finding_title=f"Directors' pay £{amount:,.2f} per the payroll is in {chart.name(staff)}",
            finding_details=(source + f"The directors' accounts hold £{in_books:,.2f}"
                             + (f" (and £{moving:,.2f} is moved by another journal)" if moving >= MIN_AMOUNT else "")
                             + f". Directors' pay is shown on its own in the accounts and in the directors' "
                               f"remuneration note. A journal is proposed (Journals tab): {entry}." + extras),
            quantified_amount=amount, suggested_journal=entry, status="OPEN", figures=figures)
        return [f], [_journal(engagement, counter, "Directors' pay per the payroll moved from staff wages", target,
                              staff, amount, chart, f)]
    if short <= -MIN_AMOUNT:
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-007",
            procedure_name="Payroll: directors' pay in the staff accounts", severity="LOW", source_row_ref=ref,
            finding_title=f"Directors' accounts hold £{-short:,.2f} more than the payroll's directors' pay",
            finding_details=(source + f"The directors' accounts hold £{in_books:,.2f}. Check whether staff wages or "
                             f"drawings were posted to the directors' salaries." + extras),
            quantified_amount=-short, status="OPEN", figures=figures)
        return [f], []
    return [], []
