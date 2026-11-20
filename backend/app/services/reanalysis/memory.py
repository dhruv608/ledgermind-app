"""
The reanalysis engine's memory: for a merchant, what this client and
what the firm's other clients did with it.

  C, client history: this client used or approved the code for the merchant at least twice, the latest within two
    years -> 1.0; once, or only in an older year -> 0.5; never, or the accountant rejected that move for this client
    -> 0. It reads this client's stored decisions and last year's ledger in the app (the code each merchant ended on).
  F, firm history: the share of the firm's decisions for the merchant, in other clients of the same industry when
    there are any, that went to the code; under 20% counts as none.

A decision approved in bulk teaches nothing (approving everything at once would teach wrong codes): record() is only
called for decisions made one by one.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Dict, Optional

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, ClientProfile, TBRecord
from backend.app.models.merchant_memory import MerchantMemory
from backend.app.services.ingestion.client_identity import company_key
from backend.app.services.reanalysis.merchants import merchant_of

RECENT = timedelta(days=2 * 366)
FIRM_FLOOR = 0.2
FIRM_CLIENTS = 2


def _industry(engagement: ClientEngagement, db: Session) -> Optional[str]:
    p = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement.id).first()
    code = (p.industry_code if p else None) or None
    return None if code in (None, "", "UNIV") else code


def record(db: Session, engagement: ClientEngagement, merchant_key: str, code: int, outcome: str, source: str,
           user_id: Optional[int], bulk: bool = False) -> None:
    """Keep one decision made by an accountant (outcome APPROVED or REJECTED). Bulk decisions are not kept."""
    if bulk or not merchant_key:
        return
    db.add(MerchantMemory(owner_user_id=engagement.owner_user_id, client_key=company_key(engagement.client_name),
                          engagement_id=str(engagement.id), period_end=engagement.period_end_date,
                          industry=_industry(engagement, db), merchant_key=merchant_key, code=int(code),
                          outcome=outcome, source=source, made_by=user_id))
    db.commit()


def _last_year_ledger(engagement: ClientEngagement, db: Session) -> Dict[str, Counter]:
    """merchant -> codes its lines ended on in last year's job in the app (the prior-year coding)."""
    from backend.app.services.review.last_year import last_year_job
    from backend.app.services.sop.common import gl_lines
    last = last_year_job(engagement, db)
    if last is None:
        return {}
    tb = db.query(TBRecord).filter(TBRecord.engagement_id == last.id).all()
    out: Dict[str, Counter] = defaultdict(Counter)
    for line in gl_lines(str(last.id), tb, db):
        if line.code is None:
            continue
        m = merchant_of(line.description or line.account or "")
        if m.key:
            out[m.key][line.code] += 1
    return out


class Memory:
    """Everything the engine needs to score one job's lines, read once."""

    def __init__(self, engagement: ClientEngagement, db: Session):
        self.client = company_key(engagement.client_name)
        self.year_end: date = engagement.period_end_date
        rows = db.query(MerchantMemory).filter(MerchantMemory.owner_user_id == engagement.owner_user_id).all()
        industry = _industry(engagement, db)
        self.own = [r for r in rows if r.client_key == self.client]
        others = [r for r in rows if r.client_key != self.client and r.outcome in ("APPROVED", "SEED")]
        same = [r for r in others if industry and r.industry == industry]
        self.firm_rows = same or others
        self.last_year = _last_year_ledger(engagement, db)

    def client_score(self, merchant_key: str, code: int) -> float:
        mine = [r for r in self.own if r.merchant_key == merchant_key and r.code == code]
        if any(r.outcome == "REJECTED" for r in mine):
            return 0.0
        uses = [r.period_end for r in mine if r.outcome in ("APPROVED", "SEED")]
        last_year = self.last_year.get(merchant_key, Counter())[code]
        times = len(uses) + (1 if last_year else 0) + (1 if last_year >= 2 else 0)
        if times == 0:
            return 0.0
        recent = any(d and self.year_end - d <= RECENT for d in uses) or last_year > 0
        return 1.0 if times >= 2 and recent else 0.5

    def firm_score(self, merchant_key: str, code: int) -> float:
        rows = [r for r in self.firm_rows if r.merchant_key == merchant_key]
        # One other client's choice is that client's habit, not the firm's (a personal Barclaycard is not every
        # client's Barclays): the firm counts from two clients
        if len({r.client_key for r in rows}) < FIRM_CLIENTS:
            return 0.0
        votes = Counter(r.code for r in rows)
        total = sum(votes.values())
        share = votes[code] / total
        return share if share >= FIRM_FLOOR else 0.0

    def candidates(self, merchant_key: str) -> Counter:
        """Codes the memory knows for the merchant (from this client, last year, or the firm)."""
        out: Counter = Counter()
        for r in self.own:
            if r.merchant_key == merchant_key and r.outcome != "REJECTED":
                out[r.code] += 1
        out.update(self.last_year.get(merchant_key, Counter()))
        firm = [r for r in self.firm_rows if r.merchant_key == merchant_key]
        if len({r.client_key for r in firm}) >= FIRM_CLIENTS:
            out.update(r.code for r in firm)
        return out
