"""
CIS (Construction Industry Scheme), first part: the firm's CIS codes, the rule that switches the module on, and the
first checks.

The module is on when a client account is mapped to a CIS tax code: 4421 CIS suffered (the client is a
subcontractor: its customers deduct CIS) or 5321 CIS deducted (the client is a contractor: it deducts CIS from its
subcontractors). CIS labour income or subcontractor costs with no CIS tax account is a query; wages carrying CIS
payments are subcontractor costs (1440), not wages.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.database import MasterCOA, TBRecord

log = logging.getLogger(__name__)

CIS_SUFFERED = 4421       # CIS suffered - recoverable from HMRC (subcontractor side)
CIS_DEDUCTED = 5321       # CIS deducted - payable to HMRC (contractor side)
SUBCONTRACTOR_COSTS = 1440
SUBCONTRACTOR_COST_CODES = (1440, 2440, 3020)    # subcontractor costs: cost of sales, distribution, employee costs
SUBCONTRACTOR_MIN = 1000.0
WAGES = 1500              # Wages and salaries (cost of sales)
CIS_TEXT = re.compile(r"\bcis\b", re.I)

# The two CIS codes (unused TaxCalc codes 4421 and 5321): each takes its parent's chart section
CIS_CODES = {
    CIS_SUFFERED: ("CIS suffered - recoverable from HMRC (Debtors < 1 year)", 4420),
    CIS_DEDUCTED: ("CIS deducted - payable to HMRC (Current liabilities - creditors < 1 year)", 5320),
}


def ensure_cis_codes(db: Session) -> List[int]:
    """Adds the CIS codes to the firm chart when missing (the chart is loaded once by a script, so a new code has to
    be added here to reach the live database). 4421 replaces the unused extended placeholder 'Other debtors (1)'."""
    changed = []
    for code, (name, parent_code) in CIS_CODES.items():
        parent = db.get(MasterCOA, parent_code)
        row = db.get(MasterCOA, code)
        if parent is None or (row is not None and row.std_name == name and not row.is_extended):
            continue
        if row is not None and not (row.std_name or "").lower().startswith(("other debtors", "other taxes", "cis ")):
            log.warning("CIS code %s is used for '%s' in the chart: left as it is", code, row.std_name)
            continue
        if row is None:
            row = MasterCOA(std_code=code)
            db.add(row)
        row.std_name, row.category, row.financial_class = name, parent.category, parent.financial_class
        row.normal_balance, row.lead_schedule_ref, row.is_extended = parent.normal_balance, parent.lead_schedule_ref, False
        row.sub_tags = '["cis"]'
        changed.append(code)
    if changed:
        db.commit()
    return changed


def ensure_cis_codes_at_start() -> None:
    """At server start: never stops the server (a database not ready yet is tried again at the next start)."""
    from backend.app.core.database import SessionLocal
    db = SessionLocal()
    try:
        added = ensure_cis_codes(db)
        if added:
            log.info("CIS codes added to the firm chart: %s", added)
    except Exception as e:      # e.g. the chart table not created yet on a new database
        db.rollback()
        log.warning("CIS codes not checked at start: %s", e)
    finally:
        db.close()


# ------------------------------------------------------------------------------------------------------------------
# Which side(s) of CIS the books show
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class CisSides:
    suffered: List[str] = field(default_factory=list)       # accounts mapped to 4421
    deducted: List[str] = field(default_factory=list)       # accounts mapped to 5321
    labour_sales: List[str] = field(default_factory=list)   # sales accounts named for CIS labour
    labour_cost: List[str] = field(default_factory=list)    # subcontractor cost accounts named for CIS

    @property
    def on(self) -> bool:
        return bool(self.suffered or self.deducted)

    @property
    def role(self) -> str:
        """The role the books suggest, as the setup's CIS status."""
        if self.suffered and self.deducted:
            return "BOTH"
        if self.deducted:
            return "CONTRACTOR"
        if self.suffered:
            return "SUBCONTRACTOR"
        return "NONE"

    def as_dict(self) -> Dict[str, Any]:
        return {"on": self.on, "role": self.role, "suffered": self.suffered, "deducted": self.deducted,
                "labour_sales": self.labour_sales, "labour_cost": self.labour_cost}


def _moves(t: TBRecord) -> bool:
    return any(abs(float(v or 0)) >= 0.005 for v in (t.net_amount, t.debit_amount, t.credit_amount, t.opening_amount))


