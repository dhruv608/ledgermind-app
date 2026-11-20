"""U-DIV-001 A dividend to clear the overdrawn director's loan, within the reserves: the reserves available are the
opening reserves plus profit after tax; if they cover the loan a dividend can be declared, otherwise s455 is charged.

The dividend is the smaller of the overdrawn balance and the reserves, in round figures, so only what the reserves
cannot cover stays overdrawn and bears s455. Proposed as Dr 8011 Interim dividend paid / Cr 5400 Director's loan, for
the accountant to confirm with the dividend voucher; a rejected proposal is not made again (the full s455 applies).

A dividend is the accountant's decision, never assumed. It is proposed only once the profit is final (a bank job with
suspense left gets none), the point says what to check before approving (the board minute and
voucher, shareholdings, the reserves on the final profit), and until it is approved the loan stays overdrawn and the
full s455 is in the computation."""

import re
from collections import defaultdict
from typing import Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM, ChartLookup

INTERIM_DIVIDEND = 8011
DIVIDEND_CODES = (8010, 8011)
RESERVES_BF = 8000
ROUND_TO = 100.0
# The other shareholders' part of a dividend, owed to them until paid (firm chart: amounts owed to related parties)
OTHER_SHAREHOLDERS = 5416
DESCRIPTION = "Dividend to clear the overdrawn director's loan"
POSTED_ELSEWHERE = "Dividends paid, posted to"
# A payment the bank or ledger calls a dividend ("dividend" or "div"); one received is income, not a dividend paid
DIVIDEND_WORDS = re.compile(r"\bdiv(?:idend)?s?\b", re.I)
RECEIVED_WORDS = re.compile(r"\breceived\b|\bincome\b", re.I)
# A supplier's bill about dividends is a cost, not a dividend paid (e.g. legal fees to prepare a dividend policy)
DIVIDEND_SERVICE = re.compile(r"\b(polic(y|ies)|advice|advise|review|prepar\w*|resolutions?|drafting|tax planning)\b", re.I)
BILL_SOURCE = re.compile(r"\b(payable invoice|bill|purchase invoice|supplier invoice)\b", re.I)


def _pl_effect(journals: Iterable[ProposedJournal], chart: ChartLookup) -> float:
    """The P&L debits less credits of journals (before tax), debit positive."""
    total = 0.0
    for j in journals:
        if j.lines:
            for l in j.lines:
                code = int(l.account_code)
                if chart.is_pre_tax_pl(code):
                    total += float(l.debit or 0) - float(l.credit or 0)
        else:
            if chart.is_pre_tax_pl(int(j.debit_code)):
                total += float(j.amount or 0)
            if chart.is_pre_tax_pl(int(j.credit_code)):
                total -= float(j.amount or 0)
    return total


def _code_effect(journals: Iterable[ProposedJournal], codes) -> float:
    """The debits less credits the journals put on these codes (an opening adjustment on reserves b/f 8000, a dividend
    already proposed on 8010 / 8011)."""
    codes = {int(c) for c in codes}
    total = 0.0
    for j in journals:
        if j.lines:
            total += sum(float(l.debit or 0) - float(l.credit or 0) for l in j.lines if int(l.account_code) in codes)
        else:
            total += (float(j.amount or 0) if int(j.debit_code) in codes else 0.0) -                      (float(j.amount or 0) if int(j.credit_code) in codes else 0.0)
    return total


