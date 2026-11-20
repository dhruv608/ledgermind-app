"""Control accounts screen, the shared parts: statuses and sections, the row record, the figures typed on the screen,
the order of the rows and the summary."""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.services.workbook.balance_tabs import CURRENCY, S455_CODES
from backend.app.services.mapping.chart_lookup import VAT_CONTROL

# Employer NI and employer pension costs: employee costs (staff, directors), cost of sales, distribution
EMPLOYER_NI_CODES = (3001, 3011, 1451, 1501, 2451, 2501)
EMPLOYER_PENSION_CODES = (3002, 3003, 3012, 3013, 1452, 1453, 1502)
TOLERANCE = 1.0          # differences under £1 count as agreed (rounding), as in the review's checks
MATCHED, DIFFERENCE, NEEDS_INPUT = "MATCHED", "DIFFERENCE", "NEEDS_INPUT"
TRADE_DEBTORS, TRADE_CREDITORS, CT_CHARGE = 4400, 5200, 3800
# The screen reads as the balance sheet does (every balance sheet code on it), then the accounts
# that must be nil, then the checks on profit and loss figures (payroll, the tax charge)
FIXED, CURRENT, CURRENT_LIAB, LONG_LIAB, CAPITAL, NIL, PL_CHECKS = (
    "Fixed assets", "Current assets", "Current liabilities", "Long-term liabilities", "Capital and reserves",
    "Must be nil", "Profit and loss checks")
SECTIONS = (FIXED, CURRENT, CURRENT_LIAB, LONG_LIAB, CAPITAL, NIL, PL_CHECKS)
CATEGORY_SECTION = {
    "Intangible assets": FIXED, "Tangible assets": FIXED, "Investments": FIXED,
    "Stock": CURRENT, "Debtors < 1 year": CURRENT, "Debtors > 1 year": CURRENT, "Current assets - investments": CURRENT,
    "Cash at bank and in hand": CURRENT, "Prepayments and accrued income": CURRENT,
    "Hire purchase and Finance Leases": CURRENT_LIAB, "Current liabilities - creditors < 1 year": CURRENT_LIAB,
    "Long term liabilities - creditors > 1 year": LONG_LIAB, "Provisions and liabilities": LONG_LIAB,
    "Share capital": CAPITAL, "Share premium account": CAPITAL, "Revaluation reserve": CAPITAL,
    "Capital redemption reserve": CAPITAL, "Profit and loss account": CAPITAL, "Suspense and misposting": NIL,
}
SUSPENSE_CODE, TRANSFERS_CODE = 9999, 9998
# What an account with no figure of its own to agree to is agreed to: by the words of its name, first match
SUPPORT = [(re.compile(p, re.I), what) for p, what in (
    (r"accru", "Accruals schedule"),
    (r"prepay|accrued income", "Prepayments schedule"),
    (r"hire purchase|finance lease|\bhp\b", "Finance agreement statement"),
    (r"director", "Director's loan account, confirmed by the director"),
    (r"paye|national insurance|social security", "HMRC PAYE account statement at the year end"),
    (r"pension", "Pension provider statement"),
    (r"wages|salar|net pay", "Payroll: net pay unpaid at the year end"),
    (r"corporation tax", "Corporation tax computations: tax unpaid"),
    (r"loan|mortgage|overdraft|bounce", "Loan statement at the year end"),
    (r"stock|work in progress", "Stock count at the year end"),
    (r"share premium", "Share allotments (Companies House)"),
    (r"share capital|shares?$|shares? (issued|capital)", "Confirmation statement (Companies House)"),
    (r"deposit", "Deposit agreement or statement"),
    (r"investment", "Investment statement at the year end"),
)]


@dataclass
class Reconciliation:
    key: str
    account: str
    area: str                       # Bank, Tax, Payroll, Balance sheet
    books: float
    compared_with: str              # what the books are agreed to
    other: Optional[float]          # that figure (None: not entered / not uploaded yet)
    difference: Optional[float]
    status: str
    tab: str = ""                   # the workbook tab with the detail
    note: str = ""
    currency: str = ""              # a foreign currency bank account: the statement is in this currency
    entered: Optional[Dict[str, Any]] = None    # what the accountant typed for it (bank statement balance)
    section: str = ""               # where it sits on the balance sheet (SECTIONS)
    last_year: Optional[float] = None           # the same accounts at last year end (None: not known)
    codes: List[int] = field(default_factory=list)  # the firm codes in it
    ticked: bool = False            # the accountant agreed it to its document by hand
    proof: Optional[Dict[str, Any]] = None      # VAT: the line-by-line proof (tax/vat_proof.py)
    balance: Optional[float] = None             # its codes' balance in the books, debit + (books may be turned round)


def _row(key: str, account: str, area: str, books: float, compared_with: str, other: Optional[float], tab: str,
         note: str = "", missing: str = "") -> Reconciliation:
    books = round(books, 2)
    if other is None:
        return Reconciliation(key, account, area, books, compared_with, None, None, NEEDS_INPUT, tab, missing or note)
    diff = round(books - other, 2)
    return Reconciliation(key, account, area, books, compared_with, round(other, 2), diff,
                          MATCHED if abs(diff) < TOLERANCE else DIFFERENCE, tab, note)


