"""The firm's query rules on the TB and the ledger that the review and the Data check ask only in part. Each gives a query for the Queries tab
only: no review point, journal or figure changes.

  C-03  not the first year, a closing TB and no last year in the app: last year's signed accounts and closing TB
  C-08  a VAT balance or VAT in the ledger, the setup not VAT registered: the VAT returns and the HMRC VAT account
  C-10  no shareholders on the client setup: the directors and shareholders, with shareholdings
  TB-10 balances on the wrong side the review does not test (costs, other debtors and creditors, loans, accruals)
  TB-12 a balance sheet account named after a company, or intercompany / related party: who, and the balance
  TB-15 opening balances that differ from last year's closing balances (last year's job in the app)
  GL-03 manual journals over £1,000 (the review asks about round sums only, U-JNL-001), not the software's VAT
        journals or the firm's own year-end journals
  GL-04 a repairs, tools or sundry line over the capitalisation limit: the invoice (an asset?)
  YE-03 purchases over £5,000 and no stock this year or last: the year-end stock (U-STK-003 asks when last year had)
  YE-07 the capital allowances proposed on this year's additions, for the accountant to confirm
  SQ-02 business mileage in the director's own car (software jobs: the bank route asks it with use of home)
  SQ-06 no director's pay in the books: what the director was paid (the salary is often added through the
        director's loan: the amount comes from the client, not the books; costs paid personally are SQ-03)
  DL-04 clothing and fines in the costs: business purpose, or personal (the director's loan)
  DL-07 fuel with no company or leased vehicle in the books: whose car
  DL-08 with that, a mileage claim as well: the same car paid twice
Not here: TB-08 (unmapped accounts are fixed on the mapping screen; other debtors and creditors are broken down by
TB-13), GL-01 (one-off and unusual payments, G9), AR-02 (old debts, U-DEB-002), YE-01 (needs bills dated after the
year end)."""

import json
import re
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord
from backend.app.services.queries.r1_rules import _line_text, _money, _query

VAT = 5300
STOCK = tuple(range(4300, 4311))
PURCHASES = tuple(range(1100, 1110)) + (1400,) + tuple(range(2100, 2110)) + (2400,)
REPAIRS_SUNDRY = (1411, 1640, 2411, 2640, 3140, 3243, 3250) + tuple(range(3390, 3396))
DIVIDENDS, RESERVES = (8010, 8011), (8000, 8030)
LOANS = (5100, 5110, 5500, 5510)
OTHER_DEBTORS = tuple(range(4420, 4430))
OTHER_CREDITORS = (5350,) + tuple(range(5353, 5360))
ACCRUALS, PREPAYMENTS = 5360, 4900
# Codes whose side the review already tests (U-TB-004): trade debtors and creditors, fixed assets, cash in hand
WRONG_SIDE_MIN = 100.0
CONNECTED_MIN = 500.0
JOURNAL_MIN = 1000.0
STOCK_PURCHASES_MIN = 5000.0
JOURNAL = re.compile(r"journal", re.I)
COMPANY = re.compile(r"\b(ltd|limited|llp|plc|inc|gmbh|intercompany|inter-company|related part(y|ies)|group "
                     r"compan|sister compan|parent compan|subsidiar)\b", re.I)
# Balance sheet codes a company's name is expected on (trade, banks, loans and lenders, HP, tax, the director)
NAMED_BY_NATURE = set(range(4400, 4402)) | set(range(4800, 4831)) | set(range(5000, 5018)) | {5200, 5300, 5310, 5320,
                  5321, 5330, 5351, 5352} | set(LOANS) | set(range(5400, 5403)) | {5800, 5310, 5710} \
                  | set(range(4000, 4170)) | set(range(4200, 4240))
CLOTHING = re.compile(r"\bclothing\b|\bclothes\b|apparel|fashion|\bshoes?\b|footwear|\basos\b", re.I)
PERSONAL_MIN = 50.0
# Journals the software makes itself (Xero's VAT return journal) or the firm's own year-end and opening journals
NOT_CLIENT_JOURNAL = re.compile(r"filed vat|vat return|\bye adj|year[- ]end adj|opening balance|conversion balance|"
                                r"payroll|wages|salar|\bemployees?\b|\bpension\b", re.I)
ROUTINE_MONTHS = 6          # the same journal in six months or more is routine (the monthly payroll, a standing one)
WORKWEAR = re.compile(r"uniform|workwear|work wear|\bppe\b|protective|safety|hi-?vis|screwfix|toolstation|arco", re.I)
FINES = re.compile(r"\bpcn\b|penalty charge|parking (fine|charge notice)|speeding|fixed penalty|court fine|"
                   r"\bfine\b|traffic enforcement|\bdvla fine|congestion charge penalty", re.I)
