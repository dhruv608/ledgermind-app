"""
Capital items in the P&L moved to fixed assets when there is no asset register (otherwise bank payments for assets
are never capitalised, and with no FAR there are no fixed assets or depreciation at all).

The Revenue vs Capital SOP flags P&L costs of at least the capitalisation limit whose description names an asset
(laptop, van, CCTV installation, office desk ...). When the words point to one asset class, the review proposes a
journal moving the cost to that class's additions (Dr additions / Cr the cost), so the depreciation that follows and
the capital allowances see it as a fixed asset. A flag matched only on the supplier's name, or with no class, stays
a question for the client. With an asset register, the register decides instead (yearend_journals.far_additions_in_pl).
Each journal is proposed, never posted: the accountant approves or rejects it.
"""

from typing import Dict, List, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, MasterCOA, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.setup_checks import ASSET_CLASS_CODES
from backend.app.services.sop.capital import RUNNING_ACCOUNTS
from backend.app.services.review.yearend_journals import _entry, _journal, _point

ADDITIONS = {codes["cost"][1]: cls for cls, codes in ASSET_CLASS_CODES.items()}     # 4101 -> Freehold property ...
# Costs a journal never moves (the flag stays a question): cost of sales and employee costs (a furniture shop's
# furniture is its stock), and accounts for hiring or running assets (CCTV towers rented, vehicle tax)
NOT_MOVED_CATEGORIES = ("Cost of sales", "Employee costs")
NOT_MOVED_NAMES = RUNNING_ACCOUNTS    # P&L accounts for running vehicles (not flagged at all)
# Client accounts for software, subscriptions or rebilled tools: a licence or a plan is a cost and stays in the P&L
import re as _re
SOFTWARE_ACCOUNT = _re.compile(r"\b(software|subscriptions?|licen[cs]es?|saas|cloud|hosting|rebillable|apps?)\b", _re.I)
# Work on a building that can be a repair or an improvement (a new roof, a refurbishment): the accountant decides
# (PIM2025 / BIM35435: replacing parts is a repair, an improvement is capital), never a journal
REPAIR_OR_IMPROVEMENT = _re.compile(r"\b(roof\w*|refurbish\w*|renovat\w*|moderni[sz]\w*|redecorat\w*|fit[- ]?out|"
                                    r"repairs?)\b", _re.I)


def g1_key(f: AuditFinding) -> Tuple[str, float]:
    """How a Revenue vs Capital point (G1) is matched to the journal that replaces it."""
    return (f.source_row_ref or "", round(float(f.quantified_amount or 0), 2))


