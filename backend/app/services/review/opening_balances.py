"""Opening balances (J2 reserves): this year's opening balances against
last year's closing balances, balance by balance, and the profit and loss reserve brought forward against last
year's closing reserve.

The books' opening of a balance is its closing balance less this year's ledger movement; last year's closing comes
from last year's job in the app (after its approved journals), else last year's closing TB uploaded in the firm's
codes. Fixed assets are compared class by class (last year's additions and charge are this year's cost and
depreciation brought forward). Then:
- two balances that differ by the same amount the opposite way are the same money on another code: no journal;
- when the other differences come to the reserve difference, they are last year's year-end adjustments that never
  reached the client's books: one journal brings each balance to last year's figure against reserves brought
  forward (U-OB-001);
- otherwise the difference is not explained by the balances (often last year's income or costs posted in this
  year's books): a question for the accountant with the figures, and no journal is guessed (U-OB-002).
Stock is left to the stock journals (U-STK), which already bring last year's stock into this year."""

from itertools import combinations
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup

RESERVE_BF, PRIOR_YEAR_ADJUSTMENT = 8000, 8030
STOCK = range(4300, 4311)
FIXED_ASSETS = range(4000, 4200)
SUSPENSE = 9999                  # suspense: where software parks opening differences
TOLERANCE = 1.0                  # pence and rounding between last year's figures and the books
YEAR_END_ENTRIES = {4900, 4950, 5360, 5310, 4450}   # prepayments, accrued income, accruals, corporation tax
NAME = "M1 Opening balances (J2 reserves)"


def _money(v: float) -> str:
    return f"£{abs(v):,.2f}"


def _is_reserve(code: int) -> bool:
    return 8000 <= code <= 8099


def last_year_closing(engagement: ClientEngagement, db: Session) -> Tuple[str, Optional[Dict[int, float]]]:
    """Last year's closing balance by firm code and where it came from; None when neither source is there."""
    from backend.app.services.review.last_year import last_year_job, prior_balances_by_code
    from backend.app.services.tax.ct_computation import final_balances
    from sqlalchemy import select
    last = last_year_job(engagement, db)
    if last is not None and last.period_end_date < engagement.period_end_date:
        ly_tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == last.id)).scalars())
        if ly_tb:
            return (f"last year's job in the app (year ended {last.period_end_date:%d/%m/%Y})",
                    final_balances(str(last.id), ly_tb, db))
    prior = prior_balances_by_code(engagement, db)
    return ("last year's closing TB", prior) if prior else ("", None)


def last_year_journals(engagement: ClientEngagement, db: Session) -> List[Tuple[str, List[Tuple[int, float, float]]]]:
    """Last year's journals, each (label, [(code, debit, credit)]): last year's job in the app, its approved journals.
    (Last year's final working paper is not read: it often changes after it is finished, and this year follows the
    opening TB.)"""
    from sqlalchemy import select
    from backend.app.models.database import ProposedJournal as PJ
    from backend.app.services.review.last_year import last_year_job
    last = last_year_job(engagement, db)
    if last is not None and last.period_end_date < engagement.period_end_date:
        out = []
        for j in db.execute(select(PJ).where(PJ.engagement_id == last.id, PJ.status == "APPROVED")).scalars():
            lines = [(int(l.account_code), float(l.debit or 0), float(l.credit or 0)) for l in (j.lines or [])] or                     [(int(j.debit_code), float(j.amount or 0), 0.0), (int(j.credit_code), 0.0, float(j.amount or 0))]
            out.append((j.journal_ref or str(j.id), lines))
        return out
    return []


def _group(code: int, chart: ChartLookup) -> Tuple[int, str]:
    """A fixed asset class's cost or its depreciation (codes in tens: cost, additions, disposals ... depreciation b/f,
    charge ...), told apart by the chart's names; any other balance is its own code."""
    if code in FIXED_ASSETS:
        name = chart.name(code, "").lower()
        return code // 10 * 10, "dep" if any(w in name for w in ("depreciation", "amortisation", "impairment")) else "cost"
    return code, ""


