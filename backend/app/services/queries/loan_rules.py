"""The firm's query rules on loans, the director's loan, dividends and donations that the review does not ask. Each gives a query for the Queries tab
only: no review point, journal or figure changes.

  TB-01 a new loan (no balance last year, or money borrowed in the year): agreement and statement; the accountant's
        split and interest
  TB-02 each existing loan: its year-end statement
  TB-03 a loan with no interest of its own (two or more loans, interest seen for only some)
  LN-01 an existing loan with no repayment in the year
  DL-01 the director's loan overdrawn at the year end: repaid since?
  DL-02 dividends paid: vouchers and board minutes
  DL-03 a credit balance on a dividend account
  DL-05 donations: how much was political"""

import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.queries.r1_rules import DIRECTORS_LOAN_CODES, _money, _query

# Bank loans, other loans, hire purchase and finance leases (under and over one year)
LOAN_CODES = (5100, 5110, 5500, 5510, 5000, 5001, 5002, 5010, 5011, 5012)
INTEREST_CODES = (3600, 3615, 3618, 3631, 3632, 3633, 3634, 3635, 3641, 3642, 5005, 5006, 5007, 5015, 5016, 5017)
DIVIDEND_CODES = (8010, 8011)
S455_RECOVERABLE = 4550     # s455 tax paid on an overdrawn director's loan, recoverable once the loan is repaid
DONATIONS, POLITICAL = 3360, 3361
LOAN_MIN = 500.0            # TB-01 / TB-02: a loan worth a statement (over £500)
INTEREST_MIN = 1000.0       # TB-03: a loan worth an interest question (over £1,000)
NOT_A_LENDER = {"loan", "loans", "bank", "other", "account", "ltd", "limited", "plc", "the", "and", "hire", "purchase",
                "finance", "lease", "leases", "less", "than", "year", "years", "after", "within", "between", "one",
                "five", "long", "short", "term", "current", "due", "creditors", "liability", "liabilities", "interest",
                "capital", "repayment", "repayments", "business"}


def _f(v) -> float:
    return float(v or 0)


def _lender_words(name: str) -> List[str]:
    return [w for w in re.findall(r"[a-z]{3,}", (name or "").lower()) if w not in NOT_A_LENDER]


