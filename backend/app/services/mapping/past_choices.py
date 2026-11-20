"""
The accountant's past choices, shown to the AI as examples: before the AI codes "Staff Xmas Do", it is told that the
accountant coded "Staff Christmas Party" as 3070 on another client. The AI then follows the firm's habits where two
codes would both be defensible (staff party 3070 or 3050, software 3241 or 3320) instead of guessing.

Examples come from the whole firm: codes an accountant set or confirmed on the firm's other clients, and the
remembered choices. Similar means sharing words that say what the account is ("christmas", "software"), not words
every account has ("costs", "account").
"""

import re
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MappingMemory, MasterCOA, TBRecord

# Codes an accountant decided (the client's own firm code and last year's code count too)
SETTLED_SOURCES = {"MANUAL", "CONFIRMED", "MEMORY", "LAST_YEAR", "ROLL_FORWARD", "CODE_AND_NAME", "CLIENT_FIRM_CODE"}
EXAMPLES_PER_ACCOUNT = 3
MIN_SHARED = 0.6
COMMON_WORDS = {
    "and", "the", "of", "for", "to", "in", "on", "a", "an", "&", "ltd", "limited", "plc", "llp", "account", "accounts",
    "cost", "costs", "expense", "expenses", "exp", "fee", "fees", "charge", "charges", "total", "general", "misc",
    "sundry", "other", "others", "payable", "receivable", "control", "balance", "uk", "gbp", "usd", "eur", "ye",
}


def words(name: str) -> frozenset:
    """What the account is about: its words without numbers, the client's code or common words ('3000 - Wages and
    Salaries' -> {wages, salaries}). A plural 's' is dropped so 'subscriptions' meets 'subscription'."""
    text = re.sub(r"^\s*[\d.\-/]+\s*[-–:]?\s*", "", (name or "").lower())
    out = set()
    for w in re.findall(r"[a-z]+", text):
        if len(w) < 3 or w in COMMON_WORDS:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return frozenset(out)


class ExamplePool:
    """Accounts with the accountant's code, searchable by the words they share with a new account."""

    def __init__(self, examples: Iterable[Tuple[str, int]], coa_names: Dict[int, str]):
        seen = set()
        self.items: List[Tuple[str, int, frozenset]] = []
        for name, code in examples:
            key = (name.strip().lower(), code)
            if not name or code is None or key in seen:
                continue
            seen.add(key)
            w = words(name)
            if w:
                self.items.append((name.strip(), int(code), w))
        self.coa_names = coa_names

    def similar(self, name: str, k: int = EXAMPLES_PER_ACCOUNT) -> List[str]:
        """Up to k past choices for accounts like this one, most alike first: '"Staff Xmas Party" -> 3070 Staff ...'."""
        mine = words(name)
        if not mine:
            return []
        scored = []
        for other, code, w in self.items:
            shared = mine & w
            # most of what this account is about must be in the other one ('computer accessories' is not
            # 'computer software costs'): at least 60% of its words
            if not shared or len(shared) / len(mine) < MIN_SHARED:
                continue
            # share of the words in common (both ways), longer shared words count more
            score = len(shared) / len(mine | w) + 0.01 * sum(len(s) for s in shared)
            scored.append((score, other, code))
        scored.sort(key=lambda x: -x[0])
        out, codes = [], set()
        for _, other, code in scored:
            if len(out) >= k:
                break
            if other.lower() == (name or "").strip().lower() and code in codes:
                continue
            out.append(f'"{other}" -> {code:04d} {self.coa_names.get(code, "")}'.strip())
            codes.add(code)
        return out


def pool_for(db: Session, owner_user_id: Optional[int], exclude_engagement: Optional[str] = None) -> ExamplePool:
    """The firm's settled codes on its other clients, plus its remembered choices. owner_user_id is reserved for
    separating firms."""
    coa_names = {c.std_code: c.std_name for c in db.query(MasterCOA)}
    engs = select(ClientEngagement.id)
    if exclude_engagement:
        engs = engs.where(ClientEngagement.id != exclude_engagement)
    rows = db.execute(select(TBRecord.raw_account_name, TBRecord.std_code)
                      .where(TBRecord.engagement_id.in_(engs), TBRecord.std_code.isnot(None),
                             TBRecord.match_source.in_(SETTLED_SOURCES))).all()
    examples: List[Tuple[str, int]] = [(n, c) for n, c in rows]
    examples += [(n, c) for n, c in db.execute(select(MappingMemory.client_account_name, MappingMemory.std_code)).all()]
    # The firm's coding in its finished working papers
    from backend.app.services.mapping.firm_examples import all_examples
    examples += all_examples(db)
    return ExamplePool(examples, coa_names)
