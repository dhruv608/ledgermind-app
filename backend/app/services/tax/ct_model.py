"""The corporation tax computation's result (CTLine, CTComputation) and the final balances it is worked from."""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ProposedJournal, TBRecord



@dataclass
class CTLine:
    label: str
    amount: float
    box: str = ""          # CT600 box
    note: str = ""
    # A line worked straight from the final balances: sign x the sum of these codes (floor: never below nil), so the
    # workbook can write it as a formula on B1-ETB
    codes: Tuple[int, ...] = ()
    sign: int = 1
    floor: bool = False


@dataclass
class CTComputation:
    period_start: date
    period_end: date
    days: int
    associated_companies: int
    lines: List[CTLine] = field(default_factory=list)       # the computation, top to bottom
    capital_allowances: List[CTLine] = field(default_factory=list)
    rate_slices: List[Dict] = field(default_factory=list)   # one per financial year in the period
    profit_before_tax: float = 0.0
    trading_profit: float = 0.0
    losses_used: float = 0.0
    losses_carried_forward: float = 0.0
    trading_loss: float = 0.0                   # this year's trading loss (carried forward unless claimed)
    property_profit: float = 0.0                # the property business's profit (negative: a loss), box 190
    property_losses_carried_forward: float = 0.0
    profits_chargeable: float = 0.0
    corporation_tax: float = 0.0
    double_tax_relief: float = 0.0
    s455_tax: float = 0.0
    s455_explanation: str = ""
    total_tax: float = 0.0
    tax_in_accounts: float = 0.0
    main_pool_cf: float = 0.0
    special_pool_cf: float = 0.0
    pools_missing: bool = False                             # assets held last year but no pool brought forward entered
    notes: List[str] = field(default_factory=list)          # things to confirm before the CT600
    ca_assets: List[Dict] = field(default_factory=list)     # each addition: suggested and chosen treatment
    # The capital allowance computation per pool (H1.2): pool, WDV b/f, additions, AIA / FYA,
    # disposals, balancing charge, balancing allowance, WDA, WDV c/f
    pools: List[Dict] = field(default_factory=list)
    goodwill_added_back: float = 0.0                        # goodwill amortisation / impairment added back, unconfirmed

    @property
    def difference_to_accounts(self) -> float:
        return round(self.tax_in_accounts - self.corporation_tax, 2)


def final_balances(engagement_id: str, tb_records: Iterable[TBRecord], db: Session,
                   proposed: Iterable[ProposedJournal] = ()) -> Dict[int, float]:
    """Closing balance per firm code (debit +): the TB plus the journals approved in the app, as on the ETB, plus any
    journals the review is proposing in the same run (proposed), so the tax can come last, on the corrected profit."""
    out: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code is not None:
            out[t.std_code] = out.get(t.std_code, 0.0) + float(t.net_amount or 0.0)
    journals = db.execute(select(ProposedJournal).where(ProposedJournal.engagement_id == engagement_id,
                                                        ProposedJournal.status == "APPROVED")).scalars().all()
    # Each approved journal once, as the workbook's ETB takes them (journal_guard: an approved twin, or one
    # made approved by re-analysis, is not counted twice in the tax, the dividend or s455)
    from backend.app.services.review.journal_guard import once_each
    journals, _twins = once_each(journals)
    for j in list(journals) + list(proposed):
        if j.lines:
            for line in j.lines:
                code = int(line.account_code)
                out[code] = out.get(code, 0.0) + float(line.debit or 0.0) - float(line.credit or 0.0)
        else:
            out[int(j.debit_code)] = out.get(int(j.debit_code), 0.0) + float(j.amount)
            out[int(j.credit_code)] = out.get(int(j.credit_code), 0.0) - float(j.amount)
    return out