# ------------------------------------------------------------------------------------------------------------------
# What the accountant types: bank statement balances (saved by key, "bank:4800")
# ------------------------------------------------------------------------------------------------------------------
def entered_inputs(db: Session, engagement_id: str) -> Dict[str, Dict[str, Any]]:
    from backend.app.models.reconciliation_inputs import ReconciliationInput
    rows = db.query(ReconciliationInput).filter_by(engagement_id=str(engagement_id)).all()
    return {r.key: json.loads(r.value) for r in rows}


def save_input(db: Session, engagement_id: str, key: str, value: Optional[Dict[str, Any]], user_id: Optional[int]) -> None:
    """value None removes the figure."""
    from backend.app.models.reconciliation_inputs import ReconciliationInput
    row = db.query(ReconciliationInput).filter_by(engagement_id=str(engagement_id), key=key).first()
    if value is None:
        if row:
            db.delete(row)
    elif row:
        row.value, row.user_id, row.updated_at = json.dumps(value), user_id, datetime.utcnow()
    else:
        db.add(ReconciliationInput(engagement_id=str(engagement_id), key=key, value=json.dumps(value), user_id=user_id))
    db.commit()


def statement_balance(entered: Optional[Dict[str, Any]]) -> Optional[float]:
    """The statement balance in £: as typed, or a currency balance at the year-end rate (as the F3 tab works it out)."""
    if not entered:
        return None
    if entered.get("balance") is not None:
        return float(entered["balance"])
    amount, rate = entered.get("currency_amount"), entered.get("rate")
    if amount is not None and rate:
        return round(float(amount) / float(rate), 2)
    return None


def bank_currency(label: str) -> str:
    """The currency in a bank account's name ('Revolut USD Main' -> 'USD'), as the F3 tab reads it; '' for sterling."""
    found = CURRENCY.search(label or "")
    return found.group(0).upper().replace("$", "USD").replace("€", "EUR") if found else ""
ROW_CODES = {"vat": {VAT_CONTROL}, "ar": {TRADE_DEBTORS}, "ap": {TRADE_CREDITORS}, "ct": {CT_CHARGE}, "s455": set(S455_CODES),
             "cis_deducted": {5321}, "cis_suffered": {4421}}
ROW_SECTION = {"vat": CURRENT_LIAB, "ar": CURRENT, "ap": CURRENT_LIAB, "s455": CURRENT, "cis_deducted": CURRENT_LIAB,
               "cis_suffered": CURRENT}


def _in_order(rows: List[Reconciliation]) -> List[Reconciliation]:
    """Section by section as the balance sheet reads, each section in code order (its first code)."""
    return sorted(rows, key=lambda r: (SECTIONS.index(r.section) if r.section in SECTIONS else len(SECTIONS),
                                       r.codes[0] if r.codes else 99999))


class LastYear(dict):
    """Each code's balance at last year end, and whether last year's job in the app gave them."""
    def __init__(self, balances: Dict[int, float], from_job: bool = False):
        super().__init__(balances)
        self.from_job = from_job


def by_hand_key(key: str) -> bool:
    """A row the accountant agrees by hand (a typed figure or a tick): every balance sheet code, a fixed asset class
    with no register, retained earnings with no last year's job."""
    return key == "reserves" or key.startswith("code:") or key.startswith("far:") or key in VAT_PROOF_KEYS
VAT_PROOF_KEYS = ("vatproof:exception", "vatproof:adjustments")   # typed lines of the VAT proof


def _same_sign(row: Reconciliation, bal: Dict[int, float], last: float) -> float:
    """Last year's balance (debit +, credit -) shown the way the row shows its books: a row that turns the books round
    (VAT and tax owed as a positive figure, debtors and creditors as amounts) turns last year round too, so this year
    and last year read alike (VAT £9,500 owed against last year's £12,000 owed, not -£12,000)."""
    raw = sum(bal.get(c, 0.0) for c in row.codes)
    turned = abs(raw) >= 0.005 and abs(row.books + raw) < abs(row.books - raw)
    return round(-last if turned else last, 2)


def summary(rows: List[Reconciliation]) -> Dict[str, Any]:
    count = lambda s: sum(1 for r in rows if r.status == s)
    # How much of the balance sheet is agreed, by value (what a reviewer looks at, more than the number of rows)
    sheet = [r for r in rows if r.section not in (PL_CHECKS, NIL, "")]
    return {"accounts": len(rows), "matched": count(MATCHED), "differences": count(DIFFERENCE),
            "needs_input": count(NEEDS_INPUT), "sections": list(SECTIONS),
            "value_total": round(sum(abs(r.books) for r in sheet), 2),
            "value_agreed": round(sum(abs(r.books) for r in sheet if r.status == MATCHED), 2),
            "rows": [asdict(r) for r in rows]}
