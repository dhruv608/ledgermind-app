"""
What the books say about each industry question on the setup (rules/industry_setup.json, 'evidence' on a question):
a suggested Yes / No with the reason, shown beside the question for the accountant to use or ignore. Never an answer
by itself.

Evidence kinds (data, editable in the JSON):
  accounts: regex on the trial balance account names (non-zero balance)  -> Yes when one matches
  ledger:   regex on the ledger descriptions                             -> Yes when lines match
  absent:   "N" -> No when nothing matched (only where the account would always exist if the answer were Yes)
  check:    "customer_concentration" -> share of sales from the largest customer (single-client contractor, IR35)
"""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, ClientProfile, GLTransaction, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup

NAME_SUFFIXES = re.compile(r"\b(inc|ltd|limited|llc|plc|co|corp|corporation|gmbh|pte|sa|bv|kk)\b\.?", re.I)
SINGLE_CLIENT_SHARE = 0.75      # largest customer at or above this share of sales: looks like a single-client contractor
SPREAD_SHARE, SPREAD_CUSTOMERS = 0.5, 5     # below this share with at least this many customers: clearly not


def _customer(description: str) -> Optional[str]:
    """The customer part of a sales line ('Acme, Inc - Translation...' -> 'acme'), or None if not named."""
    if " - " not in (description or ""):
        return None
    name = re.sub(r"\(.*?\)", " ", description.split(" - ")[0].lower())
    name = NAME_SUFFIXES.sub(" ", re.sub(r"[^\w\s]", " ", name))
    name = " ".join(name.split())
    return name or None


def customer_concentration(tb: List[TBRecord], gl: List[GLTransaction], chart: ChartLookup) -> Optional[Dict[str, Any]]:
    codes = chart.gl_account_codes(tb)
    by: Dict[str, float] = defaultdict(float)
    total = named = 0.0
    labels: Dict[str, str] = {}
    for g in gl:
        name_key = (g.raw_account_name or "").lower().strip()
        code = codes.get(name_key) or codes.get(name_key.split(":")[-1].strip())
        amount = -float(g.net_amount or 0)
        if not chart.is_sales(code) or amount <= 0:
            continue
        total += amount
        who = _customer(g.description or "")
        if who:
            by[who] += amount
            named += amount
            labels.setdefault(who, (g.description or "").split(" - ")[0].strip())
    if total <= 0 or named / total < 0.6:
        return None                                     # customers not named on enough of the sales lines
    top, top_value = max(by.items(), key=lambda kv: kv[1])
    share = top_value / named
    reason = (f"Largest customer {labels[top]} is {share:.0%} of named sales; {len(by)} customers in the ledger")
    if share >= SINGLE_CLIENT_SHARE:
        return {"value": "Y", "reason": reason}
    if share < SPREAD_SHARE and len(by) >= SPREAD_CUSTOMERS:
        return {"value": "N", "reason": reason}
    return None


def industry_evidence(eng: ClientEngagement, profile: ClientProfile, record: Dict[str, Any], db: Session) -> Dict[str, Dict[str, Any]]:
    """{question id: {value 'Y'/'N', reason}} for the industry's questions not answered yet."""
    from backend.app.services.setup.engagement_setup import catalogue
    industry = catalogue()["industries"].get(profile.industry_code or "")
    if not industry:
        return {}
    answers = record["industry"].get("answers") or {}
    open_questions = [q for q in industry["questions"] if q.get("evidence") and answers.get(q["id"]) in (None, "", [])]
    if not open_questions:
        return {}
    tb = db.query(TBRecord).filter(TBRecord.engagement_id == eng.id).all()
    gl = db.query(GLTransaction).filter(GLTransaction.engagement_id == eng.id).all()
    chart = ChartLookup(db)
    out: Dict[str, Dict[str, Any]] = {}
    for q in open_questions:
        ev = q["evidence"]
        if ev.get("check") == "customer_concentration":
            found = customer_concentration(tb, gl, chart)
            if found:
                out[q["id"]] = found
            continue
        hits = []
        if ev.get("accounts"):
            pattern = re.compile(ev["accounts"], re.I)
            hits += [f"account '{t.raw_account_name}' £{abs(float(t.net_amount or 0)):,.2f}"
                     for t in tb if pattern.search(t.raw_account_name or "") and abs(float(t.net_amount or 0)) >= 0.01][:3]
        if ev.get("ledger") and not hits:
            pattern = re.compile(ev["ledger"], re.I)
            lines = [g for g in gl if pattern.search(g.description or "")]
            if lines:
                hits.append(f"{len(lines)} ledger line(s) such as '{(lines[0].description or '').splitlines()[0][:60]}'")
        if hits:
            out[q["id"]] = {"value": "Y", "reason": "; ".join(hits)}
        elif ev.get("absent") == "N":
            out[q["id"]] = {"value": "N", "reason": "No such account in the books"}
    return out
