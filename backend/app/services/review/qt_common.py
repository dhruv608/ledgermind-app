"""Query triggers, the shared parts: the rules file, thresholds, the context a test reads, the money and line helpers
and the register the tests add themselves to."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord
from backend.app.services.sop.common import GLLine

RULES = Path(__file__).resolve().parents[2] / "rules"
VAT_REGISTRATION_THRESHOLD = 90000.0        # from 1 April 2024
FLAT_RATE_LEAVE_THRESHOLD = 230000.0
SALES_SECTIONS = {"Sales"}
INCOME_SECTIONS = {"Sales", "Other operating income", "Interest receivable and similar income"}


@dataclass
class Hit:
    title: str
    details: str
    amount: float = 0.0
    lines: List[str] = field(default_factory=list)
    # The point's figures as a small table for the screen (review/point_figures.py), when known
    figures: Optional[str] = None


@dataclass
class Ctx:
    engagement: ClientEngagement
    tb_records: List[TBRecord]
    chart: Dict[int, MasterCOA]
    bal: Dict[int, float]
    lines: List[GLLine]
    record: Dict[str, Any]
    db: Session

    def section(self, code: Optional[int]) -> str:
        c = self.chart.get(code) if code is not None else None
        return (c.category or "") if c else ""

    def is_pl(self, code: Optional[int]) -> bool:
        c = self.chart.get(code) if code is not None else None
        return bool(c and c.financial_class == "Profit and Loss")

    def name(self, code: int) -> str:
        c = self.chart.get(code)
        return c.std_name if c else f"Account {code}"

    @property
    def sales(self) -> float:
        return -sum(v for k, v in self.bal.items() if self.section(k) in SALES_SECTIONS)


def _money(v: float) -> str:
    return f"£{abs(v):,.2f}"


def _balances_figures(found) -> Optional[str]:
    """Accounts and their balances (credits in brackets), for a point that lists them."""
    from backend.app.services.review.point_figures import row, table
    return table(["Account", "Balance"], [row(n, v) for n, v in found])


def _lines_figures(found) -> Optional[str]:
    """Ledger lines (date, account, description, amount), for a point that lists them."""
    from backend.app.services.review.point_figures import row, table
    return table(["Description", "Date", "Account", "Amount"],
                 [row((l.description or l.source or "")[:60], f"{l.when:%d/%m/%Y}", l.account, l.debit - l.credit) for l in found])


def _line(l: GLLine) -> str:
    amt = l.debit - l.credit
    return f"{l.when:%d/%m/%Y}  {l.account}  {(l.description or l.source)[:70]}  {'+' if amt < 0 else ''}{_money(amt)}"
TESTS: Dict[str, Callable[[Ctx, Dict[str, Any]], Optional[Hit]]] = {}


def test(name: str):
    def register(fn):
        TESTS[name] = fn
        return fn
    return register


# ---------------------------------------------------------------------------------------------------------------
# General tests, set up per query in the rules file
# ---------------------------------------------------------------------------------------------------------------
def _where(ctx: Ctx, l: GLLine, where: str) -> bool:
    if where == "pl":
        return ctx.is_pl(l.code)
    if where == "bs":
        return not ctx.is_pl(l.code)
    if where == "income":
        return ctx.section(l.code) in INCOME_SECTIONS
    if where == "expense":
        return ctx.is_pl(l.code) and ctx.section(l.code) not in INCOME_SECTIONS
    if where == "fixed_assets":       # additions to a fixed asset account (not its depreciation)
        return ctx.section(l.code) == "Tangible assets" and "depreciation" not in ctx.name(l.code).lower()
    if where == "overheads":          # costs other than cost of sales (a restaurant's supermarket stock is not personal)
        return ctx.is_pl(l.code) and ctx.section(l.code) not in INCOME_SECTIONS | {"Cost of sales"}
    return True


def _has_balance(ctx: Ctx, codes=(), sections=(), names: str = "") -> bool:
    pat = re.compile(names, re.I) if names else None
    for t in ctx.tb_records:
        if abs(ctx.bal.get(t.std_code, 0.0)) < 0.005:
            continue
        if t.std_code in codes or ctx.section(t.std_code) in sections or (pat and pat.search(t.raw_account_name or "")):
            return True
    return False


# ---------------------------------------------------------------------------------------------------------------
# Tests for the industry queries (restaurant, construction...)
# ---------------------------------------------------------------------------------------------------------------
def _matching(ctx: Ctx, p: Dict[str, Any]) -> List[GLLine]:
    """The lines keyword_lines would find (without its 'unless' conditions)."""
    words = re.compile(p["words"], re.I)
    exclude = re.compile(p["exclude"], re.I) if p.get("exclude") else None
    side, where = p.get("side", "any"), p.get("where", "any")
    out = []
    for l in ctx.lines:
        if max(l.debit, l.credit) < 1 or ctx.section(l.code) == "Cash at bank and in hand":
            continue
        if side == "out" and l.debit <= 0 or side == "in" and l.credit <= 0:
            continue
        text = f"{l.description} {l.account}"
        if words.search(text) and not (exclude and exclude.search(text)) and _where(ctx, l, where):
            out.append(l)
    return out


def _payee(l: GLLine) -> str:
    return re.sub(r"[^a-z ]", "", (l.description or "").lower().split(" - ")[0])[:30].strip()
