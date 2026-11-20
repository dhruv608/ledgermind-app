"""
Findings for the review list from every SOP check. Used by the upload checks and by the review, so a review run
(which clears open findings first) keeps them.
"""

from typing import Iterable, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, MasterCOA, TBRecord
from backend.app.services.sop.accruals import accrual_review
from backend.app.services.sop.capital import CAPITAL_QUESTION, FLAG_CAPITAL, capital_review, capitalisation_limit
from backend.app.services.sop.duplicates import FLAG_MIXED, duplicate_review
from backend.app.services.sop.pattern import PATTERN_RULES, pattern_review
from backend.app.services.sop.restaurant import RESTAURANT_RULES, restaurant_review
from backend.app.services.sop.property import FLAGS as PROPERTY_FLAGS, SEVERITY as PROPERTY_SEVERITY, property_review
from backend.app.services.setup.profile_service import confirmed_industry
from backend.app.services.sop.prepayments import FLAG_PREPAYMENT, PREPAY_MIN_PORTION, PREPAY_QUESTION, prepayment_review
import re

from backend.app.services.mapping.chart_lookup import DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM
from backend.app.services.sop.common import gl_lines
from backend.app.services.review.point_figures import row, table
from backend.app.services.sop.related_party import FLAG_LOAN, masking_loans, person_lenders, related_parties, related_party_review


DLA_SALARY_TEXT = re.compile(r"payroll|salary|salaries|wage|net pay|brightpay", re.I)


# A duplicates SOP flag in a point's title
WHAT_TWICE = {"duplicate": "entered twice", "possible": "possibly entered twice (same amount within a week)",
              "unallocated": "paid but still outstanding"}


def _supplier_point(engagement: ClientEngagement, supplier: str, counts: str, exact) -> AuditFinding:
    """One supplier with bills and also direct payments; exact: the same amounts entered both ways (BillAlsoPaid)."""
    if exact is not None:
        listed = "; ".join(f"£{amount:,.2f} bill {b:%d/%m/%Y}, paid direct {d:%d/%m/%Y} ({account[:40]})"
                           for b, d, amount, account in exact.pairs[:8])
        return AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (bill and direct payment)",
            severity="HIGH" if exact.total >= 1000 else "MEDIUM", source_row_ref=f"supplier {supplier}"[:100],
            finding_title=(f"{supplier[:60]}: {len(exact.pairs)} cost{'s' if len(exact.pairs) > 1 else ''} entered as a "
                           f"bill and again as a direct payment (£{exact.total:,.2f})")[:255],
            finding_details=(f"{listed}{' and more' if len(exact.pairs) > 8 else ''}. Both lines are costs, so each is "
                             f"counted twice: the direct payment should have paid the bill instead. Remove the extra cost "
                             f"(match the payment to the bill), or clear this point with a note if they are different "
                             f"purchases." + (f" This year: {counts}." if counts else "")),
            quantified_amount=exact.total, suggested_journal=None, status="OPEN",
            figures=table(["", "Bill", "Paid direct", "Amount"],
                          [row(account[:40], f"{b:%d/%m/%Y}", f"{d:%d/%m/%Y}", amount) for b, d, amount, account in exact.pairs]),
        )
    return AuditFinding(
        engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (bills and direct payments)",
        severity="LOW", source_row_ref=f"supplier {supplier}"[:100],
        finding_title=f"{supplier[:70]}: bills and also direct payments"[:255],
        finding_details=(f"This year: {counts}. When a supplier sends bills, its payments should pay those bills; a direct "
                         f"payment (spend money, card, direct debit) coded to a cost as well may count the same cost "
                         f"twice, including a lump-sum payment of several bills. Check the supplier's account: match the "
                         f"payments to the bills, or clear this point if they were separate purchases."),
        quantified_amount=0.0, suggested_journal=None, status="OPEN",
    )


def _largest(top) -> str:
    """The largest items of a pattern, restaurant or property rule: account, date, amount."""
    if any(f.when for f in top):
        return table(["Account", "Date", "Amount"], [row(f.account[:40], f"{f.when:%d/%m/%Y}" if f.when else "", f.amount) for f in top])
    return table(["Account", "Amount"], [row(f.account[:40], f.amount) for f in top])