def capital_journals(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                     counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal], Dict[int, float],
                                                  Set[Tuple[str, float]]]:
    """The proposed journals and their points, the change they make to each code (so the depreciation sees the
    additions), and the G1 points they replace (g1_key)."""
    from backend.app.services.sop.capital import capital_review, capitalisation_limit
    approved = {((j.description or "").strip(), round(float(j.amount or 0), 2)) for j in db.query(ProposedJournal).filter(
        ProposedJournal.engagement_id == engagement.id, ProposedJournal.status == "APPROVED")}
    findings: List[AuditFinding] = []
    journals: List[ProposedJournal] = []
    moved: Dict[int, float] = {}
    replaced: Set[Tuple[str, float]] = set()
    limit = capitalisation_limit(engagement)
    coa = {c.std_code: c for c in db.query(MasterCOA)}
    for f in capital_review(str(engagement.id), tb_records, db, limit):
        replaced_key = (f"{f.when:%d/%m/%Y} {f.account}"[:100], round(f.amount, 2))
        # The client's own account naming the asset ('Computer Hardware', 'Photography Equipment') when the line names
        # only the shop (keyword + one-off + over the limit = a proposed journal); software and subscription accounts
        # stay questions
        by_account = (f.by_account and f.one_off and not SOFTWARE_ACCOUNT.search(f.account or ""))
        if (f.supplier_only and not by_account) or f.suggested_code not in ADDITIONS:
            continue
        # Score: keyword 0.4 + supplier 0.2 + one-off 0.2 + amount band 0.2, a journal from 0.7 (the amount is over
        # the limit already): a keyword needs a one-off purchase or a known asset supplier as well (a keyword alone
        # stays a question)
        from backend.app.services.sop.capital import _SUPPLIER_PATTERN
        if not by_account and not (f.one_off or _SUPPLIER_PATTERN.search(f.description or "")):
            continue
        if REPAIR_OR_IMPROVEMENT.search(f.description or ""):
            continue
        cost = coa.get(f.code)
        if cost is None or cost.category in NOT_MOVED_CATEGORIES or NOT_MOVED_NAMES.search(cost.std_name or ""):
            continue
        cls = ADDITIONS[f.suggested_code]
        text = f"Capital item moved from the P&L: {f.description[:150]}"[:255]
        replaced.add(replaced_key)
        if (text.strip(), round(f.amount, 2)) in approved:
            continue
        approved.add((text.strip(), round(f.amount, 2)))
        entry = _entry(f.suggested_code, f.code, f.amount, chart)
        details = (f"'{f.description[:150]}' on {f.when:%d/%m/%Y}, £{f.amount:,.2f} in {f.code} {chart.name(f.code, '')}, "
                   f"names an asset ({', '.join(f.keywords)}) and is at least the capitalisation limit of £{limit:,.0f}. "
                   f"An item lasting more than a year is a fixed asset: it is moved to {cls.lower()} additions, so it is "
                   f"depreciated and gets capital allowances (AIA) instead of being a P&L expense. A journal is proposed "
                   f"(Journals tab): {entry}. Reject it if this was a repair or a running cost.")
        point = _point(engagement, "U-FA-008", f"Capital item in the P&L: {cls.lower()}",
                       f"£{f.amount:,.2f} in {chart.name(f.code, str(f.code))} looks like a fixed asset: "
                       f"{f.description[:60]}", details, f.amount, entry)
        findings.append(point)
        journals.append(_journal(engagement, counter, text, f.suggested_code, f.code, f.amount, chart, point))
        moved[f.suggested_code] = round(moved.get(f.suggested_code, 0.0) + f.amount, 2)
        moved[f.code] = round(moved.get(f.code, 0.0) - f.amount, 2)
    return findings, journals, moved, replaced


def register_request(engagement: ClientEngagement, tb_records: List[TBRecord],
                     after: Dict[int, float]) -> List[AuditFinding]:
    """Fixed assets brought forward with no asset register: the register (or this year's additions and disposals)
    is asked for, since the depreciation is otherwise taken from the totals at the default rates."""
    cost_codes = {c for codes in ASSET_CLASS_CODES.values() for c in codes["cost"]}
    brought = round(sum(float(t.opening_amount or 0) for t in tb_records if t.std_code in cost_codes), 2)
    if brought < 1.0:
        return []
    held = sorted(cls for cls, codes in ASSET_CLASS_CODES.items()
                  if abs(sum(after.get(c, 0.0) for c in codes["cost"])) >= 1.0)
    return [AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-FA-009",
        procedure_name="Fixed assets: asset register", severity="LOW", source_row_ref="Fixed assets",
        finding_title=f"Fixed assets brought forward £{brought:,.2f} but no asset register",
        finding_details=(f"Last year's accounts carry fixed assets at cost of £{brought:,.2f}"
                         + (f" ({', '.join(held).lower()})" if held else "") + ". No asset register was uploaded, so "
                         "the depreciation is worked out on the totals at the rates in the setup. Client question: "
                         "please send the fixed asset register, or a list of the assets bought and sold this year "
                         "with their dates and costs."),
        quantified_amount=brought, suggested_journal=None, status="OPEN")]


# Revenue items posted to fixed asset codes (repairs, servicing, subscriptions ...: BIM35430, a
# repair or a running cost is never capital)
REVENUE_IN_ASSETS = _re.compile(r"\b(repairs?|servic(e|ing)|maintenance|mot|subscriptions?|monthly|annual fee|"
                                r"licen[cs]e renewal|renewal|hosting|insurance|rent|fuel|training)\b", _re.I)