def _post_code(group: Tuple[int, str], chart: ChartLookup) -> int:
    """The code a class's difference is put right on: the class cost, or its depreciation brought forward."""
    base, part = group
    if part == "cost":
        return base
    if part == "dep":
        for c in range(base, base + 10):
            name = chart.name(c, "").lower()
            if c in chart.accounts and ("b/f" in name or "b/ fwd" in name or "bfwd" in name):
                return c
        return base + 3
    return base


def opening_points(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                   counter: List[int], materiality: float = 1000.0, table: Optional[Dict] = None
                   ) -> Tuple[List[AuditFinding], List[ProposedJournal], bool]:
    """(points, journals, compared): compared is False when there is nothing to compare with (no last year). table,
    when given, is filled with the comparison for the screen (a row per balance, and the reserve at the foot)."""
    from backend.app.services.bank_only.books import is_books_client
    from backend.app.services.sop.common import code_matcher, ledger_rows
    if is_books_client(engagement):
        return [], [], False            # their openings are last year's closing TB by construction
    source, last = last_year_closing(engagement, db)
    if not last:
        return [], [], False

    closing: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code is not None:
            closing[t.std_code] = closing.get(t.std_code, 0.0) + float(t.net_amount or 0.0)
    code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))
    movement: Dict[int, float] = {}
    rows = ledger_rows(str(engagement.id), db)
    for tx in rows:
        c = code_of(tx.raw_account_name)
        if c is not None:
            movement[c] = movement.get(c, 0.0) + float(tx.net_amount or 0.0)
    if not rows:
        # No ledger: the TB's opening column is the books' opening, when it has one
        opening = {}
        for t in tb_records:
            if t.std_code is not None and t.opening_amount is not None:
                opening[t.std_code] = opening.get(t.std_code, 0.0) + float(t.opening_amount or 0.0)
        if not opening:
            return [], [], False
    else:
        opening = {c: closing.get(c, 0.0) - movement.get(c, 0.0) for c in set(closing) | set(movement)}

    # The reserve brought forward (credit +): the books' against last year's closing reserve, with last year's
    # profit or loss when its TB was not closed off
    books_bf = -round(sum(opening.get(c, 0.0) for c in (RESERVE_BF, PRIOR_YEAR_ADJUSTMENT)), 2)
    ly_bf = -round(sum(v for c, v in last.items() if _is_reserve(c) or chart.is_pl(c)), 2)
    gap = round(books_bf - ly_bf, 2)

    diffs: Dict[Tuple[int, str], float] = {}
    for c in set(opening) | set(last):
        # Suspense and transfers are compared too: the client's software often parks the opening difference there
        if chart.is_pl(c) or _is_reserve(c) or c in STOCK:
            continue
        g = _group(c, chart)
        diffs[g] = diffs.get(g, 0.0) + opening.get(c, 0.0) - last.get(c, 0.0)
    diffs = {g: round(v, 2) for g, v in diffs.items() if abs(v) >= TOLERANCE}
    # Same money on another code: pairs that cancel
    left = dict(diffs)
    moved = []
    for g1, g2 in combinations(sorted(diffs), 2):
        if g1 in left and g2 in left and abs(left[g1] + left[g2]) <= TOLERANCE:
            moved.append((g1, g2, left.pop(g1), left.pop(g2)))
    explained = round(sum(left.values()), 2)
    # Balances of last year with no line at all this year (not in the TB, not in the ledger): an export can leave them
    # out, so when the others alone explain the reserve difference these are only noted
    absent = {g for g in left if not any(c in closing or c in movement for c in set(opening) | set(last)
                                         if _group(c, chart) == g)}
    left_out: Dict[Tuple[int, str], float] = {}
    if abs(explained - gap) > TOLERANCE and absent:
        without = round(sum(v for g, v in left.items() if g not in absent), 2)
        if without and abs(without - gap) <= TOLERANCE:
            left_out = {g: v for g, v in left.items() if g in absent}
            left = {g: v for g, v in left.items() if g not in absent}
            explained = without
            absent = set()

    def label(g: Tuple[int, str]) -> str:
        code = _post_code(g, chart)
        return f"{code} {chart.name(code, f'Account {code}')}"

    def opening_of(g):
        return round(sum(v for c, v in opening.items() if _group(c, chart) == g), 2)

    def last_of(g):
        return round(sum(v for c, v in last.items() if _group(c, chart) == g), 2)

    findings: List[AuditFinding] = []
    journals: List[ProposedJournal] = []
    severity = "HIGH" if abs(gap) >= materiality else "MEDIUM"
    from backend.app.services.review.payroll_journals import _journal_lines

    # Each difference matched to the journal of last year's that made it (last year's final WP, or last year's job in
    # the app): the client never posted that journal
    prior_journals = last_year_journals(engagement, db)

    def matched(g: Tuple[int, str], d: float) -> Optional[str]:
        for label, lines in prior_journals:
            net = sum(dr - cr for c, dr, cr in lines if _group(c, chart) == g)
            if abs(net) >= TOLERANCE and abs(net + d) <= TOLERANCE:
                return label
        return None

    matches = {g: m for g, d in left.items() if (m := matched(g, d))}

    def cause(g: Tuple[int, str]) -> str:
        if g in matches:
            return f" (last year's journal {matches[g]})"
        if g[0] in YEAR_END_ENTRIES and abs(opening_of(g)) < TOLERANCE:
            return " (last year's year-end entry not brought forward, or reversed in last year's books)"
        return ""

    def described(items) -> str:
        return "; ".join(f"{label(g)}: books {_money(opening_of(g))} v last year {_money(last_of(g))}{cause(g)}"
                         for g, _ in items)

    def to_last_year(groups: Dict[Tuple[int, str], float]) -> List[Tuple[int, float, float]]:
        """Each balance brought to last year's figure, against the reserve brought forward."""
        lines = []
        for g, d in sorted(groups.items()):
            lines.append((_post_code(g, chart), -d if d < 0 else 0.0, d if d > 0 else 0.0))
        total = round(sum(groups.values()), 2)
        lines.append((RESERVE_BF, total if total > 0 else 0.0, -total if total < 0 else 0.0))
        return lines

    def entry_of(lines) -> str:
        return "; ".join(f"{'Dr' if dr else 'Cr'} {c} {chart.name(c, f'Account {c}')} {_money(dr or cr)}"
                         for c, dr, cr in lines if dr or cr)

    books_said = f"{_money(books_bf)}{' (a loss)' if books_bf < 0 else ''}"
    last_said = f"{_money(ly_bf)}{' (a loss)' if ly_bf < 0 else ''}"
    # Differences over £1 (a pound is rounding)
    ties = abs(gap) > TOLERANCE and left and abs(explained - gap) <= TOLERANCE
    posted = left if ties else {g: left[g] for g in matches}
    if abs(gap) > TOLERANCE and posted:
        # Last year's adjustments not in the books: each balance to last year's figure, against reserves b/f
        lines = to_last_year(posted)
        entry = entry_of(lines)
        amount = round(sum(posted.values()), 2)
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-OB-001", procedure_name=NAME,
            severity=severity, source_row_ref="Opening balances",
            finding_title=f"Opening balances: {_money(amount)} of last year's year-end adjustments are not in the books"[:255],
            finding_details=(
                f"The profit and loss reserve brought forward is {books_said} in the books, but last year closed at "
                f"{last_said} ({source}). "
                + ("These balances open differently from last year's closing and together explain the whole difference: "
                   if ties else "These balances open differently from last year's closing by exactly a journal of last "
                                "year's that the client never posted: ")
                + f"{described(sorted(posted.items()))}. "
                + (f"Not in this year's books at all, so check them before approving: "
                   f"{', '.join(label(g) for g in sorted(absent & set(posted)))}. " if absent & set(posted) else "")
                + (f"Left as they are (last year's TB has them, this year's has no line for them; check the TB "
                   f"export): {described(sorted(left_out.items()))}. " if left_out else "")
                + f"A journal is proposed (Journals tab) bringing each balance to last year's figure against the reserve "
                  f"brought forward: {entry}."),
            quantified_amount=abs(amount), suggested_journal=entry[:2000], status="OPEN")
        journals.append(_journal_lines(engagement, counter, "Opening balances brought into line with last year's "
                                       "closing balances", lines, chart, f))
        findings.append(f)
    rest = round(gap - (explained if ties else sum(posted.values())), 2)
    if abs(gap) > TOLERANCE and abs(rest) > TOLERANCE:
        # Not explained by the balances: the accountant looks; no journal is guessed
        unexplained = {g: d for g, d in left.items() if g not in posted}
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-OB-002", procedure_name=NAME,
            severity="HIGH" if abs(rest) >= materiality else "MEDIUM", source_row_ref="Opening balances",
            finding_title=(f"Profit and loss reserve brought forward {_money(books_bf)}, last year closed at "
                           f"{_money(ly_bf)}: {_money(rest)} to explain")[:255],
            finding_details=(
                f"The books bring forward {books_said}; last year closed at {last_said} ({source}), a difference of "
                f"{_money(gap)}"
                + (f", of which {_money(gap - rest)} is last year's journals proposed above" if posted else "") + ". "
                + (f"Other balances opening differently from last year: {described(sorted(unexplained.items()))}. "
                   if unexplained else "Every other balance sheet balance opens at last year's figure. ")
                + f"{_money(rest)} is not explained: usually last year's income or costs posted in this year's books, a "
                  "journal posted straight to retained earnings, or last year's figures changed after they were "
                  "finished. Agree the reserve to last year's signed accounts and put the difference right; no journal "
                  "is proposed until the cause is known."),
            quantified_amount=abs(rest), status="OPEN"))
    # Last year's balances the client's software opened in suspense: the suspense opening equals the other
    # differences, so each balance goes back to last year's figure against suspense (opening = last year's closing;
    # nothing changes in the reserves)
    suspense = (SUSPENSE, "")
    others = {g: d for g, d in left.items() if g != suspense and g not in posted}
    if (suspense in left and abs(left[suspense]) >= TOLERANCE and others
            and abs(left[suspense] + sum(others.values())) <= TOLERANCE):
        lines = [(_post_code(g, chart), -d if d < 0 else 0.0, d if d > 0 else 0.0) for g, d in sorted(others.items())]
        d = left[suspense]
        lines.append((SUSPENSE, -d if d < 0 else 0.0, d if d > 0 else 0.0))
        entry = entry_of(lines)
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-OB-004", procedure_name=NAME,
            severity=severity if abs(d) >= materiality else "MEDIUM", source_row_ref="Opening balances",
            finding_title=f"Opening balances: {_money(abs(d))} of last year's balances opened in suspense"[:255],
            finding_details=(
                f"The books open with {_money(d)} in suspense, exactly what these balances of last year's ({source}) "
                f"are missing: {described(sorted(others.items()))}. The client's software parked last year's closing "
                f"balances there. A journal is proposed (Journals tab) bringing each one to last year's figure out of "
                f"suspense: {entry}."),
            quantified_amount=abs(d), suggested_journal=entry[:2000], status="OPEN")
        journals.append(_journal_lines(engagement, counter, "Last year's balances moved out of suspense", lines, chart, f))
        findings.append(f)
    # Remap, never a journal: when this year's code holds only last year's money (no
    # movement on it this year), its accounts take last year's code: the code the journal would have posted to (cost
    # to the class cost, depreciation to its brought forward), so the final balances are what the journal gave.
    # An account the accountant mapped by hand keeps its code (and the journal stays)
    remapped = []
    remapped_groups = set()
    for pair in list(moved):
        g1, g2, a, b = pair
        new, old = (g1, g2) if abs(last_of(g1)) < TOLERANCE and abs(last_of(g2)) >= TOLERANCE else \
            (g2, g1) if abs(last_of(g2)) < TOLERANCE and abs(last_of(g1)) >= TOLERANCE else (None, None)
        # Only a fixed asset class to another (cost to cost, depreciation to depreciation), and only with a ledger
        # to show the code had no movement; any other pair keeps the journal for the accountant to approve
        if new is None or not rows or not new[1] or new[1] != old[1]:
            continue
        codes = {c for c in set(closing) | set(movement) if _group(c, chart) == new}
        accounts = [t for t in tb_records if t.std_code in codes and abs(float(t.net_amount or 0)) >= 0.005]
        # The code the journal would have posted to (the class cost, or its depreciation brought forward)
        target = {id(t): _post_code(old, chart) for t in accounts}
        if (not accounts or any(abs(movement.get(c, 0.0)) >= 0.005 for c in codes)
                or any(t.match_source in ("MANUAL", "CONFIRMED") for t in accounts)
                or any(c not in chart.accounts or _group(c, chart) != old for c in target.values())):
            continue
        for t in accounts:
            t.std_code = target[id(t)]
            t.std_name = chart.name(t.std_code, t.std_name)
            t.match_source = "LAST_YEAR"
            t.mapping_reason = (f"Last year's code: last year's TB has this balance on {t.std_code} ({source}); it "
                                f"was mapped to another code, with no movement this year.")
        moved.remove(pair)
        remapped.append((label(new), label(old), abs(a)))
        remapped_groups.update((new, old))
    if remapped:
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-OB-003", procedure_name=NAME,
            severity="LOW", source_row_ref="Opening balances",
            finding_title=f"{len(remapped)} account(s) moved to last year's code"[:255],
            finding_details=("These accounts opened on another code than last year's closing TB and hold only last "
                             "year's balance, so they take last year's code (no journal): "
                             + "; ".join(f"{n} to {o} {_money(v)}" for n, o, v in remapped)
                             + f". Last year's figures: {source}."),
            quantified_amount=round(sum(v for _n, _o, v in remapped), 2), status="OPEN"))
    if moved and any(abs(a) >= 100 for _g1, _g2, a, _b in moved):
        # The same money on another code: a reclassification journal back to last year's code is proposed for each
        # pair. Only approved journals reach the ETB, and this year's code is often the
        # right one, so the accountant approves it only when last year's code is
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-OB-003", procedure_name=NAME,
            severity="LOW", source_row_ref="Opening balances",
            finding_title=f"{len(moved)} balance(s) open on a different code from last year's closing"[:255],
            finding_details=(
                "The same amount sits on another code this year (no effect on the reserves): "
                + "; ".join(f"{label(g1)} {_money(a)} and {label(g2)} {_money(b)}" for g1, g2, a, b in moved)
                + f". Last year's figures: {source}. A journal back to last year's code is proposed for each (Journals "
                  "tab): approve it only if last year's code is the right one (a change of code changes last year's "
                  "comparatives in the accounts)."),
            quantified_amount=round(sum(abs(a) for _g1, _g2, a, _b in moved), 2), status="OPEN")
        findings.append(f)
        for g1, g2, a, b in moved:
            if abs(a) < 100:
                continue
            lines = [(_post_code(g, chart), -d if d < 0 else 0.0, d if d > 0 else 0.0) for g, d in ((g1, a), (g2, b))]
            journals.append(_journal_lines(engagement, counter, f"Opening on another code: back to last year's code "
                                           f"({label(g1)} / {label(g2)})"[:200], lines, chart, f))
    if table is not None:
        moved_groups = {g for g1, g2, _a, _b in moved for g in (g1, g2)}
        rows = []
        for g in sorted({_group(c, chart) for c in set(opening) | set(last)
                         if not (chart.is_pl(c) or _is_reserve(c))}):
            o, l = opening_of(g), last_of(g)
            if abs(o) < TOLERANCE and abs(l) < TOLERANCE:
                continue
            d = round(o - l, 2)
            if abs(d) < TOLERANCE:
                why = "Agrees"
            elif g[0] in STOCK:
                why = "Stock: see the stock point"
            elif g in matches:
                why = f"Last year's journal {matches[g]}, not in the books"
            elif g in moved_groups:
                why = "Same amount on another code"
            elif g in remapped_groups:
                why = "Moved to last year's code"
            elif g in left_out:
                why = "Not in this year's TB (left as it is)"
            elif g in posted:
                why = "Last year's adjustment, not in the books"
            elif g[0] in YEAR_END_ENTRIES and abs(o) < TOLERANCE:
                why = "Year-end entry not brought forward"
            else:
                why = "Not explained"
            rows.append({"code": _post_code(g, chart), "name": label(g), "books": o, "last_year": l, "difference": d,
                         "cause": why})
        table.update({"source": source, "rows": rows, "books_bf": books_bf, "last_year_bf": ly_bf, "gap": gap,
                      "explained": round(gap - rest, 2) if abs(gap) > TOLERANCE else 0.0})
    # Last year's codes the firm chart does not have, opened on their parent code: shown to confirm, not guessed
    # silently (a 5501 loan may belong on 5351 rather than 5500)
    from backend.app.services.review.last_year_read import codes_not_in_chart
    missing = codes_not_in_chart(engagement, db)
    if missing:
        listed = "; ".join(f"{code} {name} £{abs(amount):,.2f} opened on {used} {chart.name(used, '')}".strip()
                           for name, code, used, amount in missing[:10])
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-OB-005", procedure_name=NAME,
            severity="MEDIUM", source_row_ref="Opening balances",
            finding_title=f"{len(missing)} code(s) in last year's TB not in the chart: opened on their parent code"[:255],
            finding_details=(f"Last year's TB uses codes the firm chart does not have, so each opened on the parent code "
                             f"in its ten: {listed}. Check each is the right code (a loan can belong under other loans, "
                             f"5351, rather than bank loans); change the account's code on the Mapping tab if not, and "
                             f"the opening follows."),
            quantified_amount=round(sum(abs(a) for *_x, a in missing), 2), status="OPEN"))
    return findings, journals, True