DIRECTOR_PAY = re.compile(r"director'?s?'?\s*(?:salar|remun|wage|pay|fee)", re.I)     # the chart's own names
MILEAGE = re.compile(r"mileage|\bamap\b|motor allowance|business miles", re.I)
# Fuel for a vehicle: the words on the line or account, or the chart's vehicle fuel codes
FUEL = re.compile(r"\b(fuel|petrol|diesel|unleaded)\b|\b(shell|esso|texaco|gulf|jet|bp)\s+(garage|station|service|uk)\b", re.I)
FUEL_CODES = {1601, 2601, 3231}
VEHICLE_WORDS = re.compile(r"vehicle|\bcar\b|\bvan\b|motor|lorry|truck", re.I)
FUEL_MIN = 300.0


def _setup(profile) -> Dict[str, Any]:
    try:
        return json.loads(profile.setup or "{}") if profile is not None and profile.setup else {}
    except ValueError:
        return {}


def tb_queries(db: Session, eng: ClientEngagement, profile, tb: List[TBRecord], balances: Dict[int, float],
               lines) -> List[Dict[str, Any]]:
    from backend.app.services.bank_only.books import is_books_client
    from backend.app.services.queries.query_list import ACCOUNTANT, CLIENT, INTERNAL
    from backend.app.services.review.last_year import last_year_job, prior_uploaded
    from backend.app.services.setup.data_check import first_year, incorporated_in_year
    ye = f"{eng.period_end_date:%d %B %Y}" if eng.period_end_date else "the year end"
    miles_rate = _mileage_rate(eng)
    books = is_books_client(eng)
    setup = _setup(profile)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    b = lambda *codes: sum(balances.get(c, 0.0) for c in codes)
    net = lambda t: float(t.net_amount or 0)
    out: List[Dict[str, Any]] = []
    last = last_year_job(eng, db)
    opening_known = any(t.opening_amount is not None for t in tb)

    # C-03: a closing TB (it holds last year's balances) and no last year to agree them to
    if not books and not opening_known and last is None and not prior_uploaded(eng) and not first_year(profile) \
            and not incorporated_in_year(eng, profile):
        out.append({**_query("C-03", ACCOUNTANT, "Last year's signed accounts and closing TB",
                             "Please upload last year's signed accounts and closing trial balance so we can agree the "
                             "opening balances (this year's trial balance carries them, but there is nothing to check "
                             "them against).", round_=1, rule="C-03"), "blocking": True})

    # C-08: VAT in the books although the setup does not say VAT registered (the Data check asks when it does)
    vat_lines = [l for l in lines if l.code == VAT]
    if not (profile is not None and profile.is_vat_registered) and (abs(b(VAT)) >= 1 or vat_lines):
        out.append({**_query("C-08", CLIENT, "VAT returns for the year",
                             f"The books have a VAT account ({_money(-b(VAT))} at {ye}). Please send copies of the VAT "
                             "returns covering the year and a screenshot of the VAT account in your HMRC online "
                             "account (or tell us the company is not VAT registered).", abs(b(VAT)), rule="C-08"),
                    "blocking": True})

    # C-10: the directors and shareholders (with shareholdings): the director's loan, dividends, related parties
    if not (setup.get("people") or {}).get("shareholders"):
        out.append(_query("C-10", ACCOUNTANT, "Directors and shareholders",
                          f"Please confirm the directors and shareholders (with their shareholdings) during the year to "
                          f"{ye}. We need these for the director's loan, dividends and related party notes.", round_=1,
                          rule="C-10"))

    # TB-10: balances on the wrong side, beyond the codes the review tests (U-TB-004)
    wrong = []
    for t in tb:
        v, c = net(t), t.std_code
        cat = chart[c].category if c in chart else ""
        if (chart.get(c) is not None and chart[c].financial_class == "Profit and Loss" and cat not in (
                "Sales", "Other operating income", "Interest receivable and similar income", "Current tax",
                "Deferred tax") and not cat.startswith("Income from") and "stock" not in (chart[c].std_name or "").lower()
                and "profit/loss" not in (chart[c].std_name or "").lower() and v <= -WRONG_SIDE_MIN):
            wrong.append(f"{t.raw_account_name}: {_money(v)} credit on a cost account")
        elif c in OTHER_DEBTORS + (PREPAYMENTS,) and v <= -WRONG_SIDE_MIN:
            wrong.append(f"{t.raw_account_name}: {_money(v)} credit on a debtor")
        elif c in OTHER_CREDITORS + LOANS + (ACCRUALS,) and v >= WRONG_SIDE_MIN:
            wrong.append(f"{t.raw_account_name}: {_money(v)} debit on a creditor or loan")
    if wrong:
        out.append(_query("TB-10", INTERNAL, f"Balances on the wrong side: {len(wrong)}",
                          "These balances are on the opposite side to the account's nature: check the coding (a refund, "
                          "a payment posted to the wrong account, or a balance that belongs on the other side of the "
                          "balance sheet).", round_=1, lines=wrong, rule="TB-10"))

    # TB-12: a balance sheet account named after a company (not a customer, supplier, bank, lender or the tax office)
    connected = [t for t in tb if t.std_code not in NAMED_BY_NATURE and chart.get(t.std_code) is not None
                 and chart[t.std_code].financial_class == "Balance Sheet" and abs(net(t)) >= CONNECTED_MIN
                 and COMPANY.search(t.raw_account_name or "")
                 and not re.search(r"\b(hmrc|bank|loan|finance|leasing|card)\b", t.raw_account_name or "", re.I)]
    if connected:
        out.append(_query("TB-12", CLIENT, f"Balances with connected companies or people: {len(connected)}",
                          f"Please confirm who each of these is, how they are connected to the company, and that the "
                          f"balance is correct at {ye} (a statement or their confirmation).",
                          sum(abs(net(t)) for t in connected),
                          lines=[f"{t.raw_account_name}: {_money(net(t))} {'owed to the company' if net(t) > 0 else 'owed by the company'}"
                                 for t in connected], rule="TB-12"))

    # TB-15: this year's opening balances against last year's closing balances in the app (the reserve brought
    # forward is the review's FRS-E-004)
    if last is not None and opening_known and last.period_end_date < eng.period_end_date:
        from backend.app.services.tax.ct_computation import final_balances
        last_tb = db.execute(select(TBRecord).where(TBRecord.engagement_id == last.id)).scalars().all()
        closing = final_balances(str(last.id), list(last_tb), db) if last_tb else {}
        opening: Dict[int, float] = {}
        for t in tb:
            if t.std_code is not None:
                opening[t.std_code] = opening.get(t.std_code, 0.0) + float(t.opening_amount or 0)
        diffs = []
        for code in sorted(set(opening) | set(closing)):
            c = chart.get(code)
            if c is None or c.financial_class != "Balance Sheet" or code in RESERVES + DIVIDENDS:
                continue
            d = round(opening.get(code, 0.0) - closing.get(code, 0.0), 2)
            if abs(d) >= 1:
                diffs.append((code, d))
        # Totals that move between codes only (a remap) are not an opening difference: asked when the net is not nil
        # or a single code differs by more than £1
        if diffs:
            total = sum(abs(d) for _c, d in diffs)
            out.append({**_query("TB-15", ACCOUNTANT, f"Opening balances differ from last year's closing: "
                                                      f"{len(diffs)} account(s)",
                                 f"The opening balances in this year's books differ from last year's closing balances "
                                 f"({last.period_end_date:%d/%m/%Y} job) by {_money(total)} in all. Were adjustments "
                                 "posted after last year's accounts were signed, or last year's year-end journals not "
                                 "entered in the client's books? Agree them to last year's signed accounts.",
                                 total, lines=[f"{code:04d} {chart[code].std_name}: opening {_money(opening.get(code, 0))} "
                                               f"v last year {_money(closing.get(code, 0))} (difference {_money(d)})"
                                               for code, d in sorted(diffs, key=lambda x: -abs(x[1]))],
                                 rule="TB-15"), "blocking": True})

    # GL-03: manual journals over £1,000 (the client's software, not the app's own journals)
    if not books:
        journals = [l for l in lines if JOURNAL.search(l.source or "") and max(l.debit, l.credit) >= JOURNAL_MIN
                    and not NOT_CLIENT_JOURNAL.search(l.description or "")]
        if journals:
            months: Dict[str, set] = {}
            for l in journals:
                months.setdefault((l.description or "").strip().lower(), set()).add((l.when.year, l.when.month))
            journals = [l for l in journals if not (l.description or "").strip()
                        or len(months[(l.description or "").strip().lower()]) < ROUTINE_MONTHS]
        if journals:
            entries: Dict[tuple, float] = {}
            for l in journals:
                key = (l.when, (l.description or "").strip()[:80])
                entries[key] = entries.get(key, 0.0) + max(l.debit, l.credit)
            out.append(_query("GL-03", ACCOUNTANT, f"Manual journals over {_money(JOURNAL_MIN)}: {len(entries)}",
                              f"{len(entries)} manual journal(s) with lines over {_money(JOURNAL_MIN)} were posted in "
                              "the year (largest first). Please confirm what each is for, or send the supporting "
                              "schedule.", sum(entries.values()),
                              lines=[f"{d:%d/%m/%Y} {text or 'no description'}: {_money(v)}"
                                     for (d, text), v in sorted(entries.items(), key=lambda kv: -kv[1])], rule="GL-03"))

    # GL-04: one repairs, tools or sundry line over the capitalisation limit: may be a fixed asset
    cap = float(profile.capitalisation_threshold or 500.0) if profile is not None else 500.0
    capital = [l for l in lines if l.code in REPAIRS_SUNDRY and l.debit >= cap]
    if capital:
        out.append(_query("GL-04", CLIENT, f"Repairs and sundry costs over {_money(cap)}: the invoices",
                          f"Please send the invoice for each of these payments (over {_money(cap)}) and tell us what was "
                          "bought or done: equipment that lasts more than a year is a fixed asset, not a repair.",
                          sum(l.debit for l in capital),
                          lines=[_line_text(l) + f" ({l.account})" for l in sorted(capital, key=lambda l: -l.debit)],
                          rule="GL-04"))

    # YE-03: purchases of goods or materials, no stock this year or last (U-STK-003 asks when last year had stock)
    purchases = b(*PURCHASES)
    from backend.app.services.review.yearend_journals import last_year_stock
    last_stock = last_year_stock(eng, db)
    entered = ((setup.get("policies") or {}).get("closing_stock"))
    if purchases >= STOCK_PURCHASES_MIN and abs(b(*STOCK)) < 1 and abs(last_stock) < 1 and entered in (None, ""):
        out.append({**_query("YE-03", CLIENT, "Stock at the year end",
                             f"The company bought goods or materials of {_money(purchases)} in the year. Please tell us "
                             f"the value of stock (at cost) held on {ye}, with the stock list or count sheet if you have "
                             "one, or confirm there was none.", purchases, rule="YE-03"), "blocking": True})

    # YE-07: the capital allowances proposed on this year's additions, for the accountant to confirm
    try:
        from backend.app.services.tax.ct_computation import ct_computation
        comp = ct_computation(eng, tb, db)
        claims = [x for x in comp.capital_allowances if x.amount >= 1]
    except Exception:
        db.rollback()           # a failed read leaves the session unusable for the queries after it (read-only here)
        claims = []
    if claims:
        out.append(_query("YE-07", ACCOUNTANT, f"Capital allowances proposed: {_money(sum(x.amount for x in claims))}",
                          "We propose these capital allowances on this year's additions (CT computation). Please "
                          "confirm, or tell us if a different claim is wanted (for example a car's CO2, or a "
                          "disclaimer to keep allowances for later years).", sum(x.amount for x in claims),
                          lines=[f"{x.label}: {_money(x.amount)}" for x in claims], rule="YE-07"))

    # SQ-02: business mileage in the director's own car (the bank route asks it; use of home is U-ADJ-004)
    if not books and not any(MILEAGE.search(f"{t.raw_account_name}") and abs(net(t)) >= 1 for t in tb):
        out.append(_query("SQ-02", CLIENT, "Business mileage in your own car",
                          "Did you use your own car for business journeys during the year? If so, please give the total "
                          f"business miles (the company can pay you {miles_rate}).",
                          round_=1, rule="SQ-02"))

    # DL-07 / DL-08: fuel with no company vehicle, and mileage as well
    if not books:
        out += fuel_queries(chart, tb, lines, miles_rate)

    # SQ-06: no director's pay in the books: the director's salary is asked (it decides the director's loan, and so the
    # dividends that clear it)
    has_loan = any(t.std_code is not None and (5400 <= t.std_code <= 5416 or 5800 <= t.std_code <= 5816) for t in tb)
    pay_codes = {c for c, row in chart.items() if DIRECTOR_PAY.search(row.std_name or "")}
    from backend.app.services.review.adjustments import director_answers
    answered = director_answers(eng)["director_salary"] is not None if eng is not None else False
    if not books and has_loan and not answered and not any(t.std_code in pay_codes and abs(net(t)) >= 1 for t in tb):
        out.append(_query("SQ-06", CLIENT, "The director's salary for the year",
                          "The books show no salary for the director this year. Did the director take a salary? If so, "
                          "please send the P60 or the payslips (or confirm the amount, often £12,570 a year); if not, "
                          "please confirm no salary was paid.", round_=1, rule="SQ-06"))

    # DL-04: clothing and fines: not allowed for tax (fines never; clothing unless uniform or protective)
    costs = [l for l in lines if l.debit >= 1 and chart.get(l.code) is not None
             and chart[l.code].financial_class == "Profit and Loss"]
    clothes = [l for l in costs if CLOTHING.search(f"{l.description} {l.account}") and not WORKWEAR.search(f"{l.description} {l.account}")]
    fines = [l for l in costs if FINES.search(l.description or "") and not re.search(r"fine art|fine dining|finest", l.description or "", re.I)]
    found = sorted(clothes + fines, key=lambda l: -l.debit)
    if found and sum(l.debit for l in found) >= PERSONAL_MIN:
        out.append(_query("DL-04", CLIENT, f"Clothing and fines: {_money(sum(l.debit for l in found))}",
                          "Please confirm the business purpose of these costs. Fines and penalties are never allowed "
                          "for tax, and clothing only when it is a uniform or protective wear; if any were personal we "
                          "will move them to your director's loan account.", sum(l.debit for l in found),
                          lines=[_line_text(l) for l in found], rule="DL-04"))
    return out


