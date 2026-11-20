"""
Review points from the LedgerMind FRS 102 rulebook that the other checks do not make, worked out from the final
balances (TB plus approved journals) and the ledger. Each point's ref is the rule's number ("FRS-F-004"). The
framework check runs on every job; the others only when the job is FRS 102 (1A or full), since FRS 105 has its own
rules (e.g. investment property at cost, depreciated).

  F-002   the framework chosen does not fit the company's size (FRS 105 over the micro limits, 1A over the small limits)
  F-004   no debtors, creditors, accruals or prepayments at the year end: the books look cash basis
  F-006   a bank account in credit (an overdraft, shown under creditors) or a debit on trade creditors (not netted)
  E-004   the profit and loss reserve brought forward is not last year's closing reserve (a prior-period error?)
  IN-004  goodwill or other intangibles with no amortisation this year
  IP-002  investment property depreciated (FRS 102 holds it at fair value, not depreciated)
  Q-005   a director's or shareholder's loan written off to income (a capital contribution, to equity)
  FA-007  the sale of a fixed asset coded to sales
  L-001   periods from 1 January 2026: the new lease rules bring leases onto the balance sheet
Already made by other checks, so not here: going concern (U-GC-001), dividends over the reserves (U-EQ-001), old
debtors (U-DEB-002), depreciation (U-FA-004), capital items in the P&L (U-FA-008), big changes on last year, payroll,
the director's loan and s455.
"""

import re
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, MasterCOA, TBRecord
from backend.app.services.sop.common import gl_lines
from backend.app.services.tax.ct_computation import final_balances

FRS102 = ("FRS102_1A", "FULL_FRS102")
NAME = "FRS 102 rulebook"
NIL = 1.0

# Company law size limits (two of three, Companies Act 2006 s382 / s384A as amended by SI 2024/1303): periods
# starting on or after 6 April 2025, and before
NEW_LIMITS_FROM = date(2025, 4, 6)
SMALL = {"new": (15_000_000, 7_500_000, 50), "old": (10_200_000, 5_100_000, 50)}
MICRO = {"new": (1_000_000, 500_000, 10), "old": (632_000, 316_000, 10)}

SALES = set(range(0, 106)) | {440}
OTHER_INCOME = set(range(500, 581)) | {400, 410, 430}
TRADE_DEBTORS, OTHER_DEBTORS = 4400, range(4420, 4430)
TRADE_CREDITORS, ACCRUALS, PREPAYMENTS, ACCRUED_INCOME = 5200, 5360, 4900, 4950
BANKS = range(4800, 4830)
RESERVE_BF, PRIOR_YEAR_ADJUSTMENT = 8000, 8030
DIRECTORS_LOAN = (5400, 5401, 5402, 5800)
INTANGIBLE_COST = (4000, 4001, 4010, 4011, 4020, 4021, 4030, 4031)
INTANGIBLES = range(4000, 4040)
AMORTISATION = (3500, 3551)
INVESTMENT_PROPERTY = range(4160, 4170)
IP_DEPRECIATION = (4165,)
LEASE_COSTS = (3100, 3200, 3205, 3210, 3215, 3220)
LEASES_FROM = date(2026, 1, 1)
LEASE_MIN = 1000.0
CASH_BASIS_TURNOVER = 10_000.0
CREDITOR_DEBIT_MIN = 100.0
ASSET_SALE_MIN = 500.0
ASSET_SALE = re.compile(r"sale of (the )?(van|car|vehicle|lorry|truck|machine|machinery|equipment|plant|asset|"
                        r"fixed asset)|part[ -]?ex|trade[ -]?in|webuyanycar|we buy any car|motorpoint|"
                        r"cazoo|carwow|cinch cars|sold (the )?(van|car|vehicle|machine)", re.I)
# A card account mapped to a bank code is a creditor by nature: not an overdraft
CARD = re.compile(r"card|amex|american express|visa|mastercard|capital on tap|pleo|soldo|loan", re.I)
WRITE_OFF = re.compile(r"writ\w* off|waive|waiver|releas\w* of (the )?loan|forgiv", re.I)


def _money(v: float) -> str:
    return f"£{abs(v):,.2f}"


def period_start(engagement: ClientEngagement) -> date:
    if engagement.prior_period_end_date:
        return engagement.prior_period_end_date + timedelta(days=1)
    end = engagement.period_end_date
    try:
        return end.replace(year=end.year - 1) + timedelta(days=1)
    except ValueError:                      # 29 February
        return end.replace(year=end.year - 1, day=28) + timedelta(days=1)


