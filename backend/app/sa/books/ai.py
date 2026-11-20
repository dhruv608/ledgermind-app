"""AI suggestions for the lines no rule sorts (as services/bank_only/ai_suggest.py does for a company)."""

import json
import re
from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.sa.trade import HEADINGS
from backend.app.sa.books.rules import DRAWINGS, OUTSIDE, UNSORTED, not_for_ai
from backend.app.sa.books.statements import label


AI_KIND = "sa_bank_head"
AI_BATCH = 12


def kept_suggestions(db: Session, job) -> Dict[str, Dict]:
    from backend.app.models.ai_answers import AIAnswer
    return {r.key: json.loads(r.answer) for r in db.query(AIAnswer).filter(AIAnswer.engagement_id == job.id,
                                                                           AIAnswer.kind == AI_KIND)}


def _ask(payees: List[Dict], business: str) -> Dict[int, Dict]:
    from backend.app.core.bedrock import bedrock_ai
    heads = "\n".join(f"{h} {HEADINGS[h][0]}" for h in HEADINGS if HEADINGS[h][2] == "cost") + \
        f"\n{DRAWINGS} {OUTSIDE[DRAWINGS]}: personal spending\n{UNSORTED} cannot tell: ask the client"
    rows = "\n".join(f'{i}. "{p["payee"]}": {p["lines"]} line(s), money out £{p["out"]:,.2f}; for example '
                     f'"{p["example"][:140]}"' for i, p in enumerate(payees))
    prompt = f"""You are a UK chartered accountant preparing a sole trader's self-employment pages (SA103) from their
bank statement. The business: {business or "not known"}.

Each payee below has payments no rule could sort. Pick the one heading its payments most likely belong to. Use what
you know about the payee (an electrical wholesaler, a motor factor, a software firm, a shop) and the business.
- A cost counts only when it is wholly and exclusively for the business (ITTOIA 2005 s34); personal shopping, clothes,
  groceries and leisure are DRAWINGS.
- Goods and materials used in the work (for a trade: parts, cable, fittings) are COST_OF_SALES.
- A car or van's fuel, parts, repairs and servicing (a motor factor, a garage) are TRAVEL; REPAIRS is for premises
  and equipment only.
- If you cannot tell, use UNSORTED and say what to ask.

Headings:
{heads}

Payees:
{rows}

Reply with a JSON array only, one object per payee:
[{{"i": 0, "heading": "COST_OF_SALES", "sure": "high" | "medium" | "low", "reason": "one short sentence"}}]"""
    raw, model = bedrock_ai.invoke_model_reporting(prompt, max_tokens=90 * len(payees) + 200, temperature=0)
    start, end = (raw.find("["), raw.rfind("]")) if isinstance(raw, str) else (-1, -1)
    if start == -1 or end == -1:
        return {}
    valid = {h for h in HEADINGS if HEADINGS[h][2] == "cost"} | {DRAWINGS, UNSORTED}
    out = {}
    for a in json.loads(raw[start:end + 1]):
        if isinstance(a, dict) and isinstance(a.get("i"), int) and 0 <= a["i"] < len(payees) and a.get("heading") in valid:
            out[a["i"]] = {"heading": a["heading"], "sure": a.get("sure") if a.get("sure") in ("high", "medium", "low") else "low",
                           "reason": str(a.get("reason") or "")[:200], "model": model}
    return out


GENERIC_NAME = re.compile(r"^(trade|business|self[- ]?employment|sole trader|the business)$", re.I)


def business_context(db: Session, job, biz) -> str:
    """What the AI is told about the business: its name and what it does, and when nothing says what it does, the
    trade's name on last year's working paper (a salon's name: its supplies are then costs of the trade)."""
    from backend.app.sa.models import SAExpect
    parts = [x for x in (biz.name if biz else "", biz.description if biz else "") if x and not GENERIC_NAME.match(x.strip())]
    if not (biz and biz.description):
        last = {r.name for r in db.query(SAExpect).filter(SAExpect.job_id == job.id, SAExpect.source == "SELF_EMPLOYMENT")
                if r.name and not GENERIC_NAME.match(r.name.strip())}
        if last:
            parts.append("last year's return names the trade " + ", ".join(sorted(last)[:3]))
    return "; ".join(parts)


def with_suggestions(lines: List[Dict], kept: Dict[str, Dict]) -> List[Dict]:
    """Each unsorted line with the AI's suggestion for its payee, if any (shown only: the accountant clicks to use it)."""
    from backend.app.services.bank_only.books import payee_key
    for r in lines:
        if r["heading"] == UNSORTED and not r["chosen"] and not not_for_ai(r):
            a = kept.get(payee_key(r["description"]))
            if a:
                r["suggestion"] = {"heading": a["heading"], "label": label(a["heading"]), "sure": a["sure"],
                                   "reason": a["reason"]}
    return lines