def cis_sides(tb_records: Iterable[TBRecord], sales_codes: Iterable[int] = ()) -> CisSides:
    sales = set(sales_codes) or {0}
    out = CisSides()
    for t in tb_records:
        if not _moves(t):
            continue
        name = t.raw_account_name or ""
        if t.std_code == CIS_SUFFERED:
            out.suffered.append(name)
        elif t.std_code == CIS_DEDUCTED:
            out.deducted.append(name)
        elif t.std_code in sales and CIS_TEXT.search(name):
            out.labour_sales.append(name)
        elif t.std_code == SUBCONTRACTOR_COSTS and CIS_TEXT.search(name):
            out.labour_cost.append(name)
    return out


# ------------------------------------------------------------------------------------------------------------------
# First checks (rules 1 and 4, test T8)
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class CisPoint:
    ref: str
    severity: str
    title: str
    details: str
    amount: float = 0.0


def cis_points(tb_records: List[TBRecord], lines: Iterable[Any], sales_codes: Iterable[int], role: Optional[str]) -> List[CisPoint]:
    """lines: the ledger lines (GLLine: when, code, account, debit, credit, description, ...)."""
    sides = cis_sides(tb_records, sales_codes)
    points: List[CisPoint] = []

    # CIS-003: subcontractor costs in the accounts and no CIS account in
    # the ledger: is the client in CIS? (A contractor must deduct CIS from subcontractors, FA04 s61)
    sub = [(t.raw_account_name or "", float(t.net_amount or 0)) for t in tb_records
           if t.std_code in SUBCONTRACTOR_COST_CODES and float(t.net_amount or 0) >= SUBCONTRACTOR_MIN]
    if not sides.on and not (sides.labour_sales or sides.labour_cost) and sub and role is None:     # not yet answered on the setup
        total = round(sum(v for _n, v in sub), 2)
        points.append(CisPoint(
            "CIS-003", "LOW", f"Subcontractor costs £{total:,.2f} and no CIS account: is the client in CIS?",
            f"{', '.join(n for n, _v in sub[:5])} hold £{total:,.2f} of subcontractor costs, and no account is mapped to "
            f"{CIS_SUFFERED} CIS suffered or {CIS_DEDUCTED} CIS deducted. A business in construction that pays "
            f"subcontractors must register as a contractor and deduct CIS. Client question: Are the subcontractors paid "
            f"for construction work, and is the business registered for CIS?", total))

    # Rule 1: CIS labour in the books but no CIS tax account
    if not sides.on and (sides.labour_sales or sides.labour_cost):
        names = sides.labour_sales + sides.labour_cost
        points.append(CisPoint(
            "CIS-001", "MEDIUM", "CIS labour recorded but no CIS tax account: are deductions being recorded?",
            f"Accounts named for CIS labour: {', '.join(names[:5])}. No account is mapped to {CIS_SUFFERED} CIS suffered "
            f"or {CIS_DEDUCTED} CIS deducted, so the CIS module cannot reconcile to HMRC. Map the CIS tax accounts, or "
            f"confirm with the client that no CIS was deducted."))

    # Rule 4 / T8: wages carrying CIS payments are subcontractor costs
    by_account: Dict[str, List[Any]] = {}
    for l in lines:
        if l.code == WAGES:
            by_account.setdefault(l.account, []).append(l)
    for account, rows in by_account.items():
        flagged = [l for l in rows if CIS_TEXT.search(l.description or "")]
        if not flagged or len(flagged) < 0.5 * len(rows):
            continue
        balance = round(sum(l.debit - l.credit for l in rows), 2)
        cis_paid = round(sum(l.debit - l.credit for l in flagged), 2)
        points.append(CisPoint(
            "CIS-T8", "HIGH", f"Wages carrying CIS: remap £{balance:,.2f} '{account}' from Wages ({WAGES}) to "
                              f"Subcontractor costs ({SUBCONTRACTOR_COSTS})",
            f"{len(flagged)} of the {len(rows)} lines on '{account}' say CIS (£{cis_paid:,.2f}), e.g. "
            f"'{flagged[0].description}'. Payments under CIS are subcontractor costs, not wages: they stay out of staff "
            f"costs and the average number of employees. Remap the account on the Accounts tab.", balance))

    # The setup says no CIS but the books have CIS tax accounts
    if sides.on and role == "NONE":
        points.append(CisPoint(
            "CIS-002", "HIGH", "CIS accounts in the books, but the setup says the client is not in CIS",
            f"Mapped to CIS: {', '.join((sides.suffered + sides.deducted)[:5])}. The books suggest: {sides.role.lower()}. "
            f"Answer the CIS questions on the Setup tab."))
    return points
