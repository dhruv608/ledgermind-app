"""The fixed asset register against the books, class by class, and register additions found expensed in the P&L
(moved to fixed assets by journal)."""

import re
from typing import Dict, List, Optional, Tuple

from backend.app.models.database import AuditFinding, ClientEngagement, FixedAssetRecord, ProposedJournal
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.setup_checks import ASSET_CLASS_CODES, INTANGIBLE_CLASS_CODES
from backend.app.services.review.yearend_journals.common import MIN_AMOUNT, _entry, _journal, _point
from backend.app.services.review.yearend_journals.depreciation import _far_class

def far_books_check(engagement: ClientEngagement, far: List[FixedAssetRecord], after: Dict[int, float],
                    already: List[AuditFinding], merged: Optional[Dict[str, str]] = None) -> List[AuditFinding]:
    """The asset register against the books, class by class (an accountant ties the FAR to the TB before anything
    else): cost carried forward, this year's additions and disposals, and depreciation brought forward, plus the net
    book value once this year's register depreciation is in. One point per class that does not agree; classes the
    books hold that the register does not list; and a single 'agrees' point when everything ties. A class already
    raised as 'in the register, not in the books' (U-FA-006) is not raised again. Intangibles (goodwill and the rest)
    are checked the same way, on their own codes."""
    classes = {**ASSET_CLASS_CODES, **INTANGIBLE_CLASS_CODES}
    held = {cls: sum(abs(after.get(c, 0.0)) for c in codes["cost"]) for cls, codes in classes.items()}
    register: Dict[str, Dict[str, float]] = {}
    unplaced: Dict[str, float] = {}
    for a in far:
        cls = _far_class(a.category, held, merged)
        if cls is None:
            unplaced[a.category or "Fixed assets"] = unplaced.get(a.category or "Fixed assets", 0.0) + float(a.nbv or 0)
            continue
        r = register.setdefault(cls, {k: 0.0 for k in ("cost", "additions", "disposals", "dep_bf", "charge", "nbv")})
        cost_fwd = float(a.cost_fwd or 0) or (float(a.cost_bwd or 0) + float(a.additions or 0) - float(a.disposals or 0))
        r["cost"] += cost_fwd
        r["additions"] += float(a.additions or 0)
        r["disposals"] += float(a.disposals or 0)
        # Depreciation b/f from the register's own roll-forward (c/f - charge + disposals) when it has a c/f: a
        # register headed 'Opening | ... | B/Fwd' can leave the b/f column unread
        dep_fwd = float(a.depr_fwd or 0)
        r["dep_bf"] += (dep_fwd - float(a.depr_charge or 0) + float(a.depr_disposals or 0)) if dep_fwd else float(a.depr_bwd or 0)
        r["charge"] += float(a.depr_charge or 0)
        r["nbv"] += float(a.nbv or 0)
    raised = {f.finding_title.split(":")[0] for f in already if f.procedure_ref == "U-FA-006"}
    findings: List[AuditFinding] = []
    agreed = []
    for cls, codes in classes.items():
        reg = register.get(cls)
        cost, add, disp, _reval = (after.get(c, 0.0) for c in codes["cost"])
        books = {"cost": round(cost + add + disp + _reval, 2), "additions": round(add, 2), "disposals": round(-disp, 2),
                 "dep_bf": round(-after.get(codes["acc"][0], 0.0), 2)}
        if reg is None:
            if books["cost"] >= MIN_AMOUNT:
                findings.append(_point(
                    engagement, "U-FAR-002", f"Fixed asset register: {cls.lower()} v books",
                    f"{cls}: £{books['cost']:,.2f} in the books, nothing in the asset register",
                    f"The books hold {cls.lower()} costing £{books['cost']:,.2f}, but the fixed asset register lists none, "
                    f"so their depreciation is not worked out from the register. Client question: Please update the "
                    f"fixed asset register with these assets (or confirm they were sold or written off).",
                    books["cost"], "", severity="HIGH" if books["cost"] >= 1000 else "MEDIUM"))
            continue
        if cls in raised:
            continue
        nbv_after = round(books["cost"] - books["dep_bf"] - reg["charge"], 2)
        lines = [("Cost carried forward", reg["cost"], books["cost"]), ("Additions this year", reg["additions"], books["additions"]),
                 ("Disposals this year", reg["disposals"], books["disposals"]),
                 ("Depreciation brought forward", reg["dep_bf"], books["dep_bf"])]
        wrong = [(label, round(rv, 2), bv) for label, rv, bv in lines if abs(rv - bv) >= MIN_AMOUNT]
        if not wrong:
            agreed.append(cls)
            continue
        biggest = max(abs(rv - bv) for _, rv, bv in wrong)
        table = "; ".join(f"{label}: register £{rv:,.2f}, books £{bv:,.2f} (difference £{rv - bv:,.2f})"
                          for label, rv, bv in wrong)
        findings.append(_point(
            engagement, "U-FAR-002", f"Fixed asset register: {cls.lower()} v books",
            f"{cls}: the asset register and the books differ (largest £{biggest:,.2f})",
            f"The fixed asset register and the books do not agree for {cls.lower()}. {table}. Net book value after this "
            f"year's depreciation: register £{reg['nbv']:,.2f}, books £{nbv_after:,.2f}. Find the difference before "
            f"the depreciation is relied on: an addition posted to the P&L or not yet in the register, a disposal not "
            f"recorded, or last year's closing figures not carried into this year. Client question: Please confirm the "
            f"fixed asset additions and disposals for the year.",
            biggest, "", severity="HIGH" if biggest >= 1000 else "MEDIUM"))
        from backend.app.services.review.point_figures import row as _row, table as _table
        findings[-1].figures = _table(["", "Register", "Books", "Difference"],
                                      [_row(label, rv, bv, rv - bv, strong=(label, round(rv, 2), bv) in wrong)
                                       for label, rv, bv in lines]
                                      + [_row("Net book value after this year's depreciation", reg["nbv"], nbv_after,
                                              reg["nbv"] - nbv_after)])
    for category, nbv in unplaced.items():
        findings.append(_point(
            engagement, "U-FAR-002", "Fixed asset register: class not recognised",
            f"Register heading '{category}' is not matched to an asset class (NBV £{nbv:,.2f})",
            f"The register's heading '{category}' does not say which asset class it is (plant, vehicles, fixtures, "
            f"computers or property), so it is left out of the depreciation and the register / books check. Rename the "
            f"heading in the register, or check these assets by hand.", abs(nbv), "", severity="MEDIUM"))
    if agreed and not any(f.procedure_ref == "U-FAR-002" for f in findings) and not raised:
        findings.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-FAR-002",
            procedure_name="Fixed asset register v books", severity="LOW", source_row_ref="Fixed asset register",
            finding_title=f"Fixed asset register agrees to the books ({', '.join(c.lower() for c in agreed)})",
            finding_details="Cost, additions, disposals and depreciation brought forward agree between the register "
                            "and the books for every asset class.", quantified_amount=0.0, status="OPEN"))
    return findings


