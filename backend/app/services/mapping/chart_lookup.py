"""
Firm Chart of Accounts lookup.
Answers "is this Sales / P&L / tax?" from the master_coa sections instead of hardcoded number ranges,
and names the firm accounts the review engine posts journals to.
"""

import re
from typing import Dict, Iterable, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.models.database import MasterCOA, TBRecord

# Key firm accounts (codes from the firm's standard chart, COA_Standard)
VAT_CONTROL = 5300
VAT_LONG_TERM = 5700
CT_CREDITOR = 5310
PAYE_NIC = 5320
NET_WAGES = 5330
DIRECTORS_LOAN = 5400
DIRECTORS_LOAN_LONG_TERM = 5800
CT_CHARGE = 3800
CT_RECOVERABLE = 4450
PREPAYMENTS = 4900
PLANT_ADDITIONS = 4121
CLIENT_ENTERTAINING = 3385
REPAIRS_GENERAL_ADMIN = 3250
INSURANCE = 3260

SALES_SECTIONS = {"Sales"}
TAX_SECTIONS = {"Current tax", "Deferred tax"}
PROFIT_AND_LOSS = "Profit and Loss"

GROSS_WAGES_NAME = re.compile(r"^(wages and salaries|directors' salaries)", re.IGNORECASE)
DISALLOWABLE_FINES_NAME = re.compile(r"\b(fines?|penalt(y|ies)|late payment tax)\b", re.IGNORECASE)


def account_name_keys(raw_name: str) -> list:
    """Name variants used to match the same account across TB and GL ('2305 - Directors Loan' / 'Bank:Current' -> leaf),
    most exact first: 'Sub-Contractors:J Smith' must find its own account before any other 'J Smith'."""
    full = (raw_name or "").lower().strip()
    keys = [full, re.sub(r"^\d+[\s\-_:]+", "", full).strip(), full.split(":")[-1].strip(),
            # A TB writing the firm's code before the client's ('5200 - 800 - Creditors') against a ledger that names
            # the account alone ('Creditors')
            re.sub(r"^(?:\d+[\s\-_:]+)+", "", full).strip()]
    return list(dict.fromkeys(k for k in keys if k))


# Control accounts known by name when the TB leaves them out (nil at the year end): their ledger lines still belong on
# the net wages / PAYE / pension / VAT tabs
CONTROL_NAMES = [
    (re.compile(r"^(net wages|wages (payable|control)( - payroll)?|salar(y|ies) (payable|control)|net pay( payable)?)$"), NET_WAGES),
    (re.compile(r"^(paye( (and|&) n\.?i\.?c?s?)?|paye (payable|liabilit(y|ies)|control)|n\.?i\.?c? payable|"
                r"hmrc ?- ?paye|paye ?/ ?nic?)$"), PAYE_NIC),
    (re.compile(r"^(pensions? (payable|creditors?|liabilit(y|ies)|control)|nest( pension)?)$"), 5352),
    (re.compile(r"^(vat|vat (control|liabilit(y|ies)|payable)|vat control account)$"), VAT_CONTROL),
]


FOREIGN_TAX_NAME = re.compile(r"foreign|overseas|japan|withholding|double tax", re.I)
PAYE_NAME = re.compile(r"\bpaye\b|\bnic?s?\b|national insurance|hmrc", re.I)


def foreign_tax_on_paye_code(tb_records) -> Optional[str]:
    """The client's name for the PAYE code (5320) when every account on it is named for a foreign or overseas tax and
    none for PAYE: then it holds tax owed abroad, not PAYE (e.g. 'Foreign tax (BS)'). None otherwise."""
    names = [t.raw_account_name or "" for t in tb_records if t.std_code == PAYE_NIC]
    if names and all(FOREIGN_TAX_NAME.search(n) and not PAYE_NAME.search(n) for n in names):
        return names[0]
    return None


def _link_by_total(codes: "ControlAccountCodes", tb_records: list) -> None:
    """Ledger accounts whose name matches no TB account, linked to the TB account with exactly the same total: the
    ledger and the TB name one account differently (ledger '404 Net Salary Expense', TB 'Wages', same total). One to
    one only: equal to the penny, the total unique among the unlinked ledger accounts and among the TB accounts no
    ledger name reaches. A TB grouping several ledger accounts into one line is not linked here."""
    from sqlalchemy import func
    from sqlalchemy.orm import object_session
    from backend.app.models.database import GLTransaction
    if not tb_records:
        return
    try:
        db = object_session(tb_records[0])
    except Exception:
        return                       # not a database row (built in memory): nothing to read
    if db is None:
        return
    try:
        rows = db.execute(select(GLTransaction.raw_account_name,
                                 func.sum(GLTransaction.debit_amount) - func.sum(GLTransaction.credit_amount))
                          .where(GLTransaction.engagement_id == tb_records[0].engagement_id)
                          .group_by(GLTransaction.raw_account_name)).all()
    except Exception:
        return
    if not rows:
        return
    from backend.app.services.sop.common import code_matcher
    code_of = code_matcher(codes)
    unlinked: Dict[float, list] = {}
    reached = set()                  # the name keys of TB accounts some ledger name already reaches
    for name, total in rows:
        if not name:
            continue
        if code_of(name) is None:
            unlinked.setdefault(round(float(total or 0), 2), []).append(name)
        else:
            parts = [p.strip() for p in name.lower().split(":")]
            reached.update(account_name_keys(name))
            reached.update(":".join(parts[:i]) for i in range(len(parts) - 1, 0, -1))
    free: Dict[float, list] = {}
    for tb in tb_records:
        if tb.std_code is None or not tb.raw_account_name:
            continue
        if any(k in reached for k in account_name_keys(tb.raw_account_name)):
            continue
        free.setdefault(round(float(tb.net_amount or 0), 2), []).append(tb)
    for total, names in unlinked.items():
        if abs(total) < 1 or len(names) != 1 or len(free.get(total, [])) != 1:
            continue
        for key in account_name_keys(names[0]):
            codes.setdefault(key, free[total][0].std_code)