def sop_findings(engagement: ClientEngagement, tb_records: Iterable[TBRecord], db: Session) -> List[AuditFinding]:
    tb_records = list(tb_records)
    findings = []
    limit = capitalisation_limit(engagement)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    capital_flags = capital_review(str(engagement.id), tb_records, db, limit)
    for f in capital_flags:
        target = f" (suggested class: {f.suggested_code} {chart[f.suggested_code].std_name})" if f.suggested_code in chart else ""
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G1", procedure_name="Revenue vs capital",
            severity="LOW" if f.supplier_only else "HIGH" if f.amount >= 5 * limit else "MEDIUM",
            source_row_ref=f"{f.when:%d/%m/%Y} {f.account}"[:100],
            finding_title=f"{f.account[:80]}: £{f.amount:,.2f} may be a fixed asset ({', '.join(f.keywords)[:60]})"[:255],
            finding_details=(f"{FLAG_CAPITAL.format(limit=limit)} '{f.description[:150]}' on {f.when:%d/%m/%Y}; matched "
                             f"{'the supplier name only (an indicator, not proof)' if f.supplier_only else 'keywords'}: "
                             f"{', '.join(f.keywords)}{target}. Client question: {CAPITAL_QUESTION}"),
            quantified_amount=f.amount, suggested_journal=None, status="OPEN",
        ))
    # The purchases the keywords cannot read (the ledger names only the shop): the AI's 'asset' or 'not sure' answers,
    # each a question for the accountant, never a journal (sop/capital_ai.py)
    # From the firm's equipment limit when it is lower: under the general limit only the AI's 'asset' answers count
    from backend.app.services.sop.capital import equipment_limit
    from backend.app.services.sop.capital_ai import ai_capital_review
    from backend.app.services.setup.engagement_setup import INDUSTRY_NAMES
    industry = confirmed_industry(getattr(engagement, "profile", None))
    for f in ai_capital_review(str(engagement.id), gl_lines(str(engagement.id), tb_records, db), chart,
                               equipment_limit(engagement), {(c.when, round(c.amount, 2)) for c in capital_flags},
                               INDUSTRY_NAMES.get(industry or "", ""), db):
        sure = f.verdict == "asset"
        if f.amount < limit and not sure:
            continue
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G1", procedure_name="Revenue vs capital (AI review of the supplier)",
            severity="MEDIUM" if sure else "LOW",
            source_row_ref=f"{f.when:%d/%m/%Y} {f.account}"[:100],
            finding_title=(f"{f.account[:80]}: £{f.amount:,.2f} "
                           + (f"looks like a fixed asset ({f.asset_class})" if sure else "may be a fixed asset") + "?")[:255],
            finding_details=(f"'{f.description[:150]}' on {f.when:%d/%m/%Y}, posted as a cost. The ledger names only the "
                             f"supplier, so the AI was asked: {f.reason} Check the invoice: if it lasts more than a year "
                             f"and is at or over the £{limit:,.0f} limit, move it to fixed asset additions. "
                             f"Client question: {CAPITAL_QUESTION}"),
            quantified_amount=f.amount, suggested_journal=None, status="OPEN",
        ))
    duplicate_flags = duplicate_review(str(engagement.id), engagement.period_end_date, db)
    for f in duplicate_flags:
        if f.check == "mixed":
            continue
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions",
            severity={"duplicate": "HIGH", "possible": "LOW"}.get(f.check, "MEDIUM"),
            source_row_ref=f"{f.side} {f.contact}"[:100],
            finding_title=f"{f.contact[:80]}: £{f.amount:,.2f} {WHAT_TWICE[f.check]}"[:255],
            finding_details=f"{f.message} {f.detail}. Client question: {f.question}",
            quantified_amount=f.amount, suggested_journal=None, status="OPEN",
        ))
    # Suppliers with bills and also direct payments: each highlighted once (a payment can be a lump sum; a supplier
    # paid only by direct payments is fine). Where a direct payment is the same amount as a bill (both costs), the point says so and is raised higher.
    from backend.app.services.sop.duplicates import _contact_key, bills_also_paid_direct
    exact = {_contact_key(s.supplier): s for s in bills_also_paid_direct(str(engagement.id), tb_records, db)}
    others = []
    for f in [f for f in duplicate_flags if f.check == "mixed" and f.side == "supplier"]:
        s = exact.pop(_contact_key(f.contact), None)
        if s is not None:
            findings.append(_supplier_point(engagement, f.contact, f.detail, s))
        else:
            others.append(f)
    for s in exact.values():
        findings.append(_supplier_point(engagement, s.supplier, "", s))
    # A steady monthly charge entered twice in one month (a bill and the direct debit, or two direct debits): the
    # suppliers already raised above are not raised again
    from backend.app.services.sop.duplicates import same_supplier, twice_in_a_month
    raised = [_contact_key(f.source_row_ref.replace("supplier ", "", 1)) for f in findings
              if f.procedure_ref == "G5" and (f.source_row_ref or "").startswith("supplier ")]
    for t in twice_in_a_month(str(engagement.id), tb_records, db):
        if any(same_supplier(_contact_key(t.supplier), r) for r in raised):
            continue
        listed = "; ".join(f"{a:%d/%m/%Y} and {b:%d/%m/%Y}" for a, b in t.months[:6])
        extra = round(t.amount * len(t.months), 2)
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (monthly charge twice)",
            severity="MEDIUM" if extra >= 100 else "LOW", source_row_ref=f"supplier {t.supplier}"[:100],
            finding_title=(f"{t.supplier[:60]}: the monthly £{t.amount:,.2f} charged twice in "
                           f"{len(t.months)} month{'s' if len(t.months) > 1 else ''} (£{extra:,.2f})")[:255],
            finding_details=(f"{t.supplier} is charged £{t.amount:,.2f} once a month on {t.account[:60]}, but twice on "
                             f"{listed}. Usually the bill and the direct debit for the same month were both entered as "
                             f"costs (and any VAT on it claimed twice). Check the supplier's statement: remove the extra "
                             f"cost, or clear this point if two charges were really due that month."),
            quantified_amount=extra, suggested_journal=None, status="OPEN",
            figures=table(["Charged twice", "Second charge", "Amount"],
                          [row(f"{a:%d/%m/%Y}", f"{b:%d/%m/%Y}", t.amount) for a, b in t.months])))
    # The rest in one point, every supplier listed once with its counts (a review of 40 separate points is unreadable)
    if others:
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (bills and direct payments)",
            severity="LOW", source_row_ref="Suppliers with bills and direct payments"[:100],
            finding_title=f"{len(others)} supplier{'s' if len(others) > 1 else ''} with bills and also direct payments: check each once"[:255],
            finding_details=("; ".join(f"{f.contact[:40]} ({f.detail.replace(' this year', '')})" for f in others[:40])
                             + (f" and {len(others) - 40} more" if len(others) > 40 else "")
                             + ". When a supplier sends bills, its payments should pay those bills; a direct payment "
                               "(spend money, card, direct debit) coded to a cost as well may count the same cost twice, "
                               "including a lump-sum payment of several bills. Check each supplier's account once. A "
                               "supplier paid only directly (no bills) is not listed."),
            quantified_amount=0.0, suggested_journal=None, status="OPEN",
            figures=table(["Supplier", "This year"], [row(f.contact[:40], f.detail.replace(" this year", "")) for f in others]),
        ))
    customers = [f for f in duplicate_flags if f.check == "mixed" and f.side == "customer"]
    if customers:
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions",
            severity="LOW", source_row_ref="Duplicates review (G2.3)",
            finding_title=f"{len(customers)} customer(s) have invoices and also direct receipts"[:255],
            finding_details=(f"{FLAG_MIXED} {', '.join(f.contact for f in customers[:10])}"
                             f"{' and others' if len(customers) > 10 else ''}: see the duplicates review tab (G2.3)."),
            quantified_amount=0.0, suggested_journal=None, status="OPEN",
        ))
    # A cost booked twice in two ways: salary by journal and by payment; an invoice accrued and also billed
    from backend.app.services.sop.duplicates import costs_booked_twice
    booked_twice = costs_booked_twice(str(engagement.id), tb_records, db)
    for c in [c for c in booked_twice if c.kind == "salary"]:
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (salary booked twice)",
            severity="HIGH", source_row_ref=c.account[:100],
            finding_title=f"{c.account[:70]}: salary may be booked twice (£{c.amount:,.2f})"[:255],
            finding_details=(f"{c.detail}. The payroll journal already makes the cost; the payments to the employee or "
                             f"director should go to the net wages (and PAYE) account, not to the cost again. If so, move "
                             f"the payments to net wages: the cost falls by £{c.amount:,.2f}. Clear this point with a "
                             f"note if the payments are for something else."),
            quantified_amount=c.amount, suggested_journal=None, status="OPEN",
        ))
    billed = [c for c in booked_twice if c.kind == "accrued and billed"]
    if billed:
        total = round(sum(c.amount for c in billed), 2)
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (accrued and also billed)",
            severity="HIGH" if total >= 1000 else "MEDIUM", source_row_ref="Accruals also billed"[:100],
            finding_title=f"{len(billed)} invoice{'s' if len(billed) > 1 else ''} accrued and also entered as a bill (£{total:,.2f})"[:255],
            finding_details=("; ".join(f"£{c.amount:,.2f} {c.detail} to {c.account[:40]}" for c in billed[:10])
                             + ". Each cost is counted twice: once by the accrual journal and once by the bill. Reverse "
                               "the accrual for each invoice that was billed, or clear this point with a note."),
            quantified_amount=total, suggested_journal=None, status="OPEN",
            figures=table(["Account", "Invoice", "Amount"], [row(c.account[:40], c.detail, c.amount) for c in billed]),
        ))
    # Two bills from one supplier for the same amount on the same day (no bill number to compare): one point per job
    from backend.app.services.sop.duplicates import same_day_bills
    pairs = same_day_bills(str(engagement.id), tb_records, db)
    if pairs:
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (same bill twice)",
            severity="MEDIUM", source_row_ref="Same-day bills"[:100],
            finding_title=f"{len(pairs)} supplier bill{'s' if len(pairs) > 1 else ''} entered twice on the same day, only one paid"[:255],
            finding_details=("; ".join(f"{p.supplier[:40]} £{p.amount:,.2f} twice on {p.when:%d/%m/%Y} ({p.account[:35]})"
                                       for p in pairs[:12])
                             + (" and more" if len(pairs) > 12 else "")
                             + ". Two bills from one supplier for the same amount on the same day, of which only one was "
                               "paid: the unpaid one is usually the same bill entered twice (it then sits in creditors "
                               "and in costs). Check the invoices: remove the extra bill, or clear this point if both "
                               "were real deliveries and one is still owed."),
            quantified_amount=round(sum(p.amount for p in pairs), 2), suggested_journal=None, status="OPEN",
            figures=table(["Supplier", "Date", "Each bill"], [row(p.supplier[:40], f"{p.when:%d/%m/%Y}", p.amount) for p in pairs]),
        ))
    from backend.app.services.sop.duplicates import journals_twice
    twice = journals_twice(str(engagement.id), tb_records, db)
    if len(twice) > 3:
        # Many months: one point listing them (the journals are usually one batch posted again)
        extra = round(sum(j.amount * (j.times - 1) for j in twice), 2)
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (journal posted twice)",
            severity="HIGH", source_row_ref="Journals posted twice"[:100],
            finding_title=f"{len(twice)} journals posted more than once in the same month (£{extra:,.2f} extra)"[:255],
            finding_details=("Journals with exactly the same lines were posted more than once in one month: "
                             + "; ".join(f"£{j.amount:,.2f} x{j.times} in {j.month:%b %Y}" for j in twice[:20])
                             + ". Often a batch of payroll or other journals imported twice. Reverse the extra ones, or "
                             "clear this point with a note if each is a different item."),
            quantified_amount=extra, suggested_journal=None, status="OPEN",
            figures=table(["Month", "Times", "Each"], [row(f"{j.month:%b %Y}", f"x{j.times}", j.amount) for j in twice]),
        ))
        twice = []
    for j in twice:
        lines = "; ".join(f"{name} {'Dr' if v > 0 else 'Cr'} £{abs(v):,.2f}" for name, v in j.lines[:6])
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G5", procedure_name="Duplicate transactions (journal posted twice)",
            severity="HIGH" if j.amount >= 1000 else "MEDIUM",
            source_row_ref=f"Journals {j.month:%b %Y}"[:100],
            finding_title=f"The same journal (£{j.amount:,.2f}) posted {j.times} times in {j.month:%B %Y}"[:255],
            finding_details=(f"Journals with exactly the same lines were posted on {', '.join(f'{d:%d/%m/%Y}' for d in j.dates)}: "
                             f"{lines}. A monthly journal is posted once a month; twice in one month is usually a "
                             f"duplicate (for example payroll for the same month posted again). If it is, reverse the "
                             f"extra one{'s' if j.times > 2 else ''}. If each is a different item that happens to be the "
                             f"same, clear this point with a note."),
            quantified_amount=round(j.amount * (j.times - 1), 2), suggested_journal=None, status="OPEN",
            figures=table([f"Each time ({', '.join(f'{d:%d/%m/%Y}' for d in j.dates)})", "Debit", "Credit"],
                          [row(name, v if v > 0 else None, -v if v < 0 else None) for name, v in j.lines]),
        ))
    for f in accrual_review(str(engagement.id), engagement.period_end_date, tb_records, db):
        missing = ", ".join(m.strftime("%b %Y") for m in f.missing)
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G3", procedure_name="Missing accruals",
            severity="HIGH" if f.final_missing else "MEDIUM", source_row_ref=f.account[:100],
            finding_title=f"{f.account[:120]}: no cost in {missing}"[:255],
            finding_details=(f"{f.message} Cost recorded in {12 - len(f.missing)} of 12 months; average monthly cost "
                             f"£{f.average:,.2f} (for review only). Client question: {f.client_question}"),
            quantified_amount=f.average if f.final_missing else 0.0, suggested_journal=None, status="OPEN",
            figures=table(["", ""], [row("Months with a cost", f"{12 - len(f.missing)} of 12"),
                                     row("Average a month", f.average),
                                     row("Months with none", missing, strong=True)]),
        ))
    for f in prepayment_review(str(engagement.id), engagement.period_end_date, tb_records, db):
        if f.prepaid < PREPAY_MIN_PORTION:
            continue                    # too small to ask about
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G2", procedure_name="Prepayments",
            severity="MEDIUM", source_row_ref=f"{f.when:%d/%m/%Y} {f.account}"[:100],
            finding_title=f"{f.account[:80]}: £{f.prepaid:,.2f} of £{f.amount:,.2f} relates to after the year end"[:255],
            finding_details=(f"{FLAG_PREPAYMENT} '{f.description[:150]}' on {f.when:%d/%m/%Y}: period {f.start:%d/%m/%Y} to "
                             f"{f.end:%d/%m/%Y} ({f.basis}); {f.months_after} of {f.total_months} months after the "
                             f"year-end, so about £{f.prepaid:,.2f} (straight line, for review only). "
                             f"Client question: {PREPAY_QUESTION}"),
            quantified_amount=f.prepaid, suggested_journal=None, status="OPEN",
            figures=table(["", ""], [row(f"Paid on {f.when:%d/%m/%Y}", f.amount),
                                     row("Covers", f"{f.start:%d/%m/%Y} to {f.end:%d/%m/%Y}"),
                                     row("Months after the year end", f"{f.months_after} of {f.total_months}"),
                                     row("Prepaid at the year end", f.prepaid, strong=True)]),
        ))
    pattern_flags = pattern_review(str(engagement.id), engagement.period_end_date, tb_records, db)
    for rule, (reason, severity) in PATTERN_RULES.items():
        hits = [f for f in pattern_flags if rule in f.rules]
        if not hits:
            continue
        top = sorted(hits, key=lambda f: -f.amount)[:5]
        examples = "; ".join((f"{f.when:%d/%m/%Y} " if f.when else "") + f"{f.account[:40]} £{f.amount:,.2f}" for f in top)
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G9", procedure_name="Pattern & anomaly checks",
            severity=severity, source_row_ref="Pattern review (K0)",
            finding_title=f"Rule {rule}: {len(hits)} payment(s) - {reason.split('.')[0]}"[:255],
            finding_details=(f"{reason} Largest: {examples}. Full list with dates and descriptions on the pattern review "
                             f"tab (K0)."),
            quantified_amount=round(sum(f.amount for f in hits), 2), suggested_journal=None, status="OPEN",
            figures=_largest(top),
        ))
    # Industry SOPs, only for an industry the accountant has confirmed
    if confirmed_industry(getattr(engagement, "profile", None)) == "RES":
        review = restaurant_review(str(engagement.id), engagement.period_end_date, tb_records, db)
        for rule, (reason, severity) in RESTAURANT_RULES.items():
            hits = [f for f in review.flags if f.rule == rule]
            if not hits:
                continue
            top = sorted(hits, key=lambda f: -f.amount)[:5]
            examples = "; ".join((f"{f.when:%d/%m/%Y} " if f.when else "") + f"{f.account[:40]} £{f.amount:,.2f}"
                                 for f in top)
            findings.append(AuditFinding(
                engagement_id=engagement.id, procedure_ref=f"RES-{rule}", procedure_name="Restaurant checks",
                severity=severity, source_row_ref="Restaurant review (K0.1)",
                finding_title=f"Rule {rule}: {len(hits)} item(s) - {reason.split('.')[0]}"[:255],
                finding_details=f"{reason} Largest: {examples}. Full list on the restaurant review tab (K0.1).",
                quantified_amount=round(sum(f.amount for f in hits), 2), suggested_journal=None, status="OPEN",
                figures=_largest(top),
            ))
        for note in review.sense_checks():
            findings.append(AuditFinding(
                engagement_id=engagement.id, procedure_ref="RES-SENSE", procedure_name="Restaurant checks",
                severity="MEDIUM", source_row_ref="Restaurant review (K0.1)", finding_title=note.split(";")[0][:255],
                finding_details=note, quantified_amount=0.0, suggested_journal=None, status="OPEN",
            ))
    # Property SOP: for every property on the client setup (rental or trading), whatever the industry
    profile = getattr(engagement, "profile", None)
    summaries = property_review(str(engagement.id), engagement.period_end_date, tb_records, db, profile, limit)
    for s in summaries:
        for rule in PROPERTY_FLAGS:
            hits = [f for f in s.flags if f.rule == rule]
            if not hits:
                continue
            top = sorted(hits, key=lambda f: -f.amount)[:5]
            examples = "; ".join((f"{f.when:%d/%m/%Y} " if f.when else "") + f"{f.account[:40]} £{f.amount:,.2f}" for f in top)
            findings.append(AuditFinding(
                engagement_id=engagement.id, procedure_ref=f"PRP-{rule}", procedure_name="Property checks",
                severity=PROPERTY_SEVERITY[rule], source_row_ref=f"{s.entry.name} ({s.entry.model.lower()})"[:100],
                finding_title=f"{s.entry.name}: {len(hits)} item(s) - {PROPERTY_FLAGS[rule].split('.')[0]}"[:255],
                finding_details=(f"{PROPERTY_FLAGS[rule]} Rent start: {s.rent_start or 'none this year'} ({s.rent_start_source}). "
                                 f"Largest: {examples}. Client question: {hits[0].question} Full list on the property review "
                                 f"tab (C1.3)."),
                quantified_amount=round(sum(f.amount for f in hits), 2), suggested_journal=None, status="OPEN",
                figures=_largest(top),
            ))
    if not summaries and confirmed_industry(profile) == "PRP":
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="PRP-0", procedure_name="Property checks",
            severity="MEDIUM", source_row_ref="Client setup",
            finding_title="Add the client's properties (rental or trading) on the client setup screen",
            finding_details=("The property checks need each property classified first: held to earn rent (fixed asset) or "
                             "to sell (stock). Client question: Is this property held for resale or long-term rental?"),
            quantified_amount=0.0, suggested_journal=None, status="OPEN",
        ))

    # Director's salary settled through the director's loan account instead of being paid from the bank (always the
    # director's DLA): flagged so the DLA and payroll are checked together
    dla_salary = [l for l in gl_lines(str(engagement.id), tb_records, db)
                  if l.code in (DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM) and l.credit >= 1
                  and DLA_SALARY_TEXT.search(f"{l.description} {l.source}")]
    if dla_salary:
        months = ", ".join(f"{l.when:%b %Y} £{l.credit:,.2f}" for l in dla_salary)
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="G6", procedure_name="Payroll",
            severity="MEDIUM", source_row_ref=", ".join(sorted({l.account for l in dla_salary}))[:100],
            finding_title=(f"Director's salary settled through the DLA: {len(dla_salary)} month(s), "
                           f"£{sum(l.credit for l in dla_salary):,.2f}")[:255],
            finding_details=(f"Net pay credited to the director's loan account instead of being paid from the bank: {months}. "
                             "Check the DLA balance and the s455 position; the payroll summary (G6.2) shows these months."),
            quantified_amount=sum(l.credit for l in dla_salary), suggested_journal=None, status="OPEN",
        ))

    # Related parties: one point per related party with transactions (every line is on tab G3.2)
    if not related_parties(engagement):
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="RP-00", procedure_name="Related parties",
            severity="LOW", source_row_ref="Client setup",
            finding_title="No directors in the client setup: the related party check could not run",
            finding_details=("The related party check searches the ledger for the directors and shareholders. Add them on "
                             "the Setup tab, or use 'Get directors from Companies House'."),
            quantified_amount=0.0, suggested_journal=None, status="OPEN",
        ))
    else:
        summaries = related_party_review(engagement, tb_records, db)
        for s in summaries:
            surname_only = all(l.match.startswith("Surname only") for l in s.lines)
            total = sum(abs(l.amount) for l in s.lines)
            where = ", ".join(sorted({l.account for l in s.lines}))[:100]
            findings.append(AuditFinding(
                engagement_id=engagement.id, procedure_ref="RP-01", procedure_name="Related parties",
                severity="LOW" if surname_only else "MEDIUM", source_row_ref=where,
                finding_title=(f"{s.party.name}: {len(s.lines)} transaction(s) with a related party"
                               f"{' (surname match only)' if surname_only else ''}")[:255],
                finding_details=(f"{s.party.role} ({s.party.source}). {len(s.pl)} line(s) in the profit & loss, "
                                 f"{len(s.bs)} on the balance sheet, £{total:,.2f} in total; accounts: {where}. "
                                 f"{s.lines[0].message} Every line is listed on the related parties tab (G3.2)."),
                quantified_amount=total, suggested_journal=None, status="OPEN",
            ))
        for s in masking_loans(summaries):
            findings.append(AuditFinding(
                engagement_id=engagement.id, procedure_ref="RP-02", procedure_name="Related parties",
                severity="MEDIUM", source_row_ref=s.party.name[:100],
                finding_title=f"{s.party.name}: repeated costs but no loan or payable balance"[:255],
                finding_details=(f"{FLAG_LOAN} {len(s.pl)} cost line(s), £{sum(l.amount for l in s.pl):,.2f}. "
                                 "Client question: Are these business costs, or should they go to the director's loan account?"),
                quantified_amount=sum(l.amount for l in s.pl), suggested_journal=None, status="OPEN",
            ))
    # A loan from a person not on the related party list: a director's close family member is a related party
    # (FRS 102 s33), so the accountant asks who the lender is; a third party's loan is an other loan, not a bank loan
    for lender in person_lenders(engagement, tb_records, db):
        accounts = ", ".join(f"{a} ({c})" for a, c in lender["accounts"].items())[:100]
        on_bank = any(5100 <= c < 5110 or 5500 <= c < 5510 for c in lender["accounts"].values())
        findings.append(AuditFinding(
            engagement_id=engagement.id, procedure_ref="RP-03", procedure_name="Related parties",
            severity="MEDIUM", source_row_ref=accounts,
            finding_title=f"Loan from a person: {lender['name']}"[:255],
            finding_details=(f"{lender['name']} lent £{lender['lent']:,.2f} and was repaid £{lender['repaid']:,.2f} this year "
                             f"on {accounts}. Client question: is {lender['name']} a director, a shareholder or a close "
                             f"family member of one? If so, add them to the related parties on the Setup tab: the loan is a "
                             f"related party transaction to disclose (FRS 102 s33). If not, it is a loan from a third "
                             f"party." + (" It is on a bank loans code: other loans are 5110 (within one year) and 5510 "
                                          "(after one year)." if on_bank else "")
                             + " Ask for the loan agreement (interest and repayment terms). If no interest is charged, "
                               "or less than a market rate: a small company may keep it at the amount received when the "
                               "lender is in a director's close family group and that group includes a shareholder (FRS "
                               "102 11.13A); otherwise a below-market loan that is a financing arrangement is measured at "
                               "its present value (FRS 102 11.13)."),
            quantified_amount=lender["lent"], suggested_journal=None, status="OPEN",
        ))
    return findings