def dividend_to_clear_dla(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                          counter: List[int], proposed: List[ProposedJournal], ct_tax: float, s455_tax: float = 0.0,
                          already_dividends: float = 0.0) -> Tuple[List[AuditFinding], List[ProposedJournal], float]:
    """The point and journal, and the dividend proposed (0 when none), for the s455 on what is left. One point with
    the choice: no reserves means s455; with reserves the accountant decides between a dividend and s455 (s455_tax: the
    s455 on the whole overdrawn balance, as in the computation)."""
    s455_text = f" of £{s455_tax:,.2f}" if s455_tax >= 0.01 else ""
    from backend.app.services.tax.ct_computation import final_balances
    after = final_balances(engagement.id, tb_records, db)
    # Payments already described as dividends but posted to the loan (U-DIV-002) are moved off it first
    overdrawn = round(sum(after.get(c, 0.0) for c in (DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM)) - already_dividends, 2)
    if overdrawn < 1:
        return [], [], 0.0
    if db.query(ProposedJournal).filter(ProposedJournal.engagement_id == engagement.id,
                                        ProposedJournal.status == "REJECTED",
                                        ProposedJournal.description.like(f"{DESCRIPTION}%")).first():
        return [], [], 0.0                   # the accountant said no: the full s455 applies

    # Profit after tax: the books after approved journals and this review's proposals, less the computation's tax
    pl = sum(v for c, v in after.items() if chart.is_pre_tax_pl(c)) + _pl_effect(proposed, chart)
    profit_after_tax = round(-pl - ct_tax, 2)
    # Reserves b/f and dividends with this review's proposals too, as the profit is (an opening adjustment on 8000
    # left out would let the dividend exceed the reserves, CA 2006 s830)
    opening = round(-(after.get(RESERVES_BF, 0.0) + _code_effect(proposed, [RESERVES_BF])), 2)
    paid = round(sum(after.get(c, 0.0) for c in DIVIDEND_CODES) + _code_effect(proposed, DIVIDEND_CODES), 2)
    available = round(opening + profit_after_tax - paid, 2)
    # The point's figures (one table for both outcomes): the reserves worked out, the loan, and the s455
    from backend.app.services.review.point_figures import amounts
    figures = lambda dividend, left: amounts(
        [("Opening reserves", opening), ("Profit after tax", profit_after_tax)]
        + ([("Dividends already in the books", -paid)] if abs(paid) >= 1 else [])
        + [("Reserves available for a dividend", available, True), ("Directors' loan overdrawn", overdrawn)]
        + ([("Dividend that fits the reserves", dividend)] if dividend >= 1 else [])
        + ([("Left overdrawn (s455 on it)", left, True)] if left >= 1 else [])
        + ([("s455 on the whole balance", s455_tax)] if s455_tax >= 0.01 else []))
    working = (f"opening reserves £{opening:,.2f} + profit after tax £{profit_after_tax:,.2f}"
               + (f" - dividends already in the books £{paid:,.2f}" if abs(paid) >= 1 else "")
               + f" = £{available:,.2f}")
    # A dividend goes to every shareholder of the class by shareholding (Companies Act 2006 and the
    # articles): when the directors hold s% and other shareholders the rest, clearing the loan needs overdrawn / s, and
    # the whole of it must fit in the reserves. Shares from the client setup; not known: the directors' alone
    share = directors_share(engagement)
    needed = overdrawn / share if share else overdrawn
    # Round figures: up when the reserves cover the whole balance (the loan is then cleared), else down
    # to what the reserves allow
    rounded_up = -(-needed // ROUND_TO) * ROUND_TO
    if available >= needed:
        dividend = float(rounded_up if rounded_up <= available else needed)
    else:
        dividend = float(int(available // ROUND_TO) * ROUND_TO) if available >= ROUND_TO else 0.0
    if dividend < 1:
        return [AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-DIV-001",
            procedure_name="Directors' loan: dividend or s455", severity="MEDIUM", source_row_ref="Directors loan account",
            finding_title=f"Directors' loan overdrawn £{overdrawn:,.2f}: no reserves for a dividend, so s455{s455_text} applies",
            finding_details=(f"Reserves available for a dividend: {working}. Not enough to declare a dividend, so the "
                             f"overdrawn balance stays and s455 applies (see the tax computation)."),
            quantified_amount=overdrawn, status="OPEN", figures=figures(0.0, overdrawn))], [], 0.0

    to_directors = round(dividend * share, 2) if share else dividend
    to_others = round(dividend - to_directors, 2)
    left = round(max(overdrawn - to_directors, 0.0), 2)
    entry = (f"Dr {INTERIM_DIVIDEND} {chart.name(INTERIM_DIVIDEND)} £{dividend:,.2f} / Cr {DIRECTORS_LOAN} "
             f"{chart.name(DIRECTORS_LOAN)} £{to_directors:,.2f} / Cr {OTHER_SHAREHOLDERS} "
             f"{chart.name(OTHER_SHAREHOLDERS)} £{to_others:,.2f}" if to_others >= 0.01 else
             f"Dr {INTERIM_DIVIDEND} {chart.name(INTERIM_DIVIDEND)} / Cr {DIRECTORS_LOAN} {chart.name(DIRECTORS_LOAN)} "
             f"£{dividend:,.2f}")
    others_text = (f" The directors hold {share:.0%} of the shares, so a dividend of £{dividend:,.2f} gives them "
                   f"£{to_directors:,.2f} (to the loan) and the other shareholders £{to_others:,.2f} (owed to them until "
                   f"paid); the whole dividend must fit in the reserves." if to_others >= 0.01 else "")
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-DIV-001",
        procedure_name="Directors' loan: dividend or s455", severity="HIGH", source_row_ref="Directors loan account",
        finding_title=(f"Directors' loan overdrawn £{overdrawn:,.2f}: declare a dividend of up to £{dividend:,.2f}, or "
                       f"charge s455{s455_text}?" + (f" (s455 still on the £{left:,.2f} left)" if left >= 1 else ""))[:255],
        finding_details=(f"The directors' loan is overdrawn by £{overdrawn:,.2f} at the year end. Reserves available: "
                         f"{working}. A dividend of £{dividend:,.2f} (the smaller of the two, in round figures) clears "
                         + ("it, so no s455 is due." if left < 1 else
                            f"part of it; the £{left:,.2f} the reserves cannot cover stays overdrawn and bears s455.")
                         + others_text + f" Nothing is assumed: the journal (Journals tab: {entry}) waits for your decision. Before "
                           f"approving it, check that the board minute and dividend voucher exist (dated by the year "
                           f"end), that other shareholders are paid by their shares, and that the reserves are on the "
                           f"final profit. Until you decide, the loan stays overdrawn and the full s455 is in the tax "
                           f"computation; its journal is proposed once you have decided. Reject it if no dividend was "
                           f"declared: the next review then books the full s455."),
        quantified_amount=dividend, suggested_journal=entry, status="OPEN", figures=figures(dividend, left))
    if to_others >= 0.01:
        from backend.app.services.review.payroll_journals import _journal_lines
        j = _journal_lines(engagement, counter, f"{DESCRIPTION} (within reserves of £{available:,.2f}; by shareholding)",
                           [(INTERIM_DIVIDEND, dividend, 0.0), (DIRECTORS_LOAN, 0.0, to_directors),
                            (OTHER_SHAREHOLDERS, 0.0, to_others)], chart, f)
        return [f], [j], dividend
    j = ProposedJournal(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{counter[0]:02d}",
                        description=f"{DESCRIPTION} (within reserves of £{available:,.2f})"[:255],
                        debit_code=INTERIM_DIVIDEND, debit_name=chart.name(INTERIM_DIVIDEND), credit_code=DIRECTORS_LOAN,
                        credit_name=chart.name(DIRECTORS_LOAN), amount=dividend, status="PROPOSED")
    counter[0] += 1
    j._point = f
    return [f], [j], dividend


def directors_share(engagement: ClientEngagement) -> Optional[float]:
    """The directors' part of the shares (0-1) when the client setup lists other shareholders as well and the shares add
    to 100%; None otherwise (the directors are taken to hold them all)."""
    import json
    profile = getattr(engagement, "profile", None)
    try:
        setup = json.loads(profile.setup or "{}") if profile is not None and profile.setup else {}
        directors = json.loads(profile.directors or "[]") if profile is not None and profile.directors else []
    except (TypeError, ValueError):
        return None
    people = setup.get("people") or {}
    details = people.get("director_details") or {}
    names = {str(n).strip().lower() for n in directors}
    try:
        mine = sum(float((details.get(n) or {}).get("shares") or 0) for n in directors)
        others = sum(float(x.get("shares") or 0) for x in people.get("shareholders") or []
                     if str(x.get("name") or "").strip().lower() not in names)
    except (TypeError, ValueError):
        return None
    if mine <= 0 or others <= 0 or abs(mine + others - 100) > 0.5:
        return None
    return round(mine / 100, 4)


def dividends_posted_elsewhere(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                               counter: List[int], ct_tax: float, proposed: List[ProposedJournal]
                               ) -> Tuple[List[AuditFinding], List[ProposedJournal], float]:
    """U-DIV-002: payments described as dividends but posted to a P&L account (directors' salary, wages): a
    dividend is never a cost, so they are moved to interim dividends, one journal per account, with the reserves test
    (reserves b/f + profit after tax - dividends >= 0; a fail is a possible unlawful dividend). Dividends paid out of
    the directors' loan are left to U-DIV-001: how much to declare there is the accountant's decision within the
    reserves (it can be less than the loan's 'dividend' payments). A rejected journal is not proposed again."""
    from backend.app.services.sop.common import gl_lines
    lines = [l for l in gl_lines(engagement.id, tb_records, db)
             if DIVIDEND_WORDS.search(l.description) and not RECEIVED_WORDS.search(l.description)
             and not DIVIDEND_SERVICE.search(l.description) and not BILL_SOURCE.search(l.source or "")
             and chart.is_pre_tax_pl(l.code) and l.debit - l.credit > 0.005]
    by_code = defaultdict(list)
    for l in lines:
        by_code[l.code].append(l)
    rejected = {j.credit_code for j in db.query(ProposedJournal).filter(
        ProposedJournal.engagement_id == engagement.id, ProposedJournal.status == "REJECTED",
        ProposedJournal.description.like(f"{POSTED_ELSEWHERE}%"))}
    totals = {c: round(sum(l.debit - l.credit for l in ls), 2) for c, ls in by_code.items() if c not in rejected}
    totals = {c: t for c, t in totals.items() if t >= 1}
    if not totals:
        return [], [], 0.0
    total = round(sum(totals.values()), 2)

    # Reserves test: reserves b/f + profit after tax - dividends already in the books - these
    from backend.app.services.tax.ct_computation import final_balances
    after = final_balances(engagement.id, tb_records, db)
    moved_from_pl = sum(t for c, t in totals.items() if chart.is_pre_tax_pl(c))     # salary moved out raises the profit
    pl = sum(v for c, v in after.items() if chart.is_pre_tax_pl(c)) + _pl_effect(proposed, chart) - moved_from_pl
    profit_after_tax = round(-pl - ct_tax, 2)
    # Reserves b/f and dividends with this review's proposals too, as the profit is (an opening adjustment on 8000
    # left out would let the dividends exceed the reserves, CA 2006 s830)
    opening = round(-(after.get(RESERVES_BF, 0.0) + _code_effect(proposed, [RESERVES_BF])), 2)
    paid = round(sum(after.get(c, 0.0) for c in DIVIDEND_CODES) + _code_effect(proposed, DIVIDEND_CODES), 2)
    left = round(opening + profit_after_tax - paid - total, 2)
    reserves = (f"Reserves test: opening reserves £{opening:,.2f} + profit after tax £{profit_after_tax:,.2f}"
                + (f" - dividends already in the books £{paid:,.2f}" if abs(paid) >= 1 else "")
                + f" - these £{total:,.2f} = £{left:,.2f}: "
                + ("passed." if left >= 0 else "FAILED, the dividends are more than the reserves: a possible unlawful "
                   "dividend (CA 2006 s830), refer to the accountant."))

    where = "; ".join(f"£{t:,.2f} in {c} {chart.name(c)} ({len(by_code[c])} line{'s' if len(by_code[c]) != 1 else ''})"
                      for c, t in sorted(totals.items(), key=lambda x: -x[1]))
    sample = "; ".join(f"{l.when:%d/%m/%Y} £{l.debit - l.credit:,.2f} '{l.description[:60]}'"
                       for c in totals for l in sorted(by_code[c], key=lambda x: x.when)[:3])
    f = AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-DIV-002",
        procedure_name="Dividends: paid but posted to another account", severity="HIGH", source_row_ref="Dividends",
        finding_title=f"£{total:,.2f} of payments described as dividends are posted to other accounts, not dividends"[:255],
        finding_details=(
            f"Ledger lines whose description says dividend: {where}. For example: {sample}. Paid as dividends, they "
            f"belong in {INTERIM_DIVIDEND} {chart.name(INTERIM_DIVIDEND)}: a dividend is paid out of profits, "
            f"never a cost, so the profit and the tax are understated while they sit here. {reserves} A journal is "
            f"proposed for each account "
            f"(Journals tab). Before approving, check the board minute and dividend vouchers and that each shareholder "
            f"was paid by shareholding. If any were really salary or a loan, reject that journal."),
        quantified_amount=total, status="OPEN")
    journals = []
    for c, t in sorted(totals.items(), key=lambda x: -x[1]):
        j = ProposedJournal(engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{counter[0]:02d}",
                            description=f"{POSTED_ELSEWHERE} {c} {chart.name(c)}"[:255],
                            debit_code=INTERIM_DIVIDEND, debit_name=chart.name(INTERIM_DIVIDEND), credit_code=c,
                            credit_name=chart.name(c), amount=t, status="PROPOSED")
        counter[0] += 1
        j._point = f
        journals.append(j)
    on_dla = round(sum(t for c, t in totals.items() if c in (DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM)), 2)
    return [f], journals, on_dla
