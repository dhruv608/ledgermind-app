"""U-FA-020: a fixed asset account of the year that holds both sides: the client keeps one 'Motor Vehicles' account for
cars bought (debits) and cars sold (credits), and one 'Motor Vehicles Depreciation' account for the year's charge
(credits) and the depreciation taken out on the cars sold (debits). Its code puts the net on one line, so the fixed
asset note shows additions net of disposals, or depreciation net of what was disposed of.

The note must show additions, disposals and depreciation separately for each class (FRS 102 1AD.13, Schedule 3A para
45; FA-007: on disposal the cost and the accumulated depreciation both come out), and the tax computation works the
disposal value from the disposal codes (CAA 2001 s61). So each side goes to its own code: cost debits to additions,
cost credits to disposals; depreciation credits to the charge, debits to depreciation on disposals. A presentation
journal, proposed: profit, the class's cost and its depreciation do not change."""

import re
from collections import defaultdict
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.setup_checks import ASSET_CLASS_CODES
from backend.app.services.review.yearend_journals import _entry, _journal, _point

MIN_AMOUNT = 100.0
OPENING = ("opening balance", "balance b/f", "balance brought forward")
# A line that takes an asset out: only these count as disposals (a credit on a cost account can be a refund, or an
# employee repaying a phone, which stays an addition)
DISPOSAL_LINE = re.compile(r"dispos|\bsold\b|\bsale of\b|scrapp|write[- ]?off|written[- ]?off|part[- ]?exchange|"
                           r"insurance (?:pay ?out|claim|settlement)|total loss", re.I)


def _sides() -> Dict[int, Tuple[str, int, int, str]]:
    """{code: (class, the code for debits, the code for credits, 'cost' or 'depreciation')} for each class's in-year
    codes: additions / disposals (cost) and charge / depreciation on disposals."""
    out = {}
    for cls, codes in ASSET_CLASS_CODES.items():
        additions, disposals = codes["cost"][1], codes["cost"][2]
        charge, on_disposals = codes["acc"][1], codes["acc"][2]
        for c in (additions, disposals):
            out[c] = (cls, additions, disposals, "cost")
        for c in (charge, on_disposals):
            out[c] = (cls, on_disposals, charge, "depreciation")
    return out


def disposal_split(engagement: ClientEngagement, tb_records: List[TBRecord], chart: ChartLookup, db: Session,
                   counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.sop.common import gl_lines
    sides = _sides()
    totals: Dict[Tuple[str, int], List[float]] = defaultdict(lambda: [0.0, 0.0])
    start = engagement.prior_period_end_date
    by_account: Dict[Tuple[str, int], list] = defaultdict(list)
    for g in gl_lines(engagement.id, tb_records, db):
        if g.code not in sides or any(w in (g.description or "").lower() for w in OPENING):
            continue
        if start is not None and g.when <= start:
            continue
        by_account[(g.account, g.code)].append(g)
    kept = []
    for lines in by_account.values():
        # A line and its own reversal (the same amount the other way, in the same account) are no addition and no
        # disposal (e.g. a disposal journal cleared again in the same year)
        debits = [g for g in lines if g.debit and not g.credit]
        credits = [g for g in lines if g.credit and not g.debit]
        for d in list(debits):
            match = next((c for c in credits if abs(c.credit - d.debit) < 0.005), None)
            if match is not None:
                debits.remove(d)
                credits.remove(match)
        kept += debits + credits
    for g in kept:
        cls, dr_code, cr_code, kind = sides[g.code]
        t = totals[(g.account, g.code)]
        # Cost credits and depreciation debits are disposals only when the line says so; purchases on a disposals code
        # and charges on a depreciation-on-disposals code always move
        out_side = g.credit if kind == "cost" else g.debit
        if out_side and not DISPOSAL_LINE.search(g.description or ""):
            out_side = 0.0
        t[0] += g.debit if kind == "cost" else out_side
        t[1] += out_side if kind == "cost" else g.credit
    findings, journals = [], []
    for (account, code), (debits, credits) in sorted(totals.items()):
        cls, dr_code, cr_code, kind = sides[code]
        # The side that is on the wrong code: debits on the credits' code, or credits on the debits' code
        amount = round(debits if code == cr_code else credits, 2)
        if amount < MIN_AMOUNT:
            continue
        entry = _entry(dr_code, cr_code, amount, chart)
        if kind == "cost":
            what = (f"£{debits:,.2f} bought (additions) and £{credits:,.2f} sold or scrapped (disposals)")
            title = f"{cls}: additions and disposals on one account, '{account}'"
        else:
            what = (f"£{credits:,.2f} charged for the year and £{debits:,.2f} taken out on assets disposed of")
            title = f"{cls}: depreciation charge and depreciation on disposals on one account, '{account}'"
        f = _point(engagement, "U-FA-020", "Fixed assets: additions and disposals shown separately", title,
                   f"The ledger account '{account}' ({code} {chart.name(code)}) holds {what}, all on one code. The "
                   f"fixed asset note shows additions, disposals and depreciation separately for each class (FRS 102 "
                   f"1AD.13), and the capital allowances take the disposal from the disposal codes (CAA 2001 s61). A "
                   f"journal moves £{amount:,.2f} to its own code (Journals tab): {entry}. Profit and the class's "
                   f"totals do not change.", amount, entry, severity="LOW")
        findings.append(f)
        journals.append(_journal(engagement, counter, f"{cls}: {kind} disposals shown separately ({account})"[:255],
                                 dr_code, cr_code, amount, chart, f))
    return findings, journals