def reserves_moved(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                   materiality: float = 1000.0) -> List[AuditFinding]:
    """Reserves brought forward (8000, 8030) are last year's closing reserve and do not move during the year (FRS
    102 10.21: an error in last year's figures restates the opening reserve, it is not
    posted in the year). A movement means something was posted to them this year (dividends, last year's profit,
    an adjustment), so the job stops at a point for the accountant; nothing is moved automatically."""
    from backend.app.services.bank_only.books import is_books_client
    from backend.app.services.sop.common import code_matcher, ledger_rows
    if is_books_client(engagement):
        return []
    codes = (RESERVE_BF, PRIOR_YEAR_ADJUSTMENT)
    by_account: Dict[str, float] = {}
    movement_tb = any(t.opening_amount is not None for t in tb_records)
    if movement_tb:
        # The TB holds this year's movements (net = opening + movement)
        for t in tb_records:
            if t.std_code in codes and t.opening_amount is not None:
                mv = round(float(t.net_amount or 0) - float(t.opening_amount or 0), 2)
                if abs(mv) >= TOLERANCE:
                    by_account[t.raw_account_name] = by_account.get(t.raw_account_name, 0.0) + mv
    else:
        code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))
        for tx in ledger_rows(str(engagement.id), db):
            if code_of(tx.raw_account_name) in codes:
                by_account[tx.raw_account_name] = by_account.get(tx.raw_account_name, 0.0) + float(tx.net_amount or 0)
    by_account = {a: round(v, 2) for a, v in by_account.items() if abs(v) >= TOLERANCE}
    moved = round(sum(by_account.values()), 2)
    if abs(moved) < TOLERANCE:
        return []
    listing = "; ".join(f"{a} {'Dr' if v > 0 else 'Cr'} {_money(v)}" for a, v in sorted(by_account.items()))
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-OB-003", procedure_name=NAME,
        severity="HIGH" if abs(moved) >= materiality else "MEDIUM",
        source_row_ref=f"{RESERVE_BF} {chart.name(RESERVE_BF, 'Reserves brought forward')}"[:100],
        finding_title=f"Reserves brought forward moved in the year by {_money(moved)}"[:255],
        finding_details=(f"Reserves brought forward must equal last year's closing reserve and do not move during the "
                         f"year, but {_money(moved)} was posted to them this year: {listing}. Find what these postings "
                         f"are (dividends, last year's profit closed off again, an adjustment) and code them to where "
                         f"they belong before the accounts are finished (a correction of "
                         f"last year's figures restates the opening reserve, FRS 102 10.21)."),
        quantified_amount=abs(moved), status="OPEN")]
