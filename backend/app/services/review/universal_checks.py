"""
Checks the firm's Industry Query Library asks for on every client (UNIV queries), worked out from the final balances
(TB plus approved journals), the corporation tax computation and the aged receivables report:

  U-GC-001   going concern: net liabilities, net current liabilities, or a loss for the year
  U-EQ-001   dividends paid more than the distributable reserves (reserve brought forward + profit after tax)
  U-DEB-002  debtors outstanding more than 90 days (aged receivables report)
  U-BNK-004  cash in hand negative at a month end (cash cannot go below nil: missing receipts or costs paid
             personally)
  U-CRD-090  supplier bills outstanding more than 90 days (aged payables report)
  U-BNK-005  a credit card in debit at the year end
Not covered here: U-TB-002 (opening balances against last year's accounts) needs last year's engagement in the app and
the ledger's opening-balance lines kept at upload.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord
from backend.app.services.ingestion.ageing_reports import over_90_days, read_ageing_reports
from backend.app.services.tax.ct_computation import ct_computation, final_balances
from backend.app.services.sop.common import gl_lines, year_months
from backend.app.services.review.point_figures import amounts

EQUITY_SECTIONS = {"Share capital", "Share premium account", "Revaluation reserve", "Capital redemption reserve",
                   "Other reserves", "Fair Value Reserves", "Profit and loss account", "Non-controlling interest"}
CURRENT_ASSETS = {"Stock", "Debtors < 1 year", "Current assets - investments", "Cash at bank and in hand",
                  "Prepayments and accrued income"}
CURRENT_LIABILITIES = {"Current liabilities - creditors < 1 year"}
TAX_SECTIONS = {"Current tax", "Deferred tax"}
RESERVE_BF, PRIOR_YEAR_ADJUSTMENT = 8000, 8030
DIVIDENDS_PAID = (8010, 8011)
CASH_IN_HAND = 4830
DEBTOR_REVIEW_MIN = 100.0
CARD_DEBIT_MIN = 100.0
OTHER_CREDITORS = range(5350, 5360)


@dataclass
class GeneralFinding:
    query: str
    severity: str
    title: str
    details: str
    amount: float = 0.0
    # The point's figures as a small table for the screen (review/point_figures.py), when known
    figures: Optional[str] = None


@dataclass
class GeneralChecks:
    figures: Dict[str, Optional[float]] = field(default_factory=dict)   # key figures shown on the tab
    findings: List[GeneralFinding] = field(default_factory=list)
    old_debtors: Dict[str, float] = field(default_factory=dict)


def general_checks(engagement: ClientEngagement, tb_records: Iterable[TBRecord], db: Session) -> GeneralChecks:
    tb_records = list(tb_records)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    bal = final_balances(str(engagement.id), tb_records, db)
    section = lambda k: chart[k].category if k in chart else None
    bs = lambda k: k in chart and chart[k].financial_class == "Balance Sheet"
    out = GeneralChecks()

    # Profit, and profit after the tax this computation says is due (the accounts may not hold the charge yet)
    profit_before_tax = -sum(v for k, v in bal.items() if k in chart and chart[k].financial_class == "Profit and Loss"
                             and section(k) not in TAX_SECTIONS)
    comp = ct_computation(engagement, tb_records, db)
    profit_after_tax = profit_before_tax - comp.corporation_tax
    net_assets = sum(v for k, v in bal.items() if bs(k) and section(k) not in EQUITY_SECTIONS) \
        - comp.corporation_tax + comp.tax_in_accounts           # the tax still to be provided is a liability
    net_current = sum(v for k, v in bal.items() if section(k) in CURRENT_ASSETS | CURRENT_LIABILITIES) \
        - comp.corporation_tax + comp.tax_in_accounts
    out.figures.update({"Profit before tax": round(profit_before_tax, 2), "Corporation tax (computation)": comp.corporation_tax,
                        "Profit after tax": round(profit_after_tax, 2), "Net assets / (liabilities)": round(net_assets, 2),
                        "Net current assets / (liabilities)": round(net_current, 2)})

    # U-GC-001 going concern
    reasons, figures = [], []         # the title names the first reason; the point's amount is that figure
    if net_assets < -1:
        reasons.append(f"net liabilities of £{-net_assets:,.2f}"); figures.append(-net_assets)
    if net_current < -1:
        reasons.append(f"net current liabilities of £{-net_current:,.2f} (short-term debts more than short-term assets)")
        figures.append(-net_current)
    if profit_before_tax < -1:
        reasons.append(f"a loss of £{-profit_before_tax:,.2f} for the year"); figures.append(-profit_before_tax)
    if reasons:
        out.findings.append(GeneralFinding(
            "U-GC-001", "HIGH" if net_assets < -1 or len(reasons) > 1 else "MEDIUM",
            f"Going concern: the company has {reasons[0]}",
            "The company has " + "; ".join(reasons) + ". Client question: Please provide your assessment of going concern "
            "for at least 12 months from approval of the accounts, including support from directors or lenders.",
            round(figures[0], 2),
            amounts([("Net assets / (liabilities)", net_assets, net_assets < -1),
                     ("Net current assets / (liabilities)", net_current, net_assets >= -1 and net_current < -1),
                     ("Profit / (loss) before tax", profit_before_tax)])))

    # U-EQ-001 dividends vs distributable reserves
    dividends = sum(bal.get(k, 0.0) for k in DIVIDENDS_PAID)
    reserve_bf = -(bal.get(RESERVE_BF, 0.0) + bal.get(PRIOR_YEAR_ADJUSTMENT, 0.0))
    distributable = reserve_bf + profit_after_tax
    out.figures.update({"Profit and loss reserve brought forward": round(reserve_bf, 2), "Dividends paid": round(dividends, 2),
                        "Distributable reserves before dividends": round(distributable, 2)})
    if dividends > 1 and dividends > distributable + 1:
        out.findings.append(GeneralFinding(
            "U-EQ-001", "HIGH", f"Dividends of £{dividends:,.2f} exceed distributable reserves of £{max(distributable, 0):,.2f}",
            f"Reserve brought forward £{reserve_bf:,.2f} + profit after tax £{profit_after_tax:,.2f} = £{distributable:,.2f}. "
            f"A dividend paid out of more than the distributable reserves is unlawful (Companies Act 2006 s830) and may "
            f"have to be repaid or treated as a director's loan. Client question: Please provide board minutes and "
            f"dividend vouchers, and confirm the dates paid.", round(dividends - max(distributable, 0.0), 2),
            amounts([("Reserve brought forward", reserve_bf), ("Profit after tax", profit_after_tax),
                     ("Distributable reserves", distributable), ("Dividends paid", dividends),
                     ("Over the reserves", dividends - max(distributable, 0.0), True)])))

    # U-DEB-002 debtors over 90 days
    report = read_ageing_reports(str(engagement.id), engagement.period_end_date, tb_records).get("AR")
    if report is not None and report.as_at in (None, engagement.period_end_date):
        out.old_debtors = dict(sorted(over_90_days(report, engagement.period_end_date).items(), key=lambda x: -x[1]))
        old = sum(out.old_debtors.values())
        out.figures["Debtors over 90 days"] = round(old, 2)
        if old >= DEBTOR_REVIEW_MIN:
            top = "; ".join(f"{k} £{v:,.2f}" for k, v in list(out.old_debtors.items())[:5])
            share = f" ({old / report.total:.0%} of the £{report.total:,.2f} owed)" if report.total else ""
            out.findings.append(GeneralFinding(
                "U-DEB-002", "HIGH" if report.total and old / report.total > 0.25 else "MEDIUM",
                f"Debtors of £{old:,.2f} are more than 90 days old{share}",
                f"Largest: {top}. Client question: Please confirm these are recoverable and whether any are disputed; "
                f"a debt not expected to be paid needs writing off or providing for (VAT bad debt relief is separate).",
                round(old, 2)))

    # U-CRD-090 supplier bills over 90 days: still owed, disputed, or paid and not matched
    ap = read_ageing_reports(str(engagement.id), engagement.period_end_date, tb_records).get("AP")
    if ap is not None and ap.as_at in (None, engagement.period_end_date):
        old_bills = dict(sorted(over_90_days(ap, engagement.period_end_date).items(), key=lambda x: -x[1]))
        old = sum(old_bills.values())
        out.figures["Creditors over 90 days"] = round(old, 2)
        if old >= DEBTOR_REVIEW_MIN:
            top = "; ".join(f"{k} £{v:,.2f}" for k, v in list(old_bills.items())[:5])
            share = f" ({old / ap.total:.0%} of the £{ap.total:,.2f} owed)" if ap.total else ""
            out.findings.append(GeneralFinding(
                "U-CRD-090", "MEDIUM", f"Supplier bills of £{old:,.2f} are more than 90 days old{share}",
                f"Largest: {top}. Old unpaid bills are often paid already (a payment not matched to the bill, so the cost "
                f"or the creditor is counted twice), disputed, or no longer owed. Client question: Please confirm these "
                f"bills are still owed at the year end; any paid, credited or not owed are corrected.", round(old, 2)))

    # U-BNK-004 cash in hand below nil at a month end: closing balance worked back through the ledger
    lines = [l for l in gl_lines(str(engagement.id), tb_records, db) if l.code == CASH_IN_HAND]
    if lines:
        closing = bal.get(CASH_IN_HAND, 0.0)
        negative = []
        for month_end in year_months(engagement.period_end_date):
            after = sum(l.debit - l.credit for l in lines if l.when > month_end)
            if closing - after < -1:
                negative.append((month_end, round(closing - after, 2)))
        if negative:
            out.findings.append(GeneralFinding(
                "U-BNK-004", "MEDIUM", f"Cash in hand below nil at {len(negative)} month end(s)",
                "; ".join(f"{d:%b %Y} £{v:,.2f}" for d, v in negative[:6]) + ". Cash cannot go below nil: this usually "
                "means receipts not recorded, or costs paid personally (director's loan). Client question: Please provide "
                "the year-end cash count and explain the negative balances.", abs(min(v for _d, v in negative))))

    # U-BNK-005 a credit card in debit at the year end (amber), each card by its account (a card is found by its
    # name: clients keep cards on 5350-5359 or a bank code, and 5351 holds CIS on some): more paid off than spent,
    # card purchases not posted, a personal card, or (no balance brought forward) last year's card balance kept on
    # another creditor line
    out.findings.extend(cards_in_debit(tb_records))
    return out


def cards_in_debit(tb_records: List[TBRecord]) -> List[GeneralFinding]:
    from backend.app.services.workbook.balance_tabs.cards import CARD_NAME, NOT_A_CARD
    is_card = lambda t: (t.std_code in OTHER_CREDITORS or 4800 <= int(t.std_code or 0) < 4900) and         bool(CARD_NAME.search(t.raw_account_name or "")) and not NOT_A_CARD.search(t.raw_account_name or "")
    found = []
    for t in tb_records:
        if t.std_code is None or not is_card(t):
            continue
        debit = round(float(t.net_amount or 0.0), 2)
        if debit < CARD_DEBIT_MIN:
            continue
        opening = float(t.opening_amount or 0.0)
        name = t.raw_account_name
        why = (f"{name} ({t.std_code}) ends £{debit:,.2f} in debit: the card owing the company. A card is normally owed "
               f"to the bank. Usual causes: card purchases not posted (to the costs, or the director's loan for "
               f"personal spending), a payment to the card posted twice, a refund, or a personal card the company paid.")
        if abs(opening) < 1.0:
            paid = round(debit - opening, 2)
            others = sorted((x for x in tb_records if x is not t and x.std_code in OTHER_CREDITORS
                             and -float(x.opening_amount or 0.0) >= debit), key=lambda x: float(x.opening_amount or 0.0))
            why += (f" It has no balance brought forward, yet £{paid:,.2f} more was paid to it than spent this year: its "
                    f"balance at last year's end is probably kept elsewhere")
            if others:
                x = others[0]
                why += (f" (last year's TB holds £{-float(x.opening_amount):,.2f} on {x.std_code}, '{x.raw_account_name}',"
                        f" which may include it: move the card's part to the card)")
            why += "."
        why += (" Client question: Please send the card statements at the year end and at last year's end, with any "
                "card purchases not yet in the books; if it is the director's personal card, please say so.")
        found.append(GeneralFinding("U-BNK-005", "MEDIUM" if abs(opening) < 1.0 else "LOW",
                                    f"Credit card in debit at the year end: {name} £{debit:,.2f}"[:255], why, debit))
    return found