def _point(engagement: ClientEngagement, rule: str, severity: str, title: str, details: str, amount: float = 0.0,
           where: str = "") -> AuditFinding:
    return AuditFinding(
        engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=f"FRS-{rule}",
        procedure_name=f"{NAME} {rule}", severity=severity, source_row_ref=(where or f"{NAME} {rule}")[:100],
        finding_title=title[:255], finding_details=details, quantified_amount=round(abs(amount), 2), status="OPEN")


def _employees(engagement: ClientEngagement, db: Session) -> Optional[int]:
    """People on the payroll report (None when no report was uploaded): the most paid in one month."""
    # (none from a report for another period: payroll_period.py, as every payroll step)
    from backend.app.services.review.payroll_period import usable
    rows = usable(engagement, db)[0]
    named = [r for r in rows if r.employee_name]
    if not named:
        return None
    by_month: Dict[tuple, set] = {}
    for r in named:
        d = r.period_end or r.period_start
        by_month.setdefault((d.year, d.month) if d else None, set()).add(r.employee_name.strip().lower())
    return max(len(v) for v in by_month.values())


def size_point(engagement: ClientEngagement, framework: str, bal: Dict[int, float], chart: Dict[int, MasterCOA],
               db: Session) -> Optional[AuditFinding]:
    """F-002: FRS 105 is for micro-entities only and Section 1A for small companies only (two of three limits)."""
    start = period_start(engagement)
    era = "new" if start >= NEW_LIMITS_FROM else "old"
    months = max(1, round((engagement.period_end_date - start).days / 30.44))
    turnover = -sum(v for k, v in bal.items() if k in chart and chart[k].category == "Sales") * 12 / months
    assets = sum(v for k, v in bal.items() if k in chart and chart[k].financial_class == "Balance Sheet" and v > 0
                 and chart[k].category not in ("Profit and loss account", "Share capital"))
    staff = _employees(engagement, db)
    limits, label = (MICRO[era], "micro-entity") if framework == "FRS105" else \
        (SMALL[era], "small company") if framework == "FRS102_1A" else (None, "")
    if limits is None:
        return None
    over = [f"turnover {_money(turnover)}{' (for 12 months)' if months != 12 else ''} over {_money(limits[0])}"
            if turnover > limits[0] else "",
            f"balance sheet total {_money(assets)} over {_money(limits[1])}" if assets > limits[1] else "",
            f"{staff} employees over {limits[2]}" if staff is not None and staff > limits[2] else ""]
    over = [o for o in over if o]
    if len(over) < 2:
        return None
    use = "FRS 102 Section 1A (small) or full FRS 102" if framework == "FRS105" else "full FRS 102"
    return _point(
        engagement, "F-002", "HIGH",
        f"{'FRS 105' if framework == 'FRS105' else 'FRS 102 Section 1A'} chosen, but the company is over the "
        f"{label} limits",
        f"The company is over two of the three {label} limits ({'; '.join(over)}; limits for periods starting "
        f"{'on or after' if era == 'new' else 'before'} 6 April 2025). A company leaves the regime only when it is over "
        f"the limits in two years running: if it was also over last year, the accounts must use {use}. Please check "
        "last year's figures and change the framework on the client setup if needed."
        + ("" if staff is not None else " The number of employees is not known (no payroll report)."),
        turnover if turnover > limits[0] else assets, "Client setup: framework")


