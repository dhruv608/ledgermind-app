"""
Scoring and deciding: for one ledger line, every candidate code and the
code it is on are scored, and the line moves only when another code clearly beats it.

  confidence = 0.35 C + 0.20 F + 0.25 D + 0.20 X - ambiguity - conflict
    C client history, F firm history (memory.py), D the definition card (rules/reanalysis_cards.json: the merchant is
    a typical supplier, a word of the line is a card keyword; a card that sends the merchant elsewhere counts against),
    X context (the merchant category's usual code, rules/merchants.json).
  Ambiguity (0.15, and confidence capped at 0.60): a marketplace, supermarket, general retailer or payment platform
    with no client history decides nothing on its own.
  A move needs the best candidate to beat the current code by 0.15. Its reason code comes from the two codes' types;
  the band and the reason's risk give the outcome: an analysis-only move (R01) is proposed when High or Medium and
  left when Low; a move that changes profit, tax or the balance sheet is a journal approved one by one when High, an
  accountant query when Medium and a client query when Low.
Payroll, VAT, bank and the tax charge are other modules' lines: never scored here.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Optional, Protocol

from backend.app.services.reanalysis.merchants import Merchant, merchant_of

RULES = Path(__file__).resolve().parents[2] / "rules"
WEIGHTS = {"C": 0.35, "F": 0.20, "D": 0.25, "X": 0.20}
AMBIGUITY, AMBIGUOUS_CAP, MOVE_MARGIN = 0.15, 0.60, 0.15
HIGH, MEDIUM = 0.85, 0.60
AMBIGUOUS = {"marketplace", "supermarket", "general retail", "payment platform"}
# Lines other modules own: payroll, VAT, bank and cash, the tax charge and creditor
OWNED_ELSEWHERE = set(range(3000, 3016)) | {5300, 5310, 5320, 5330, 5350, 5351, 5352, 3800, 3810} | set(range(4800, 4831))
DISALLOWABLE = {3385, 3391, 3360, 3361, 3362}
DLA = 5400
SUSPENSE = 9999
# Names that say nothing about who was paid: never looked up in memory
GENERIC_MERCHANTS = {"unknown", "spend money", "receive money", "bill", "expense", "payment", "transfer", "cash", "bank",
                     "money added", "payable invoice", "service", "open", "loan"}
WEIGHTS_VERSION = "2026-10-28 SOP starting values"


class MemoryLike(Protocol):
    def client_score(self, merchant_key: str, code: int) -> float: ...
    def firm_score(self, merchant_key: str, code: int) -> float: ...
    def candidates(self, merchant_key: str) -> "Iterable[int]": ...


@dataclass
class Decision:
    merchant: Merchant
    current: int
    proposed: Optional[int]          # None: keep as posted
    confidence: float                # of the proposed code (or of the current one when kept)
    band: str                        # High, Medium, Low
    reason: Optional[str]            # R01 ... R13
    outcome: str                     # keep, propose, journal, accountant query, client query, unclear
    scores: Dict[int, float] = field(default_factory=dict)
    evidence: Dict[str, float] = field(default_factory=dict)


@lru_cache(maxsize=1)
def _cards() -> Dict[int, dict]:
    from backend.app.services.shared import rules_store
    return {c["code"]: c for c in rules_store.load("reanalysis_cards")["cards"]}


@lru_cache(maxsize=1)
def _category_defaults() -> Dict[str, int]:
    from backend.app.services.shared import rules_store
    d = rules_store.load("merchants").get("category_defaults", {})
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _card_score(code: int, merchant: Merchant, words: set) -> float:
    card = _cards().get(code)
    if card is None:
        return 0.0
    name = merchant.name.lower()
    supplier = any(s.lower() == name or s.lower() in name for s in card["typical_suppliers"]) if name else False
    keyword = any(k.lower() in words for k in card["keywords"])
    return 0.5 * supplier + 0.5 * keyword


def _card_sends_elsewhere(code: int, merchant: Merchant) -> bool:
    """The code's card lists this merchant among the things that do not belong there (e.g. Netflix on 3241)."""
    card = _cards().get(code)
    name = merchant.name.lower()
    return bool(card and name and any(name in (e["item"] or "").lower() for e in card["excludes"]))


def _context(code: int, merchant: Merchant) -> float:
    default = _category_defaults().get(merchant.category or "")
    return 1.0 if default == code else 0.0