def loan_queries(db: Session, eng: ClientEngagement, tb: List[TBRecord], balances: Dict[int, float],
                 lines, data_keys: Optional[set] = None) -> List[Dict[str, Any]]:
    from backend.app.services.queries.query_list import ACCOUNTANT, CLIENT
    from backend.app.services.review.last_year import last_year_job
    ye = f"{eng.period_end_date:%d %B %Y}" if eng.period_end_date else "the year end"
    out: List[Dict[str, Any]] = []

    # Loans: each TB account on a loan code, with what it held last year (the TB's opening column, else last
    # year's job in the app; None when neither tells)
    loans = [t for t in tb if t.std_code in LOAN_CODES and abs(_f(t.net_amount)) >= LOAN_MIN
             and not re.search(r"director|\bdla\b", t.raw_account_name or "", re.I)]
    last = last_year_job(eng, db) if loans else None
    last_tb = {} if last is None else {
        (t.raw_account_name or "").strip().lower(): _f(t.net_amount)
        for t in db.query(TBRecord).filter(TBRecord.engagement_id == last.id).all()}

    def opening(t: TBRecord) -> Optional[float]:
        if t.opening_amount is not None:
            return _f(t.opening_amount)
        if last is not None:
            return last_tb.get((t.raw_account_name or "").strip().lower(), 0.0)
        return None

    # Money borrowed in the year: credits to the loan from the bank, not the year-end journals that charge its
    # interest or split it between under and over one year
    borrowed = lambda t: sum(l.credit for l in lines if l.account == t.raw_account_name and l.code in LOAN_CODES
                             and not re.search(r"journal", l.source or "", re.I)
                             and not re.search(r"interest|bifurcat|reclass|split|transfer|ye adj", l.description or "", re.I))
    new, existing = [], []
    for t in loans:
        before = opening(t)
        (new if (before is not None and abs(before) < 1) or borrowed(t) >= LOAN_MIN else existing).append(t)

    # TB-01: a new loan: the agreement and statement from the client, the split and interest for the accountant
    for t in new:
        bal = -_f(t.net_amount)
        out.append({**_query(f"TB-01:{t.raw_account_name}", CLIENT, f"New loan: {t.raw_account_name} {_money(bal)}",
                             f"We can see a new loan of {_money(bal)} ({t.raw_account_name}). Please send the loan "
                             f"agreement and a statement showing the balance at {ye}, the interest charged and the "
                             "repayments made.", bal, rule="TB-01"), "blocking": True})
        out.append(_query(f"TB-01a:{t.raw_account_name}", ACCOUNTANT, f"New loan {t.raw_account_name}: split and interest",
                          f"New loan {t.raw_account_name} ({_money(bal)}): once the statement arrives we will split it "
                          "between amounts due within and after one year and accrue interest. Please confirm whether "
                          "there is any security or personal guarantee to disclose.", bal, rule="TB-01"))

    # TB-02: the year-end statement for every existing loan (a bank job's Data check already asks for them)
    if existing and not any(k.startswith("data:loan:") for k in (data_keys or set())):
        total = sum(-_f(t.net_amount) for t in existing)
        out.append({**_query("TB-02", CLIENT, f"Loan statements at the year end: {len(existing)}",
                             f"Please send a statement for each of these loans showing the balance at {ye} and the "
                             "interest charged in the year.", total,
                             lines=[f"{t.raw_account_name}: {_money(-_f(t.net_amount))}" for t in existing],
                             rule="TB-02"), "blocking": True})

    # TB-03: with two or more loans, a loan whose lender is named on no interest line (the review asks when there is
    # no interest at all, U-LOAN-001)
    interest_lines = [l for l in lines if l.code in INTEREST_CODES and l.debit > 0]
    big = [t for t in loans if -_f(t.net_amount) >= INTEREST_MIN]
    if len(big) >= 2 and interest_lines:
        text = " ".join(f"{l.account} {l.description}".lower() for l in interest_lines)
        silent = [t for t in big if _lender_words(t.raw_account_name)
                  and not any(w in text for w in _lender_words(t.raw_account_name))]
        if silent:
            out.append(_query("TB-03", ACCOUNTANT, f"Loans with no interest of their own: {len(silent)}",
                              "No interest can be seen for these loans this year. Should we accrue interest (at the "
                              "rate in the loan statement), or are they interest-free?",
                              sum(-_f(t.net_amount) for t in silent),
                              lines=[f"{t.raw_account_name}: {_money(-_f(t.net_amount))}" for t in silent],
                              rule="TB-03"))

    # LN-01: an existing loan with no repayment at all in the year: paid from another account, a payment holiday, or the balance is not right
    unpaid = [t for t in existing
              if not any(l.account == t.raw_account_name and l.code in LOAN_CODES and l.debit >= 1 for l in lines)]
    if unpaid and lines:
        out.append(_query("LN-01", CLIENT, f"Loans with no repayments this year: {len(unpaid)}",
                          "No repayments can be seen on these loans during the year. Were they paid from another "
                          "account (for example personally by the director), is there a payment holiday, or has the "
                          "loan been settled? Please send the lender's statement.",
                          sum(-_f(t.net_amount) for t in unpaid),
                          lines=[f"{t.raw_account_name}: {_money(-_f(t.net_amount))}" for t in unpaid], rule="LN-01"))

    # DL-01: the director's loan overdrawn at the year end (the review works out the s455 tax; the client tells
    # whether it was repaid since)
    dla = sum(balances.get(c, 0.0) for c in DIRECTORS_LOAN_CODES)
    if dla >= 1:
        out.append({**_query("DL-01", CLIENT, f"Director's loan overdrawn at the year end: {_money(dla)}",
                             f"The director's loan account shows the director owing the company {_money(dla)} at "
                             f"{ye}. Has any of this been repaid since? If so, please send the bank statement "
                             "showing the repayment.", dla, rule="DL-01"), "blocking": True})

    # s455 paid on an earlier year's overdrawn loan, still in the books, when the loan is no longer overdrawn: the tax
    # is reclaimed from HMRC and released in the books
    s455 = balances.get(S455_RECOVERABLE, 0.0)
    if s455 >= 1 and dla < 1:
        out.append(_query("DL-01:s455", ACCOUNTANT, f"s455 tax to reclaim: {_money(s455)}",
                          f"{_money(s455)} of s455 tax is in the books ({S455_RECOVERABLE} Corporation tax "
                          f"recoverable) but the director's loan is no longer overdrawn at {ye}. Was the loan repaid? "
                          "If so, reclaim the tax from HMRC (form L2P, or on the CT600A of the year it was repaid) "
                          "and release it in the books.", s455, rule="DL-01"))

    # DL-02: dividends paid: the vouchers and board minutes (the review asks too when they exceed the reserves)
    dividends = sum(balances.get(c, 0.0) for c in DIVIDEND_CODES)
    if dividends >= 1:
        out.append({**_query("DL-02", CLIENT, f"Dividends paid: {_money(dividends)}",
                             f"Please send the dividend vouchers and board minutes for the dividends paid during the "
                             f"year ({_money(dividends)} in total).", dividends, rule="DL-02"), "blocking": True})

    # DL-03: a credit balance on a dividend account
    for t in tb:
        if t.std_code in DIVIDEND_CODES and _f(t.net_amount) <= -1:
            out.append(_query(f"DL-03:{t.raw_account_name}", ACCOUNTANT,
                              f"Credit balance on dividends: {t.raw_account_name} {_money(_f(t.net_amount))}",
                              f"{t.raw_account_name} has a credit balance of {_money(_f(t.net_amount))}. Dividends "
                              "paid are a debit: please confirm the dividends each shareholder actually received.",
                              _f(t.net_amount), rule="DL-03"))

    # DL-05: donations: how much was political (over £2,000 is disclosed in the directors' report and is never
    # deductible for tax)
    donations = balances.get(DONATIONS, 0.0) + balances.get(POLITICAL, 0.0)
    if donations >= 1:
        out.append(_query("DL-05", ACCOUNTANT, f"Donations of {_money(donations)}: any political?",
                          f"Donations of {_money(donations)} were made. Please confirm how much (if any) was political: "
                          "political donations over £2,000 must be disclosed in the directors' report, and none are "
                          "deductible for tax.", donations, rule="DL-05"))
    return out
