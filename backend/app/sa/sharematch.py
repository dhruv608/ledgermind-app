"""Share and cryptoasset matching (TCGA s104, s105, s106A; CG51560; crypto the same way): each sale is matched first with
shares of the same holding bought the same day, then with those bought in the 30 days after (earliest first), then
with the section 104 pool at its average cost. A pool brought forward is an opening line (quantity and cost).

Trades of a holding are worked through in date order; same-day buys are one acquisition, same-day sells one disposal.
Each sale in the tax year becomes a disposal for capital gains with its matched cost."""

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List

POOL, BUY, SELL = "POOL", "BUY", "SELL"
EPS = 1e-9


def _d(s: str) -> date:
    return date.fromisoformat(s)


def match(trades: List) -> Dict:
    """trades: objects with on (YYYY-MM-DD), side (POOL/BUY/SELL), quantity, amount (cost with fees, or proceeds net of
    fees). Returns each sale with its cost by rule, and the pool left."""
    buys: Dict[date, Dict[str, float]] = defaultdict(lambda: {"qty": 0.0, "cost": 0.0})
    sells: Dict[date, Dict[str, float]] = defaultdict(lambda: {"qty": 0.0, "proceeds": 0.0})
    pool = {"qty": 0.0, "cost": 0.0}
    for t in trades:
        q, a = float(t.quantity or 0), float(t.amount or 0)
        if t.side == POOL:
            pool["qty"] += q
            pool["cost"] += a
        elif t.side == BUY:
            buys[_d(t.on)]["qty"] += q
            buys[_d(t.on)]["cost"] += a
        elif t.side == SELL:
            sells[_d(t.on)]["qty"] += q
            sells[_d(t.on)]["proceeds"] += a
    left = {d: dict(v) for d, v in buys.items()}                 # buys not yet matched with an earlier sale
    # First the same-day and 30-day matches for every sale, which take buys out before they reach the pool
    # (every sale's same-day match comes before any 30-day match: s105 then s106A)
    plans: Dict[date, Dict] = {sd: {"parts": [], "need": sells[sd]["qty"]} for sd in sells}
    for rule in ("same day", "30 days"):
        for sd in sorted(sells):
            p = plans[sd]
            days = [sd] if rule == "same day" else [d for d in sorted(left) if sd < d <= sd + timedelta(days=30)]
            for d in days:
                b = left.get(d)
                if not b or b["qty"] <= EPS or p["need"] <= EPS:
                    continue
                take = min(p["need"], b["qty"])
                cost = b["cost"] * take / b["qty"]
                b["qty"] -= take
                b["cost"] -= cost
                p["need"] -= take
                p["parts"].append({"rule": rule, "on": d.isoformat(), "qty": take, "cost": cost})
    # Then the pool, in date order: what is left of each buy joins the pool on its day; each sale takes the rest from it
    events = sorted(set(left) | set(sells))
    out, short = [], []
    for d in events:
        if d in left and left[d]["qty"] > EPS:
            pool["qty"] += left[d]["qty"]
            pool["cost"] += left[d]["cost"]
        if d in sells:
            p = plans[d]
            need = p["need"]
            if need > EPS:
                if pool["qty"] + EPS < need:
                    short.append(f"Sold {sells[d]['qty']:g} on {d:%d/%m/%Y} but only {pool['qty']:g} held: a purchase is missing.")
                take = min(need, pool["qty"])
                cost = pool["cost"] * take / pool["qty"] if pool["qty"] > EPS else 0.0
                pool["qty"] -= take
                pool["cost"] -= cost
                p["parts"].append({"rule": "section 104 pool", "on": None, "qty": take, "cost": cost})
            cost = round(sum(x["cost"] for x in p["parts"]), 2)
            out.append({"on": d.isoformat(), "qty": sells[d]["qty"], "proceeds": round(sells[d]["proceeds"], 2), "cost": cost,
                        "gain": round(sells[d]["proceeds"] - cost, 2),
                        "parts": [{**x, "cost": round(x["cost"], 2)} for x in p["parts"]]})
    return {"sales": out, "pool": {"qty": round(pool["qty"], 8), "cost": round(pool["cost"], 2)}, "issues": short}


def disposals(db, job) -> Dict:
    """Every holding's matching, and the sales of the tax year as disposals for capital gains."""
    from types import SimpleNamespace as N
    from backend.app.sa.cgt import year_bounds
    from backend.app.sa.models import SAShareTrade
    trades = db.query(SAShareTrade).filter(SAShareTrade.job_id == job.id).order_by(SAShareTrade.on, SAShareTrade.id).all()
    start, end = year_bounds(job.tax_year)
    holdings, rows = [], []
    by: Dict[tuple, List] = defaultdict(list)
    for t in trades:
        by[(t.holding, t.kind)].append(t)
    for (name, kind), ts in by.items():
        m = match(ts)
        holdings.append({"holding": name, "kind": kind, **m,
                         "trades": [{"id": t.id, "on": t.on, "side": t.side, "quantity": float(t.quantity or 0),
                                     "amount": float(t.amount or 0), "doc_id": t.doc_id} for t in ts]})
        for n, s in enumerate(m["sales"]):
            if start <= _d(s["on"]) <= end:
                rows.append(N(id=f"m{ts[0].id}-{n}", kind=kind, name=f"{name}: {s['qty']:g} sold", acquired=None,
                              contract_date=s["on"], completion_date=None, proceeds=s["proceeds"], cost=s["cost"], costs=0,
                              improvements=0, share=1, uk=1, main_home_months=None, badr=0, negligible=0, rtt_date=None,
                              rtt_gain=None, rtt_tax=None, doc_id=None, note="Cost by the share matching rules",
                              matched=True))
    return {"holdings": holdings, "disposals": rows}