def _revenue_target(cost_code: int, text: str) -> int:
    """Where a revenue item on an asset code belongs."""
    if cost_code in (4130, 4131):
        return 3234                                          # vehicle repairs
    if cost_code in (4150, 4151):
        return 3240 if _re.search(r"subscription|licen[cs]e|hosting|renewal|software", text, _re.I) else 3243
    return 3250                                              # repairs, renewals and maintenance


def revenue_in_assets(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                      counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal], Dict[int, float]]:
    """Lines on fixed asset cost / additions codes that read as a revenue cost, scored: keyword
    0.4, recurring (the same contact in 3 or more months) 0.2, amount over 5 times the client's median expense line
    0.2. From 0.7 a proposed journal back to the P&L (Dr the cost, Cr the additions code); 0.4 to 0.7 a client query."""
    from statistics import median
    from backend.app.services.sop.common import gl_lines, supplier_name
    asset_codes = {c for codes in ASSET_CLASS_CODES.values() for c in codes["cost"][:2]}
    lines = gl_lines(str(engagement.id), tb_records, db)
    expenses = [l.debit for l in lines if l.debit > 0 and l.code < 4000]
    big = 5 * median(expenses) if expenses else float("inf")
    on_assets = [l for l in lines if l.code in asset_codes and l.debit > 0 and REVENUE_IN_ASSETS.search(l.description or "")]
    months: Dict[str, Set[Tuple[int, int]]] = {}
    for l in on_assets:
        months.setdefault(supplier_name(l.description or ""), set()).add((l.when.year, l.when.month))
    findings: List[AuditFinding] = []
    journals: List[ProposedJournal] = []
    moved: Dict[int, float] = {}
    questions: Dict[Tuple[str, int], list] = {}
    for l in on_assets:
        recurring = len(months.get(supplier_name(l.description or ""), ())) >= 3
        score = 0.4 + (0.2 if recurring else 0.0) + (0.2 if l.debit > big else 0.0)
        target = _revenue_target(l.code, l.description or "")
        entry = _entry(target, l.code, l.debit, chart)
        details = (f"'{(l.description or '')[:150]}' on {l.when:%d/%m/%Y}, £{l.debit:,.2f} on {l.code} "
                   f"{chart.name(l.code, '')}, reads as a running cost or repair"
                   f"{', paid in 3 or more months' if recurring else ''}, not an asset (a repair or running cost is "
                   f"never capital, BIM35430): it belongs in the P&L ({entry}).")
        if score >= 0.7:
            point = _point(engagement, "U-FA-011", "Revenue cost in fixed assets",
                           f"£{l.debit:,.2f} on {chart.name(l.code, str(l.code))} looks like a running cost: "
                           f"{(l.description or '')[:60]}", details + " A journal is proposed (Journals tab).", l.debit, entry)
            findings.append(point)
            journals.append(_journal(engagement, counter, f"Revenue cost moved out of fixed assets: "
                                     f"{(l.description or '')[:150]}"[:255], target, l.code, l.debit, chart, point))
            moved[target] = round(moved.get(target, 0.0) + l.debit, 2)
            moved[l.code] = round(moved.get(l.code, 0.0) - l.debit, 2)
        else:
            questions.setdefault((supplier_name(l.description or ""), l.code), []).append((l, details, entry))
    # One question per supplier and code, its lines listed (a monthly service plan is one question, not twelve)
    for (_supplier, code), items in questions.items():
        total = round(sum(l.debit for l, _d, _e in items), 2)
        first = items[0][0]
        listed = "; ".join(f"{l.when:%d/%m/%Y} £{l.debit:,.2f}" for l, _d, _e in items[:12])
        target = _revenue_target(code, first.description or "")
        findings.append(_point(engagement, "U-FA-011", "Revenue cost in fixed assets? (client query)",
                               f"£{total:,.2f} on {chart.name(code, str(code))}: {(first.description or '')[:60]}"
                               f"{f' ({len(items)} payments)' if len(items) > 1 else ''}",
                               items[0][1] + (f" The payments: {listed}." if len(items) > 1 else "")
                               + " Please send the invoice so we can confirm what it is.", total,
                               _entry(target, code, total, chart)))
    return findings, journals, moved
