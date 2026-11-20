"""Queries from the FRS 102 rulebook (ledgermind_frs102_rules.json) that need the
client's or the accountant's answer, not a figure in the books. The Queries tab only: no review point, journal or
figure changes. The rule numbers are the rulebook's; all but D-010 only on FRS 102 jobs (1A or full).

  G-001   shares in a subsidiary: group accounts, or which exemption applies
  IP-002  investment property with no change in value this year: the year-end valuation
  FA-005  freehold property depreciated: the land element (land is not depreciated)
  FX-002  a bank account in a foreign currency: its year-end balance in that currency
  Q-001   preference shares: redeemable (a liability) or not (equity)
  I-010   swaps, forward contracts or other derivatives: the bank's year-end valuation
  D-010   no payroll report: the average number of employees (including directors) for the notes"""

import re
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, PayrollP32Record, TBRecord
from backend.app.services.queries.r1_rules import _money, _query
from backend.app.services.review.frs102_checks import FRS102, INVESTMENT_PROPERTY

SUBSIDIARIES = tuple(range(4230, 4240)) + (4600,)
FAIR_VALUE_MOVES = (3570, 3575, 3580, 3585, 4162)
FREEHOLD = range(4100, 4110)
FREEHOLD_DEPRECIATION = (3405,)
PREFERENCE_SHARES = range(7020, 7037)
BANKS = range(4800, 4830)
CURRENCY = re.compile(r"\b(usd|eur|euro|euros|dollar|dollars|us\$|chf|aed|inr|cad|aud|nzd|sek|nok|dkk|pln|jpy|"
                      r"currency|foreign|fx)\b|[$€¥]", re.I)
DERIVATIVE = re.compile(r"(interest rate|currency|fx|cross currency) swap|swap (agreement|contract|valuation|interest|"
                        r"settlement)|forward (fx )?contract|fx forward|currency forward|forward exchange|hedg(e|ing) "
                        r"(contract|instrument|loss|gain|settlement)|interest rate (cap|collar|hedge)|option premium", re.I)