class ControlAccountCodes(dict):
    """GL account name -> firm code, from the TB; for a name the TB does not have, a payroll / VAT control account
    is recognised by its name (anything else stays unknown). 'ambiguous': names the TB gives two different codes
    (a QuickBooks sub-account name used under two parents, e.g. 'J Smith' under Sales and under Sub-Contractors)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.ambiguous: set = set()

    def _by_name(self, key: str) -> Optional[int]:
        name = re.sub(r"\s+", " ", (key or "").strip().lower())
        return next((code for pattern, code in CONTROL_NAMES if pattern.match(name)), None)

    def __contains__(self, key) -> bool:
        return dict.__contains__(self, key) or (isinstance(key, str) and self._by_name(key) is not None)

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        code = self._by_name(key) if isinstance(key, str) else None
        if code is None:
            raise KeyError(key)
        return code

    def get(self, key, default=None):
        return self[key] if key in self else default


class ChartLookup:
    def __init__(self, db: Session):
        self.accounts: Dict[int, MasterCOA] = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars().all()}

    def section(self, code: Optional[int]) -> Optional[str]:
        c = self.accounts.get(code) if code is not None else None
        return c.category if c else None

    def name(self, code: Optional[int], default: str = "") -> str:
        c = self.accounts.get(code) if code is not None else None
        return c.std_name if c else default

    def is_pl(self, code: Optional[int]) -> bool:
        c = self.accounts.get(code) if code is not None else None
        return bool(c and c.financial_class == PROFIT_AND_LOSS)

    def is_sales(self, code: Optional[int]) -> bool:
        return self.section(code) in SALES_SECTIONS

    def is_pre_tax_pl(self, code: Optional[int]) -> bool:
        """P&L account that counts towards profit before tax (everything in P&L except the tax charge)."""
        return self.is_pl(code) and self.section(code) not in TAX_SECTIONS

    def is_gross_wages(self, code: Optional[int]) -> bool:
        return bool(GROSS_WAGES_NAME.match(self.name(code)))

    def is_depreciation(self, code: Optional[int]) -> bool:
        return self.is_pl(code) and "depreciation" in self.name(code).lower()

    def is_disallowable_fine(self, code: Optional[int]) -> bool:
        return self.is_pl(code) and bool(DISALLOWABLE_FINES_NAME.search(self.name(code)))

    def is_fixed_asset_addition(self, code: Optional[int]) -> bool:
        return self.section(code) == "Tangible assets" and "additions" in self.name(code).lower()

    # --- Totals over a trial balance (net = debit - credit, so income and liabilities are negative) ---

    @staticmethod
    def _net(tb: TBRecord) -> float:
        return float(tb.net_amount or 0.0)

    def turnover(self, tb_records: Iterable[TBRecord]) -> float:
        return round(-sum(self._net(tb) for tb in tb_records if self.is_sales(tb.std_code)), 2)

    def profit_before_tax(self, tb_records: Iterable[TBRecord]) -> float:
        return round(-sum(self._net(tb) for tb in tb_records if self.is_pre_tax_pl(tb.std_code)), 2)

    def balance(self, tb_records: Iterable[TBRecord], *codes: int) -> float:
        return round(sum(self._net(tb) for tb in tb_records if tb.std_code in codes), 2)

    def total_where(self, tb_records: Iterable[TBRecord], predicate) -> float:
        return round(sum(self._net(tb) for tb in tb_records if predicate(tb.std_code)), 2)

    @staticmethod
    def gl_account_codes(tb_records: Iterable[TBRecord]) -> Dict[str, int]:
        """Map GL account names (which often lack the TB's '7100 - ' prefix) to the TB's mapped firm code. A ledger
        account the TB leaves out (a control account that ended the year at nil: Xero lists no zero balances) is
        known by its name when it is a payroll or VAT control account (ControlAccountCodes). A ledger account whose
        name matches no TB account is linked by its total (_link_by_total)."""
        tb_records = list(tb_records)
        codes = ControlAccountCodes()
        for tb in tb_records:
            if tb.std_code is None or not tb.raw_account_name:
                continue
            for key in account_name_keys(tb.raw_account_name):
                if key in codes and dict.get(codes, key) not in (None, tb.std_code):
                    codes.ambiguous.add(key)       # e.g. a name under Sales (0) and under Sub-Contractors (1440)
                codes.setdefault(key, tb.std_code)
        _link_by_total(codes, tb_records)
        return codes
