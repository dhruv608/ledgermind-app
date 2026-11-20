"""The open client's figures shared by the assistant's tools, and the small formatting helpers they use."""

from datetime import date
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord

MAX_ROWS = 60
CT_SUMMARY = "CT-01"     # the tax computation's summary: shown as its own card on the Review tab, not a review point


def _r(v) -> float:
    return round(float(v or 0.0), 2)


def drcr(v) -> Optional[str]:
    """A balance as the accountant reads it: '£3,263.21 Cr' (a minus sign in a tool result gets misread)."""
    if v is None:
        return None
    v = round(float(v), 2)
    return "£0.00" if abs(v) < 0.005 else f"£{abs(v):,.2f} {'Dr' if v > 0 else 'Cr'}"


def _cut(text: Optional[str], n: int = 300) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "..."


def _date(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


class ClientData:
    """One client's figures, worked out once per question and shared by the tools."""

    def __init__(self, engagement: ClientEngagement, db: Session):
        self.eng, self.db = engagement, db
        self._tb = self._final = self._last = self._chart = None
        self.last_year_source = ""

    @property
    def tb(self) -> List[TBRecord]:
        if self._tb is None:
            self._tb = list(self.db.execute(select(TBRecord).where(TBRecord.engagement_id == self.eng.id)).scalars())
        return self._tb

    @property
    def final(self) -> Dict[int, float]:
        if self._final is None:
            from backend.app.services.tax.ct_computation import final_balances
            self._final = final_balances(str(self.eng.id), self.tb, self.db)
        return self._final

    @property
    def chart(self) -> Dict[int, MasterCOA]:
        if self._chart is None:
            self._chart = {c.std_code: c for c in self.db.execute(select(MasterCOA)).scalars()}
        return self._chart

    @property
    def last_year(self) -> Dict[int, float]:
        """Last year's closing balances by firm code, as the review compares them: last year's client in the app,
        else last year's TB uploaded with this year's files (matched by account name, then code)."""
        if self._last is None:
            from backend.app.services.mapping.chart_lookup import ChartLookup
            from backend.app.services.review.last_year import compare
            out: Dict[int, float] = {}
            try:
                cmp = compare(self.eng, self.tb, ChartLookup(self.db), self.db)
                code_of = {t.raw_account_name: t.std_code for t in self.tb}
                for name, amount in cmp.by_account.items():
                    code = code_of.get(name)
                    if code is not None and amount is not None:
                        out[code] = out.get(code, 0.0) + float(amount)
                for line in cmp.gone:
                    if line.code is not None:
                        out[line.code] = out.get(line.code, 0.0) + float(line.amount)
                self.last_year_source = cmp.source
            except Exception:
                self.db.rollback()
                out = {}
            self._last = out
        return self._last

    def is_pl(self, code: int) -> bool:
        c = self.chart.get(code)
        return bool(c and (c.financial_class or "").lower().startswith("profit"))


def match_accounts(tb: List[TBRecord], text: str) -> List[str]:
    """The client's accounts a name or code means: an exact account name, else a firm code, else an exact firm code
    name, else any account containing the words ('sales' alone must not also take 'Cost of sales')."""
    a = (text or "").strip().lower()
    if not a:
        return []
    for test in (lambda t: (t.raw_account_name or "").strip().lower() == a,
                 lambda t: str(t.std_code) == a,
                 lambda t: (t.std_name or "").strip().lower() == a,
                 lambda t: a in (t.raw_account_name or "").lower() or a in (t.std_name or "").lower()):
        names = sorted({t.raw_account_name for t in tb if test(t)})
        if names:
            return names
    return []

def _codes_for(d: ClientData, account: str) -> List[int]:
    """The firm codes an account name or code means (as match_accounts finds the client's accounts)."""
    names = set(match_accounts(d.tb, account))
    return sorted({t.std_code for t in d.tb if t.raw_account_name in names and t.std_code is not None})
