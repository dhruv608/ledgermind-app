"""
Capital v revenue, the AI step: purchases the keyword check cannot read because the ledger only
names the shop ('Hoxton Macs', 'Ballicom', 'Amazon'), asked of the AI as "asset or running cost?".

Candidates are found by the shape of the books, not by words: a P&L overhead (or a cost of sales account other than the
goods bought to sell) at or over the client's capitalisation limit, not in an account for hiring or running assets,
with no running-cost words, not already flagged by the keywords, and a one-off for its account: the supplier appears
fewer than 3 times there in the year, or this line is at least 3 times that supplier's usual line (a big Amazon order).
The AI's 'asset' and 'not sure' answers become questions for the accountant, never journals; its 'running cost'
answers drop the line. Answers are kept per line (ai_answers), so a review run asks only about new lines.
"""

import json
import logging
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import MasterCOA
from backend.app.services.sop.capital import CAPITAL_EXCLUSIONS, NOT_CAPITAL_SOURCES, RUNNING_ACCOUNTS
from backend.app.services.sop.common import GLLine, PAYROLL_CODES

log = logging.getLogger(__name__)

OVERHEADS = ("General admin", "Premises expenses", "Distribution costs", "Other operating and exceptional costs")
GOODS_TO_SELL = re.compile(r"\b(purchases|materials|subcontract\w*|carriage)\b", re.I)   # cost of sales that is the product
MAX_ASKED = 40                      # the largest lines of a job, one AI call
KIND = "capital"


@dataclass
class AICapitalFlag:
    when: object
    code: int
    account: str
    description: str
    amount: float
    verdict: str                    # "asset" or "unsure"
    asset_class: str
    reason: str


def _supplier(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower().split(" - ")[0])[:12]


def _key(l: GLLine) -> str:
    return f"{l.when:%Y-%m-%d}|{l.debit:.2f}|{l.code}|{(l.description or '')[:200]}"


def candidates(lines: Iterable[GLLine], chart: Dict[int, MasterCOA], limit: float, flagged: Set[Tuple]) -> List[GLLine]:
    """The one-off P&L purchases worth asking about (see the module note). flagged: (date, amount) of keyword flags."""
    def eligible(l: GLLine) -> bool:
        c = chart.get(l.code)
        if c is None or c.financial_class != "Profit and Loss" or l.code in PAYROLL_CODES:
            return False
        if not (c.category in OVERHEADS or (c.category == "Cost of sales" and not GOODS_TO_SELL.search(c.std_name or ""))):
            return False
        return not RUNNING_ACCOUNTS.search(c.std_name or "") and not any(s in (l.source or "").lower() for s in NOT_CAPITAL_SOURCES)

    pl = [l for l in lines if l.debit > 0 and eligible(l)]
    by_supplier: Dict[Tuple[int, str], List[float]] = defaultdict(list)
    for l in pl:
        by_supplier[(l.code, _supplier(l.description))].append(l.debit)
    out = []
    for l in pl:
        if l.debit < limit or CAPITAL_EXCLUSIONS.search(l.description or "") or (l.when, round(l.debit, 2)) in flagged:
            continue
        seen = by_supplier[(l.code, _supplier(l.description))]
        if len(seen) < 3 or l.debit >= 3 * statistics.median(seen):
            out.append(l)
    return sorted(out, key=lambda l: -l.debit)[:MAX_ASKED]


def _ask(lines: List[GLLine], chart: Dict[int, MasterCOA], business: str) -> Dict[int, dict]:
    from backend.app.core.bedrock import bedrock_ai
    rows = "\n".join(f'{i}. £{l.debit:,.2f} on {l.when:%d/%m/%Y}, account "{chart[l.code].std_name}", ledger text "{(l.description or "")[:160]}"'
                     for i, l in enumerate(lines))
    prompt = f"""You are a UK chartered accountant reviewing a client's expenses for items that should be fixed assets.
The client's business: {business or "not known"}.

Each line below was posted to an expense account. The ledger text is often only the shop or supplier name: use what you
know about the supplier (for example a Mac reseller, a computer distributor, a furniture shop) and the amount.
- "asset": most likely equipment, furniture, computers, phones, machinery, vehicles or similar that lasts more than a
  year and is used in the business.
- "cost": most likely a running cost: consumables, stock for resale, subscriptions, repairs, fees, and any service
  (photography, design and branding, consultancy, marketing, cleaning, installation labour on its own), even when
  the amount is large.
- "unsure": cannot tell (for example a marketplace like Amazon with no item named, for an amount that could be either).

{rows}

Reply with a JSON array only, one object per line:
[{{"i": 0, "verdict": "asset" | "cost" | "unsure", "asset_class": "computer equipment | office equipment | furniture | plant and machinery | motor vehicle | other | none", "reason": "one short sentence"}}]"""
    raw, model = bedrock_ai.invoke_model_reporting(prompt, max_tokens=120 * len(lines) + 200, temperature=0)
    if not isinstance(raw, str):
        return {}
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return {}
    answers = {}
    for a in json.loads(raw[start:end + 1]):
        if isinstance(a, dict) and isinstance(a.get("i"), int) and 0 <= a["i"] < len(lines):
            answers[a["i"]] = {**a, "model": model}
    return answers


def ai_capital_review(engagement_id: str, lines: List[GLLine], chart: Dict[int, MasterCOA], limit: float,
                      flagged: Set[Tuple], business: str, db: Session) -> List[AICapitalFlag]:
    """The AI's 'asset' and 'unsure' answers on this job's candidates, asking only about lines not asked before."""
    from backend.app.models.ai_answers import AIAnswer
    cands = candidates(lines, chart, limit, flagged)
    if not cands:
        return []
    kept = {r.key: json.loads(r.answer) for r in db.query(AIAnswer).filter(
        AIAnswer.engagement_id == engagement_id, AIAnswer.kind == KIND, AIAnswer.key.in_([_key(l) for l in cands]))}
    new = [l for l in cands if _key(l) not in kept]
    if new:
        try:
            answers = _ask(new, chart, business)
        except Exception as e:          # no AI (tests, an outage): the keyword check still runs, nothing is guessed
            log.warning("Capital AI check skipped: %s", e)
            answers = {}
        for i, l in enumerate(new):
            if i in answers:
                kept[_key(l)] = answers[i]
                db.add(AIAnswer(engagement_id=engagement_id, kind=KIND, key=_key(l), answer=json.dumps(answers[i]),
                                model=answers[i].get("model")))
        if answers:
            db.commit()
    out = []
    for l in cands:
        a: Optional[dict] = kept.get(_key(l))
        if not a or a.get("verdict") not in ("asset", "unsure"):
            continue
        out.append(AICapitalFlag(when=l.when, code=l.code, account=l.account, description=l.description or "",
                                 amount=round(l.debit, 2), verdict=a["verdict"],
                                 asset_class=str(a.get("asset_class") or ""), reason=str(a.get("reason") or "")))
    return out