def _kind(code: int, chart: Dict[int, dict]) -> str:
    if code == DLA:
        return "dla"
    if code == 9999:
        return "suspense"
    row = chart.get(code) or {}
    cat, fc = row.get("category") or "", row.get("financial_class") or ""
    if fc == "Profit and Loss":
        if cat == "Sales" or code < 1000:
            return "income"
        if 1000 <= code < 2000:
            return "cost of sales"
        return "overhead"
    if 4000 <= code < 4200:
        return "fixed asset"
    return "balance sheet"


def reason_code(frm: int, to: int, chart: Dict[int, dict]) -> str:
    a, b = _kind(frm, chart), _kind(to, chart)
    if to in DISALLOWABLE and frm not in DISALLOWABLE:
        return "R13"
    if b == "dla":
        return "R02"
    if a == "dla":
        return "R09"
    if a == "suspense":
        return "R06"
    if "income" in (a, b):
        return "R07"
    if b == "fixed asset":
        return "R10"
    if a == "fixed asset":
        return "R08"
    if {a, b} == {"cost of sales", "overhead"}:
        return "R04"
    if a == b == "overhead" or a == b == "cost of sales":
        return "R01"
    return "R12"


def _scored(code: Optional[int], chart: Dict[int, dict]) -> bool:
    """Lines the engine reads: costs and income in the firm's chart, the director's loan and suspense. A
    payment against a supplier's bill (trade creditors) or a receipt against an invoice is the other side of a cost
    already booked, not the cost itself."""
    if code is None or code in OWNED_ELSEWHERE or code not in chart:
        return False
    return code in (DLA, SUSPENSE) or (chart[code].get("financial_class") == "Profit and Loss")


def _target(code: int, chart: Dict[int, dict]) -> bool:
    """Codes a line can be moved to: the firm chart's costs and income, fixed assets and the director's loan."""
    if code in OWNED_ELSEWHERE or code not in chart:
        return False
    return code == DLA or 4000 <= code < 4200 or chart[code].get("financial_class") == "Profit and Loss"


def decide(description: str, current: int, memory: MemoryLike, chart: Dict[int, dict]) -> Optional[Decision]:
    """The decision for one line on code `current`, or None for a line the engine does not read."""
    if not _scored(current, chart):
        return None
    merchant = merchant_of(description)
    words = _words(description)
    key = "" if merchant.key in GENERIC_MERCHANTS else merchant.key
    candidates = {current}
    if key:
        candidates |= set(memory.candidates(key))
    candidates |= {c for c in _cards() if _card_score(c, merchant, words) > 0}
    default = _category_defaults().get(merchant.category or "")
    if default:
        candidates.add(default)
    candidates = {c for c in candidates if c == current or _target(c, chart)}
    here = _kind(current, chart)
    client_known = bool(key) and any(memory.client_score(key, c) > 0 for c in candidates)
    scores, parts = {}, {}
    for code in candidates:
        p = {"C": memory.client_score(key, code) if key else 0.0, "F": memory.firm_score(key, code) if key else 0.0,
             "D": -0.5 if _card_sends_elsewhere(code, merchant) else _card_score(code, merchant, words),
             # The category's usual code is an overhead: it never decides cost of sales v overheads, which the
             # client's industry and history do (a builder's Uber in direct costs stays there)
             "X": 0.0 if {here, _kind(code, chart)} == {"cost of sales", "overhead"} else _context(code, merchant)}
        s = sum(WEIGHTS[k] * v for k, v in p.items())
        if merchant.category in AMBIGUOUS and not client_known:
            s = min(s - AMBIGUITY, AMBIGUOUS_CAP)
        scores[code], parts[code] = round(max(s, 0.0), 3), p
    best = max(scores, key=lambda c: (scores[c], c == current))
    if best == current or scores[best] - scores[current] < MOVE_MARGIN:
        conf = scores[current]
        return Decision(merchant, current, None, conf, _band(conf), None, "keep", scores, parts[current])
    conf = scores[best]
    reason = reason_code(current, best, chart)
    return Decision(merchant, current, best, conf, _band(conf), reason, _outcome(_band(conf), reason), scores, parts[best])


def _band(conf: float) -> str:
    return "High" if conf >= HIGH else "Medium" if conf >= MEDIUM else "Low"


def _outcome(band: str, reason: str) -> str:
    if reason == "R01":
        return {"High": "propose", "Medium": "propose", "Low": "unclear"}[band]
    return {"High": "journal", "Medium": "accountant query", "Low": "client query"}[band]