# ---------------------------------------------------------------------------------------------------------------
# Capital items left in the P&L, found from the asset register and moved to fixed assets by journal
# ---------------------------------------------------------------------------------------------------------------
CAPITAL_MATCH_TOLERANCE = 1.0
CAPITAL_MATCH_DAYS = 45
NOT_CAPITAL_PL = re.compile(r"depreciation|amortisation|wages|salar|pension|national insurance|corporation tax|"
                            r"interest|dividend|sales|turnover|bank charges", re.I)


def far_additions_in_pl(engagement: ClientEngagement, far: List[FixedAssetRecord], after: Dict[int, float],
                        lines: list, chart: ChartLookup, counter: List[int], merged: Optional[Dict[str, str]] = None
                        ) -> Tuple[List[AuditFinding], List[ProposedJournal], Dict[int, float]]:
    """Each addition in the register that the books' additions accounts do not hold, looked for among this year's
    P&L expense lines: the same amount (to £1) within 45 days of the register's date (any date when it has none).
    A match is a capital item expensed: a point and the journal Dr the class's additions / Cr that expense account.
    Works on amounts and dates, so a line with no asset words (only a supplier's name) is still found.
    Returns the points, the journals, and the balance changes they make (for the depreciation and register checks
    that run after it)."""
    held = {cls: sum(abs(after.get(c, 0.0)) for c in codes["cost"]) for cls, codes in ASSET_CLASS_CODES.items()}
    adds = [a for a in far if float(a.additions or 0) >= MIN_AMOUNT]
    if not adds:
        return [], [], {}
    # The additions the books already hold, per class: the register's additions up to that amount need no search
    by_class: Dict[str, List[FixedAssetRecord]] = {}
    for a in adds:
        cls = _far_class(a.category, held, merged)
        if cls is not None and cls in ASSET_CLASS_CODES:
            by_class.setdefault(cls, []).append(a)
    candidates = [l for l in lines if l.debit >= MIN_AMOUNT and chart.is_pl(l.code) and not chart.is_sales(l.code)
                  and not chart.is_depreciation(l.code) and not NOT_CAPITAL_PL.search(chart.name(l.code, ""))]
    used = set()
    findings, journals, moved = [], [], {}
    for cls, items in by_class.items():
        codes = ASSET_CLASS_CODES[cls]
        add_code = codes["cost"][1]
        in_books = round(after.get(add_code, 0.0), 2)
        missing = round(sum(float(a.additions) for a in items) - in_books, 2)
        if missing < MIN_AMOUNT:
            continue
        for a in sorted(items, key=lambda a: -float(a.additions)):
            if missing < MIN_AMOUNT:
                break
            amount = round(float(a.additions), 2)
            if amount > missing + CAPITAL_MATCH_TOLERANCE:
                continue
            when = a.acquisition_date
            hit = None
            for i, l in enumerate(candidates):
                if i in used or abs(l.debit - amount) > CAPITAL_MATCH_TOLERANCE:
                    continue
                if when and l.when and abs((l.when - when).days) > CAPITAL_MATCH_DAYS:
                    continue
                hit = i
                break
            if hit is None:
                continue
            used.add(hit)
            l = candidates[hit]
            value = round(l.debit, 2)
            missing = round(missing - value, 2)
            entry = _entry(add_code, l.code, value, chart)
            bought = f"bought {when:%d/%m/%Y} " if when else ""
            posted = f"{l.when:%d/%m/%Y} " if l.when else ""
            details = (f"The fixed asset register lists '{a.description}' {bought}for £{amount:,.2f}. The books "
                       f"expensed it: {posted}'{(l.description or '')[:80]}' £{value:,.2f} in {l.code} "
                       f"{chart.name(l.code, '')}. It is moved to {cls.lower()} additions, so it is depreciated and gets "
                       f"capital allowances (AIA) instead of being a P&L expense. A journal is proposed (Journals tab): "
                       f"{entry}.")
            f = _point(engagement, "U-FA-007", f"Capital item in the P&L: {cls.lower()}",
                       f"£{value:,.2f} in {chart.name(l.code, str(l.code))} is a fixed asset in the register: "
                       f"{(a.description or '')[:60]}", details, value, entry)
            findings.append(f)
            journals.append(_journal(engagement, counter, f"Capital item moved from the P&L: {(a.description or cls)[:80]}",
                                     add_code, l.code, value, chart, f))
            moved[add_code] = round(moved.get(add_code, 0.0) + value, 2)
            moved[l.code] = round(moved.get(l.code, 0.0) - value, 2)
    return findings, journals, moved
