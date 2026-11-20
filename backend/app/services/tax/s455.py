"""
Section 455 tax on overdrawn directors' loan accounts (CTA 2010 s455, HMRC CTM61505).
The rate depends on the date each loan was made, so the year-end balance is split by advance date.
Rates and the change-over date come from rules/parameters.json (P-S455, P-S455-PRIOR).
"""

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

PARAMETERS_FILE = Path(__file__).resolve().parents[2] / "rules" / "parameters.json"


@lru_cache(maxsize=1)
def s455_rates() -> Tuple[float, float, date]:
    """Return (rate for older loans, rate for newer loans, date the newer rate starts)."""
    with open(PARAMETERS_FILE, encoding="utf-8") as f:
        params = {p.get("Param_ID"): p for p in json.load(f)}
    current, prior = params["P-S455"], params["P-S455-PRIOR"]
    starts = datetime.strptime(current["Effective From"], "%d %b %Y").date()
    return float(prior["Value"]), float(current["Value"]), starts


def s455_charge(overdrawn_balance: float, advances: Iterable[Tuple[Optional[date], float]]) -> Dict[str, Any]:
    """Split the overdrawn balance into the loans still outstanding and apply each loan's rate.

    Repayments are taken to clear the oldest loans first, so the balance still owed is made up of the most
    recent advances. Any part not covered by advances in this year's ledger is a brought-forward loan.
    """
    prior_rate, current_rate, starts = s455_rates()
    remaining = round(max(0.0, overdrawn_balance), 2)
    newer, older = 0.0, 0.0

    for advance_date, amount in sorted((a for a in advances if a[0] and a[1] > 0), key=lambda a: a[0], reverse=True):
        if remaining <= 0:
            break
        portion = min(amount, remaining)
        if advance_date >= starts:
            newer += portion
        else:
            older += portion
        remaining = round(remaining - portion, 2)
    older += remaining  # brought forward from earlier years

    parts = []
    if newer > 0.005:
        parts.append({"label": f"loans from {starts:%d %b %Y}", "rate": current_rate, "amount": round(newer, 2), "tax": round(newer * current_rate, 2)})
    if older > 0.005:
        parts.append({"label": f"loans before {starts:%d %b %Y}", "rate": prior_rate, "amount": round(older, 2), "tax": round(older * prior_rate, 2)})

    return {
        "tax": round(sum(p["tax"] for p in parts), 2),
        "parts": parts,
        "explanation": "; ".join(f"£{p['amount']:,.2f} of {p['label']} at {p['rate'] * 100:.2f}% = £{p['tax']:,.2f}" for p in parts),
    }