def _mileage_rate(eng: ClientEngagement) -> str:
    """The approved mileage rate for the company's year, in words (tax/mileage.py: 55p from 6 April 2026)."""
    from datetime import timedelta
    from backend.app.services.tax.mileage import rate_text
    end = eng.period_end_date
    if end is None:
        return rate_text(date.today(), date.today())
    start = eng.prior_period_end_date + timedelta(days=1) if eng.prior_period_end_date else end - timedelta(days=364)
    return rate_text(start, end)


def fuel_queries(chart: Dict[int, Any], tb: List[TBRecord], lines,
                 miles_rate: str = "45p a mile for the first 10,000, 25p after") -> List[Dict[str, Any]]:
    """DL-07 fuel paid with no company or leased vehicle in the books; DL-08 a mileage claim as well."""
    from backend.app.services.queries.query_list import ACCOUNTANT, CLIENT
    net = lambda t: float(t.net_amount or 0)
    out: List[Dict[str, Any]] = []
    # DL-07 / DL-08: fuel paid with no company vehicle in the books is for whose car? With a
    # mileage claim as well, the same car may be paid twice (the mileage rate already covers fuel; HMRC EIM31205)
    vehicle_codes = {c for c, row in chart.items() if row.financial_class == "Balance Sheet"
                     and re.search(r"motor vehicles?", row.std_name or "", re.I)}
    has_vehicle = any(abs(net(t)) >= 1 or abs(float(t.opening_amount or 0)) >= 1 for t in tb if t.std_code in vehicle_codes)
    leased = any(re.search(r"lease|leasing|hire", f"{t.raw_account_name}", re.I) and VEHICLE_WORDS.search(
        f"{t.raw_account_name} {chart[t.std_code].std_name if t.std_code in chart else ''}") and abs(net(t)) >= 1
        for t in tb)
    fuel = [l for l in lines if l.debit >= 1 and chart.get(l.code) is not None
            and chart[l.code].financial_class == "Profit and Loss"
            and (FUEL.search(f"{l.account} {l.description}") or l.code in FUEL_CODES)]
    fuel_total = round(sum(l.debit for l in fuel), 2)
    if fuel_total >= FUEL_MIN and not has_vehicle and not leased:
        mileage = round(sum(net(t) for t in tb if MILEAGE.search(t.raw_account_name or "") and net(t) > 0)
                        + sum(l.debit for l in lines if MILEAGE.search(l.description or "") and l.debit > 0
                              and not MILEAGE.search(l.account or "")), 2)
        out.append(_query("DL-07", CLIENT, f"Fuel of {_money(fuel_total)} with no company vehicle",
                          "Fuel was paid by the company, but there is no company or leased vehicle in the books. Whose "
                          "vehicle is it for? For the director's own car the company can pay a mileage allowance "
                          f"({miles_rate}) instead; fuel for a private car is the "
                          "director's own cost, charged to the director's loan.", fuel_total,
                          lines=[_line_text(l) for l in sorted(fuel, key=lambda l: -l.debit)[:10]], rule="DL-07"))
        if mileage >= 1:
            out.append(_query("DL-08", ACCOUNTANT, f"Mileage and fuel both paid: {_money(mileage)} and {_money(fuel_total)}",
                              "The company pays mileage and also fuel, with no company vehicle: the mileage rate already "
                              "covers the fuel of the director's own car, so the same car may be paid for twice. Check "
                              "the mileage log and move the private fuel to the director's loan.", fuel_total,
                              rule="DL-08"))

    return out
