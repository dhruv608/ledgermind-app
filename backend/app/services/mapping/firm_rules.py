"""
The firm's account rules (Account rules page): "an account whose name contains these words goes to this code".

These are the firm's choices where accounting allows more than one code (Christmas party: staff entertaining or staff
welfare), so they are data the accountant edits, not code. Accounting facts (debtors are assets, a bank is a bank)
stay in the mapping service's built-in rules.

Matching: words are comma separated and matched as whole words, any case, with a plural 's' allowed
('client meeting' also matches 'Client Meetings'). A rule does not apply when the name also contains one of its
'except' words (exactly, no plural). When several rules match, the most specific wins: the one whose matching
words are longest ('staff entertaining' beats 'entertaining'), so the accountant never has to order the rules.
"""

import re
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, FirmMappingRule, MasterCOA, TBRecord

# The firm's starting rules, loaded into the table when it is empty
SEED_RULES = [
    {"words": "christmas party, xmas party, staff party, team party, summer party, staff do, staff event, staff social, "
              "staff entertaining, staff entertainment, team building, team lunch, team outing",
     "std_code": 3070, "note": "Staff parties and team events (accountant: 3070 for a new client; a client keeps last year's code)"},
    {"words": "client meeting, client entertaining, client lunch, client dinner, client hospitality, "
              "business entertaining, entertainment, entertaining",
     "std_code": 3385, "note": "Entertaining clients (accountant: 3385)"},
    {"words": "trivial benefit, eye test, eye care, christmas card, staff welfare, staff gift, staff meeting, team meeting",
     "std_code": 3050, "note": "Small staff costs that are not entertaining"},
    {"words": "software, subscription, saas, slack, microsoft, office 365, adobe, zoom, google workspace, g suite, dropbox",
     "except_words": "cost, addition, amortisation, depreciation, intangible, sales, income, revenue, rebillable, recharge, recharged",
     "std_code": 3320, "note": "Software and subscriptions (accountant: 3320 for a new client, regular costs that lead to prepayments; a client keeps last year's code)"},
    {"words": "travel, travelling, subsistence, hotel, accommodation, train, rail, flight, airfare, taxi, uber",
     "except_words": "motor, vehicle, car hire, income, sales, revenue, recharge, recharged",
     "std_code": 3081, "note": "All travel in one code (accountant: 3081 travel and subsistence)"},
]

# A rule decides only accounts the AI (or an earlier rule) coded. Kept as they are: codes an accountant chose or
# confirmed, codes from the client's own chart when it follows the firm's codes or from last year, and accounting
# facts (built-in naming rules, exact firm account names, parent accounts).
RULE_DECIDES = {"AI", "FIRM_DEFAULT", "", None}
KEPT_REASON = {"MANUAL": "set by an accountant", "CONFIRMED": "confirmed by an accountant",
               "MEMORY": "confirmed by an accountant before", "CODE_AND_NAME": "client's own firm code",
               "CLIENT_FIRM_CODE": "client's own firm code", "ROLL_FORWARD": "last year's code", "LAST_YEAR": "last year's code",
               "RULE": "built-in accounting rule", "COA_NAME": "exact firm account name", "PARENT": "parent account"}


def split_words(text: Optional[str]) -> List[str]:
    return [w.strip().lower() for w in (text or "").split(",") if w.strip()]


@lru_cache(maxsize=4096)
def _pattern(word: str, plural: bool = True) -> "re.Pattern":
    """The words in the name as whole words, any spacing or punctuation between them; a two-word phrase also the
    other way round, as accounts are often named ('Entertainment - Staff' is 'staff entertainment', 'Meeting -
    Client' is 'client meeting')."""
    parts = [re.escape(part) for part in word.split()]
    end = "(s|es)?" if plural else ""
    bodies = [r"[^a-z0-9]+".join(parts)]
    if len(parts) == 2:
        bodies.append(rf"{parts[1]}{end}[^a-z0-9]+{parts[0]}")
    return re.compile("|".join(rf"(?<![a-z])(?:{b}){end}(?![a-z])" if i == 0 else rf"(?<![a-z])(?:{b})(?![a-z])"
                               for i, b in enumerate(bodies)), re.I)


def _clean(name: str) -> str:
    """The account name without a leading account number ('7400 - Travel' -> 'travel')."""
    return re.sub(r"^\d+[\s\-_:]+", "", name or "").strip().lower()


