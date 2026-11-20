"""
AI suggestions on the bank lines no rule could sort, shown on a manual job's Books tab. The unsorted lines are
grouped by payee; the AI is asked once per batch which code of the
firm's chart each payee's lines belong to, with a short reason. A suggestion is only shown: the accountant clicks to
use it (the head then goes on every line from that payee, as a choice made by hand). Costs that look personal go to
the director's loan and unclear ones to 'Ask the client': a cost is the company's only when it is wholly and
exclusively for the trade (CTA 2009 s54). Answers are kept per payee (ai_answers), so asking again costs nothing.
"""

import json
import logging
import re
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement

log = logging.getLogger(__name__)

KIND = "bank_head"
BATCH = 12                  # payees per AI call (sent together: the reply in about 20 seconds)
MAX_PAYEES = 200            # the largest payees of a job, by money moved
SURE = ("high", "medium", "low")
# Words in a payee that are not its name ('next nextdirectory united' -> 'next')
NOT_A_NAME = {"united", "kingdom", "london", "the", "card", "payment", "paypal", "www", "com", "ltd", "limited", "gbp"}


def kept_suggestions(engagement_id: str, db: Session) -> Dict[str, Dict[str, Any]]:
    """The AI's answers already kept for this job: {payee: {code, reason, sure}}."""
    from backend.app.models.ai_answers import AIAnswer
    return {r.key: json.loads(r.answer) for r in db.query(AIAnswer).filter(
        AIAnswer.engagement_id == engagement_id, AIAnswer.kind == KIND)}


def _ask(payees: List[Dict[str, Any]], chart: List[Dict[str, Any]], business: str) -> Dict[int, Dict[str, Any]]:
    from backend.app.core.bedrock import bedrock_ai
    codes = "\n".join(f"{c['code']} {c['name']}" for c in chart if not c.get("extended"))
    def described(p: Dict[str, Any]) -> str:
        money = f"money out £{p['out']:,.2f}" if p["out"] >= p["in"] else f"money in £{p['in']:,.2f}"
        paid = (f"; the client also paid this name {p['paid_same_name']} time(s) elsewhere in the bank"
                if p["in"] > p["out"] and p.get("paid_same_name") else "")
        return f'"{p["payee"]}": {p["lines"]} line(s), {money}{paid}; for example "{p["example"][:140]}"'
    rows = "\n".join(f"{i}. {described(p)}" for i, p in enumerate(payees))
    prompt = f"""You are a UK chartered accountant coding a small company's bank statement lines.
The client's business: {business or "not known"}.

Each payee below has bank lines no rule could code. Pick the one code from the firm's chart that its lines most likely
belong to. Use what you know about the payee (a software company, a courier, a supermarket, a marketplace) and the
client's business.
- A cost belongs to the company only when it is wholly and exclusively for the business; clothes, groceries for a
  non-food business, personal shopping or leisure go to 5400 Director's loan account.
- Meals and drinks (restaurants, pubs, bars) may be business entertaining or personal: use the chart's entertaining
  code if it has one, else 5400, and always "low" for sure.
- Money in from customers or payment platforms paying out sales (Shopify, Stripe, PayPal payouts, Amazon payouts) is
  sales. Money in from a shop, supplier or travel company (Next, John Lewis, Amazon purchases, an airline, a hotel) is a
  refund: the same code as that payee's cost, never sales; so is money in from a name the client also pays.
- If you cannot tell, use 9999 (ask the client) and say what to ask.

The firm's chart (code name):
{codes}

Payees:
{rows}

Reply with a JSON array only, one object per payee:
[{{"i": 0, "code": 3240, "sure": "high" | "medium" | "low", "reason": "one short sentence"}}]"""
    raw, model = bedrock_ai.invoke_model_reporting(prompt, max_tokens=90 * len(payees) + 200, temperature=0)
    if not isinstance(raw, str):
        return {}
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return {}
    valid = {c["code"] for c in chart}
    out = {}
    for a in json.loads(raw[start:end + 1]):
        if not isinstance(a, dict) or not isinstance(a.get("i"), int) or not 0 <= a["i"] < len(payees):
            continue
        try:
            code = int(a.get("code"))
        except (TypeError, ValueError):
            continue
        if code in valid:
            out[a["i"]] = {"code": code, "sure": a.get("sure") if a.get("sure") in SURE else "low",
                           "reason": str(a.get("reason") or "")[:200], "model": model}
    return out


def suggest(engagement: ClientEngagement, db: Session) -> Dict[str, int]:
    """Asks the AI about the unsorted payees not asked before; {asked, suggested, payees}."""
    from backend.app.models.ai_answers import AIAnswer
    from backend.app.services.bank_only.bank_sort import UNSORTED
    from backend.app.services.bank_only.books import bank_industry, books, chart_for_picking
    from backend.app.services.setup.engagement_setup import INDUSTRY_NAMES

    data = books(engagement, db)
    # How often the client paid out to a payee's name anywhere in the bank: money in from a name it also pays is a refund
    out_texts = [r["description"].lower() for r in data["bank"] if (r["money_out"] or 0) > 0]

    def paid_same_name(payee: str) -> int:
        word = next((w for w in payee.split() if len(w) >= 3 and w not in NOT_A_NAME), "")
        return sum(1 for t in out_texts if re.search(rf"\b{re.escape(word)}\b", t)) if word else 0
    groups: Dict[str, Dict[str, Any]] = {}
    for r in data["bank"]:
        if r["head"] != UNSORTED or r["chosen"] or not r["payee"]:
            continue
        g = groups.setdefault(r["payee"], {"payee": r["payee"], "lines": 0, "in": 0.0, "out": 0.0,
                                           "example": r["description"]})
        g["lines"] += 1
        g["in"] += r["money_in"] or 0
        g["out"] += r["money_out"] or 0
    for g in groups.values():
        g["paid_same_name"] = paid_same_name(g["payee"]) if g["in"] > g["out"] else 0
    kept = kept_suggestions(str(engagement.id), db)
    new = sorted((g for p, g in groups.items() if p not in kept), key=lambda g: -(g["in"] + g["out"]))[:MAX_PAYEES]
    industry, _ = bank_industry(engagement)
    business = ", ".join(x for x in (engagement.client_name, INDUSTRY_NAMES.get(industry or "", "")) if x)
    chart = chart_for_picking(db)
    from backend.app.services.mapping.chart_lookup import ChartLookup
    chart_lookup = ChartLookup(db)
    suggested = 0
    batches = [new[i:i + BATCH] for i in range(0, len(new), BATCH)]

    def ask(batch):
        try:
            return _ask(batch, chart, business)
        except Exception as e:          # no AI (an outage): nothing is guessed, the accountant picks by hand
            log.warning("Bank AI suggestions skipped: %s", e)
            return {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(ask, batches))
    for batch, answers in zip(batches, replies):
        for j, g in enumerate(batch):
            a = answers.get(j)
            if a and g.get("paid_same_name") and chart_lookup.is_sales(a["code"]):
                # Sales from a name the client also pays: probably a refund of that cost, so never sure
                a["sure"] = "low"
                a["reason"] = (a["reason"] + f" The client also paid this name {g['paid_same_name']} time(s): it may be "
                               f"a refund.")[:240]
            if j in answers:
                db.add(AIAnswer(engagement_id=str(engagement.id), kind=KIND, key=g["payee"][:300],
                                answer=json.dumps(answers[j]), model=answers[j].get("model")))
                suggested += 1
        db.commit()
    return {"asked": len(new), "suggested": suggested, "payees": len(groups)}