def frs102_queries(db: Session, eng: ClientEngagement, profile, tb: List[TBRecord], balances: Dict[int, float],
                   lines) -> List[Dict[str, Any]]:
    from backend.app.services.queries.query_list import ACCOUNTANT, CLIENT
    framework = (profile.accounting_framework if profile is not None else None) or "FRS102_1A"
    ye = f"{eng.period_end_date:%d %B %Y}" if eng.period_end_date else "the year end"
    b = lambda *codes: sum(balances.get(c, 0.0) for c in codes)
    named = lambda codes: [f"{t.raw_account_name}: {_money(float(t.net_amount or 0))}" for t in tb
                           if t.std_code in codes and abs(float(t.net_amount or 0)) >= 1]
    out: List[Dict[str, Any]] = []

    # D-010 (every framework): the notes give the average number of employees, directors included
    has_report = db.execute(select(PayrollP32Record.id).where(PayrollP32Record.engagement_id == eng.id,
                                                              PayrollP32Record.employee_name.isnot(None)).limit(1)).first()
    if has_report is None:
        out.append(_query("D-010", CLIENT, "Average number of employees in the year",
                          "The accounts must show the average number of people employed during the year, directors "
                          "included. How many people (including directors) worked for the company on average, month "
                          "by month?", round_=1, rule="D-010"))
    if framework not in FRS102:
        return out

    # G-001: a parent prepares group accounts unless an exemption applies (a small group, or included in a larger one)
    subs = b(*SUBSIDIARIES)
    if subs >= 1:
        out.append(_query("G-001", ACCOUNTANT, f"Shares in subsidiaries of {_money(subs)}: group accounts?",
                          f"The company holds shares in subsidiaries ({_money(subs)}). Please confirm whether group "
                          "accounts are needed or which exemption applies (a small group, or the company is included in "
                          "a larger group's accounts), and check each subsidiary's net assets for impairment.", subs,
                          lines=named(SUBSIDIARIES), rule="G-001"))

    # IP-002: investment property at fair value each year end: the valuation behind it
    ip = b(*INVESTMENT_PROPERTY)
    if ip >= 1 and not any(abs(b(c)) >= 1 for c in FAIR_VALUE_MOVES):
        out.append(_query("IP-002", CLIENT, f"Investment property {_money(ip)}: value at the year end",
                          f"Investment property is shown at its value at {ye} ({_money(ip)} in the books, no change in "
                          "value this year). Please tell us what each property was worth at the year end (the "
                          "directors' estimate, or a valuer's or agent's report if there is one).", ip,
                          lines=named(INVESTMENT_PROPERTY), rule="IP-002"))

    # FA-005: freehold property depreciated: land is never depreciated, so the cost needs a land / building split
    chart = {c.std_code: c.std_name or "" for c in db.execute(select(MasterCOA).where(
        MasterCOA.std_code.in_(list(FREEHOLD)))).scalars()}
    freehold = b(*FREEHOLD)
    charged = abs(b(*FREEHOLD_DEPRECIATION)) + sum(abs(float(t.net_amount or 0)) for t in tb if t.std_code in FREEHOLD
                                                    and "charge" in chart.get(t.std_code, "").lower())
    land_shown = any(re.search(r"\bland\b(?!.*(build|propert))", t.raw_account_name or "", re.I) for t in tb
                     if t.std_code in FREEHOLD)
    if freehold >= 1 and charged >= 1 and not land_shown:
        out.append(_query("FA-005", ACCOUNTANT, "Freehold property depreciated: the land element",
                          f"Freehold property ({_money(freehold)}) is depreciated ({_money(charged)} this year) with no "
                          "separate land account. Land is not depreciated (FRS 102 s17): please split the cost between "
                          "land and buildings (a valuation, the purchase completion statement or the council tax / "
                          "insurance value) and depreciate the buildings only.", charged, rule="FA-005"))

    # FX-002: foreign currency balances are translated at the closing rate at the year end
    foreign = [t for t in tb if t.std_code in BANKS and CURRENCY.search(t.raw_account_name or "")
               and abs(float(t.net_amount or 0)) >= 1]
    if foreign:
        out.append(_query("FX-002", CLIENT, f"Bank accounts in a foreign currency: {len(foreign)}",
                          f"Please send the statement for each of these accounts showing its balance at {ye} in the "
                          "account's own currency, so we can translate it at the year-end rate.",
                          sum(abs(float(t.net_amount or 0)) for t in foreign),
                          lines=[f"{t.raw_account_name}: {_money(float(t.net_amount or 0))}" for t in foreign],
                          rule="FX-002"))

    # Q-001: a share that must be repaid (redeemable preference shares) is a liability, not share capital
    pref = -b(*PREFERENCE_SHARES)
    if abs(pref) >= 1:
        out.append(_query("Q-001", ACCOUNTANT, f"Preference shares {_money(pref)}: liability or equity?",
                          "The company has preference shares. If the company must redeem them, or pay a fixed dividend "
                          "whatever its profits, they are a liability (FRS 102 s22), with the dividends as interest. "
                          "Please check the articles or the share terms and confirm how they are shown.", pref,
                          lines=named(PREFERENCE_SHARES), rule="Q-001"))

    # I-010: derivatives are measured at fair value: the bank's year-end valuation (mark-to-market) letter
    deriv = [l for l in lines if DERIVATIVE.search(f"{l.description or ''} {l.account or ''}")]
    if deriv:
        out.append(_query("I-010", ACCOUNTANT, "Swap, forward contract or other derivative in the books",
                          "These lines look like a swap, forward contract or other derivative. Derivatives are shown at "
                          f"their fair value at {ye} (FRS 102 s12): please get the bank's valuation letter, or confirm "
                          "they are not derivatives.", sum(abs(l.debit - l.credit) for l in deriv),
                          lines=[f"{l.when:%d/%m/%Y} {(l.description or l.account).strip()}: "
                                 f"{_money(l.debit - l.credit)}" for l in deriv], rule="I-010"))
    return out