def match_length(rule: Any, name: str) -> int:
    """How specific the rule's match is: the length of its longest word found in the name (0: no match)."""
    text = _clean(name)
    found = [len(w) for w in split_words(rule.words) if _pattern(w).search(text)]
    # 'except' words are exact ('cost' rules out 'Software - cost', not 'Software costs')
    if not found or any(_pattern(w, plural=False).search(text) for w in split_words(rule.except_words)):
        return 0
    return max(found)


def rule_matches(rule: Any, name: str) -> bool:
    return match_length(rule, name) > 0


def all_rules(db: Session, owner_user_id: Optional[int]) -> List[FirmMappingRule]:
    """The firm's rules in order (active or not), shared by every sign-in of the firm; the starting rules are loaded
    the first time. owner_user_id only says who added a rule."""
    q = select(FirmMappingRule).order_by(FirmMappingRule.position, FirmMappingRule.id)
    rules = db.execute(q).scalars().all()
    if not rules and owner_user_id is not None:
        for i, r in enumerate(SEED_RULES):
            db.add(FirmMappingRule(position=i, owner_user_id=owner_user_id, **r))
        db.commit()
        rules = db.execute(q).scalars().all()
    return rules


def load_rules(db: Session, owner_user_id: Optional[int]) -> List[FirmMappingRule]:
    """The firm's active rules in order."""
    return [r for r in all_rules(db, owner_user_id) if r.active]


def first_rule(rules: Iterable[FirmMappingRule], name: str) -> Optional[FirmMappingRule]:
    """The rule that decides this account: the most specific match (longest matching words); on a tie, the older rule."""
    best, best_len = None, 0
    for r in rules:
        n = match_length(r, name)
        if n > best_len:
            best, best_len = r, n
    return best


def match_counts(db: Session, owner_user_id: Optional[int]) -> Dict[int, int]:
    """How many client accounts each rule decides, in one pass over the firm's clients."""
    rules = load_rules(db, owner_user_id)
    counts: Dict[int, int] = {r.id: 0 for r in rules}
    ids = select(ClientEngagement.id)
    for (name,) in db.execute(select(TBRecord.raw_account_name).where(TBRecord.engagement_id.in_(ids))):
        r = first_rule(rules, name)
        if r is not None:
            counts[r.id] += 1
    return counts


def rule_matches_in_clients(rule: FirmMappingRule, db: Session) -> List[Dict[str, Any]]:
    """Every client account this rule decides (it is the first matching rule), with what it has now."""
    rules = load_rules(db, rule.owner_user_id)
    clients = {e.id: e.client_name for e in db.execute(select(ClientEngagement)).scalars()}
    out = []
    for t in db.execute(select(TBRecord).where(TBRecord.engagement_id.in_(list(clients) or [""]))).scalars():
        first = first_rule(rules, t.raw_account_name)
        if first is None or first.id != rule.id:
            continue
        kept = t.match_source not in RULE_DECIDES
        out.append({"engagement_id": t.engagement_id, "client": clients.get(t.engagement_id, ""),
                    "account": t.raw_account_name, "current_code": t.std_code, "current_name": t.std_name,
                    "match_source": t.match_source, "balance": float(t.net_amount or 0),
                    "kept_because": KEPT_REASON.get(t.match_source or "", "kept") if kept else None,
                    "would_change": t.std_code != rule.std_code and not kept})
    out.sort(key=lambda x: (not x["would_change"], x["client"], x["account"]))
    return out


def apply_rule(rule: FirmMappingRule, db: Session) -> Dict[str, Any]:
    """Moves the accounts this rule decides to its code, except those an accountant set; returns what changed."""
    from backend.app.services.shared.activity import mark_changed
    coa = db.get(MasterCOA, rule.std_code)
    if coa is None:
        raise ValueError(f"Code {rule.std_code} is not in the chart")
    changes = [m for m in rule_matches_in_clients(rule, db) if m["would_change"]]
    touched = set()
    for m in changes:
        for t in db.execute(select(TBRecord).where(TBRecord.engagement_id == m["engagement_id"],
                                                   TBRecord.raw_account_name == m["account"])).scalars():
            t.std_code, t.std_name = rule.std_code, coa.std_name
            t.mapping_status, t.confidence_score, t.match_source = "MATCHED", 0.95, "FIRM_DEFAULT"
            t.mapping_reason = f"Firm account rule: {rule.note or ', '.join(split_words(rule.words)[:3])} ({rule.std_code:04d})."
        touched.add(m["engagement_id"])
    db.commit()
    for eng_id in touched:
        mark_changed(db, eng_id)
    return {"changed": len(changes), "clients": len(touched)}


def touch(rule: FirmMappingRule) -> None:
    rule.updated_at = datetime.utcnow()