def frs102_points(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                  db: Session) -> List[AuditFinding]:
    framework = (profile.accounting_framework if profile is not None else None) or "FRS102_1A"
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    bal = final_balances(str(engagement.id), tb_records, db)
    out: List[AuditFinding] = []
    p = size_point(engagement, framework, bal, chart, db)
    if p is not None:
        out.append(p)
    if framework not in FRS102:
        return out
    b = lambda *codes: sum(bal.get(c, 0.0) for c in codes)
    names = lambda pred: [t.raw_account_name for t in tb_records if pred(t.std_code)]
    lines = gl_lines(str(engagement.id), tb_records, db)
    turnover = -sum(v for k, v in bal.items() if k in SALES)

    # F-004 accruals basis: a trading company with nothing owed either way at the year end
    held = [b(TRADE_DEBTORS, *OTHER_DEBTORS), b(PREPAYMENTS), b(ACCRUED_INCOME), b(TRADE_CREDITORS), b(ACCRUALS)]
    if turnover >= CASH_BASIS_TURNOVER and all(abs(v) < NIL for v in held):
        out.append(_point(
            engagement, "F-004", "MEDIUM", "No debtors, creditors, accruals or prepayments at the year end",
            f"Turnover is {_money(turnover)}, but nothing is owed to or by the company at the year end: no trade or other "
            "debtors, prepayments, accrued income, trade creditors or accruals. FRS 102 accounts are on the accruals "
            "basis (income and costs in the year they relate to), so the books look cash basis. Please check sales "
            "invoiced but unpaid, and bills for the year paid after the year end (the bank after the year end shows "
            "them)."))

    # F-006 / I-011 no netting: an overdrawn bank account is a creditor; a debit on trade creditors is not a creditor
    overdrawn, debit_creditors = [], []
    for t in tb_records:
        v = bal.get(t.std_code, 0.0) if sum(1 for x in tb_records if x.std_code == t.std_code) == 1 else float(t.net_amount or 0)
        if t.std_code in BANKS and v <= -CREDITOR_DEBIT_MIN and not CARD.search(t.raw_account_name or ""):
            overdrawn.append((t.raw_account_name, v))
        elif t.std_code == TRADE_CREDITORS and v >= CREDITOR_DEBIT_MIN:
            debit_creditors.append((t.raw_account_name, v))
    if overdrawn or debit_creditors:
        parts = [f"{n} overdrawn by {_money(v)}" for n, v in overdrawn] + \
                [f"{n} a debit of {_money(v)}" for n, v in debit_creditors]
        out.append(_point(
            engagement, "F-006", "LOW",
            (f"Bank overdrawn at the year end: {_money(sum(v for _n, v in overdrawn))}" if overdrawn else
             f"Trade creditors with a debit balance: {_money(sum(v for _n, v in debit_creditors))}"),
            "; ".join(parts) + ". FRS 102 does not net balances: an overdraft is shown under creditors due within one "
            "year, not taken off the other bank balances, and an overpaid supplier or a credit note due is a debtor, "
            "not taken off the creditors. Where the account was not really overdrawn (or the supplier not overpaid), "
            "a payment is posted twice or a receipt or bill is missing: check the bank reconciliation and the "
            "creditors listing.", sum(abs(v) for _n, v in overdrawn + debit_creditors)))

    # E-004: the reserve brought forward against last year's closing reserve (last year's job in the app)
    from backend.app.services.review.last_year import last_year_job
    last = last_year_job(engagement, db)
    if last is not None and last.period_end_date < engagement.period_end_date:
        last_tb = db.execute(select(TBRecord).where(TBRecord.engagement_id == last.id)).scalars().all()
        if last_tb:
            last_bal = final_balances(str(last.id), list(last_tb), db)
            closing = -sum(v for k, v in last_bal.items() if k in chart and (
                chart[k].financial_class == "Profit and Loss" or chart[k].category == "Profit and loss account"))
            brought = -b(RESERVE_BF, PRIOR_YEAR_ADJUSTMENT)
            moved_in_year = any(l.code == RESERVE_BF for l in lines)
            if abs(closing - brought) >= NIL and not moved_in_year:
                out.append(_point(
                    engagement, "E-004", "HIGH" if abs(closing - brought) >= 10000 else "MEDIUM",
                    f"Profit and loss reserve brought forward {_money(brought)}, last year closed at {_money(closing)}",
                    f"Last year's job ({last.period_end_date:%d/%m/%Y}) closes the profit and loss reserve at "
                    f"{'' if closing >= 0 else 'minus '}{_money(closing)}; this year brings forward "
                    f"{'' if brought >= 0 else 'minus '}{_money(brought)}, a difference of {_money(closing - brought)}. "
                    "The usual causes: dividends or journals posted straight to retained earnings this year (move them "
                    "to dividends or the right account), last year's figures changed after its job was finished (late "
                    "journals, last year's tax), or wrong opening balances. Agree the figure to last year's signed "
                    "accounts; a material prior-period error is corrected by restating last year (a prior year "
                    "adjustment, with a note).", closing - brought,
                    "Profit and loss reserve"))

    # IN-004 / G-005 amortisation: goodwill and intangibles are amortised (at most 10 years if the life is not known)
    nbv = b(*INTANGIBLES)
    cost = b(*INTANGIBLE_COST)
    charge = b(*AMORTISATION) + sum(l.credit - l.debit for l in lines if l.code in INTANGIBLES
                                    and re.search(r"amorti", l.description or "", re.I))
    charged_in_tb = any(t.std_code in INTANGIBLES and re.search(r"amortisation charge|charge in year", (chart[t.std_code].std_name
                        if t.std_code in chart else ""), re.I) and abs(float(t.net_amount or 0)) >= NIL for t in tb_records)
    if cost >= NIL and nbv >= NIL and abs(charge) < NIL and not charged_in_tb:
        out.append(_point(
            engagement, "IN-004", "MEDIUM", f"Goodwill and intangibles of {_money(nbv)} with no amortisation this year",
            f"{', '.join(names(lambda c: c in INTANGIBLES))[:300]}: {_money(nbv)} carried, no amortisation charged this "
            "year. FRS 102 (s18 and s19) amortises every intangible over its useful life; when the life cannot be "
            "estimated reliably, over no more than 10 years. Please confirm the life and post the charge (or confirm "
            "the asset is fully written down).", nbv))

    # IP-002: investment property is measured at fair value under FRS 102, never depreciated
    ip = b(*INVESTMENT_PROPERTY)
    ip_charge = b(*IP_DEPRECIATION)
    ip_named = [t for t in tb_records if t.std_code in (3400, 3405, 3406) and re.search(r"investment prop", t.raw_account_name or "", re.I)]
    if abs(ip) >= NIL and (abs(ip_charge) >= NIL or ip_named):
        dep = abs(ip_charge) or sum(abs(float(t.net_amount or 0)) for t in ip_named)
        out.append(_point(
            engagement, "IP-002", "HIGH", f"Investment property depreciated ({_money(dep)})",
            f"Investment property of {_money(ip)} has depreciation of {_money(dep)}. Under FRS 102 (s16) investment "
            "property is held at its fair value at each year end, with the change in value in the profit and loss "
            "account (and deferred tax on it), and is not depreciated. Please reverse the depreciation and post the "
            "change to the year-end valuation (the directors' or a valuer's).", dep, "Investment property"))

    # Q-005: a loan from a director or shareholder written off is a capital contribution (equity), not income
    waived = [l for l in lines if l.code in OTHER_INCOME | SALES and l.credit >= NIL and WRITE_OFF.search(l.description or "")
              and re.search(r"loan|director|dla|shareholder", f"{l.description} {l.account}", re.I)]
    waived += [l for l in lines if l.code in DIRECTORS_LOAN and l.debit >= NIL and WRITE_OFF.search(l.description or "")]
    if waived:
        total = sum(l.credit or l.debit for l in waived)
        out.append(_point(
            engagement, "Q-005", "MEDIUM", f"Director's or shareholder's loan written off: {_money(total)}",
            "; ".join(f"{l.when:%d/%m/%Y} {l.account}: {l.description} {_money(l.credit or l.debit)}" for l in waived[:6])
            + ". When a director or shareholder writes off money the company owes them, acting as a shareholder, the "
            "release is a capital contribution credited to equity (FRS 102 s22), not income. If the company wrote off "
            "money the director owed it, that is a distribution or pay (with s455 and NI to consider). Please confirm "
            "which, with the waiver letter.", total))

    # FA-007: fixed asset sale proceeds are not turnover: they go to the disposal (profit or loss on disposal)
    sold = [l for l in lines if l.code in SALES and l.credit >= ASSET_SALE_MIN and ASSET_SALE.search(l.description or "")]
    if sold:
        total = sum(l.credit for l in sold)
        out.append(_point(
            engagement, "FA-007", "HIGH", f"Sale of a fixed asset in sales: {_money(total)}",
            "; ".join(f"{l.when:%d/%m/%Y} {l.description} {_money(l.credit)}" for l in sold[:6])
            + ". Money from selling a fixed asset (a vehicle, machine or equipment) is not turnover. Move it to the "
            "asset's disposal: remove its cost and depreciation from the asset register and post the profit or loss "
            "on disposal (capital allowances: a disposal value in the pool). VAT on the sale stays as charged.", total))

    # L-001 / TR-002: periods from 1 January 2026 bring leases onto the balance sheet (right-of-use asset, liability)
    if period_start(engagement) >= LEASES_FROM:
        rent = b(*LEASE_COSTS)
        if rent >= LEASE_MIN:
            out.append(_point(
                engagement, "L-001", "MEDIUM", f"New lease rules apply this year: rent and leasing of {_money(rent)}",
                f"The period starts on or after 1 January 2026, so the 2024 amendments to FRS 102 apply: a lessee brings "
                f"its leases onto the balance sheet (a right-of-use asset and a lease liability) instead of expensing "
                f"rent of {_money(rent)}. Only leases of 12 months or less and low-value items (never property, vehicles "
                "or production equipment) can stay as an expense. Please list each lease (what, start and end, "
                "payments, break options) for the lease schedule and the transition journal to opening reserves.",
                rent, "Rent and leasing"))
    return out
