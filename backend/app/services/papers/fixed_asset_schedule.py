"""The fixed asset schedule on screen, tangible and intangible: one column per asset class, rows Cost b/f, Additions,
Disposals, Cost c/f, Depreciation b/f, Charge for the year, Elimination, Depreciation c/f, NBV this year and last.

The figures follow the workbook's C1-1 tab (workbook/fixed_assets.py): the firm chart keeps each class in a group of
ten codes and each code's role is read from its chart name (fa_role). Every code's opening goes to b/f (cost codes to
cost b/f, depreciation codes to depreciation b/f); its movement this year (the books' closing balance with the journals
approved in the app, less the opening) goes to additions or disposals, the charge or the elimination. So the NBV is the
class's balances in the books, and a class's cost and depreciation c/f are its codes added up."""

import re
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup

INTANGIBLE = range(4000, 4100)
TANGIBLE = range(4100, 4200)
ROWS = ("cost_bf", "additions", "disposals", "cost_cf", "dep_bf", "charge", "elimination", "dep_cf", "nbv", "nbv_bf")


def fa_role(name: str) -> str:
    """A fixed asset code's role from its firm chart name (the same reading as the workbook's C1-1 tab)."""
    name = name.lower()
    dep = re.search(r"depreciation|amortisation", name)
    if re.search(r"b/ ?fwd", name):
        return "DEP_BF" if dep else "COST"
    if dep and re.search(r"disposal|revaluation", name):
        return "DEP_DISP"
    if dep or "impairment" in name:
        return "CHARGE"
    if "disposal" in name:
        return "DISP"
    if "addition" in name or "revaluation" in name:
        return "ADD"
    return "COST"


def class_name(chart: ChartLookup, base: int) -> str:
    return re.sub(r"\s*-?\s*cost$", "", chart.name(base, f"Fixed assets {base}"), flags=re.IGNORECASE).strip()


def schedule(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.reconciliation.rows import _last_year_balances
    from backend.app.services.tax.ct_computation import final_balances

    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    closing = final_balances(str(engagement.id), tb_records, db)     # the TB with the journals approved in the app
    tb_closing: Dict[int, float] = {}
    for t in tb_records:
        if t.std_code is not None:
            tb_closing[t.std_code] = tb_closing.get(t.std_code, 0.0) + float(t.net_amount or 0)
    last = _last_year_balances(engagement, db, tb_records)
    chart = ChartLookup(db)
    codes = sorted(c for c in set(closing) | set(last or {}) if c in TANGIBLE or c in INTANGIBLE)

    def opening(code: int, role: str) -> float:
        if last is not None:
            return float(last.get(code, 0.0))
        # No last year's figures: a b/fwd code's TB balance is its b/f, the journals its movement (as the workbook)
        return tb_closing.get(code, 0.0) if role in ("COST", "DEP_BF") else 0.0

    def group(kind: range) -> Dict[str, Any]:
        classes: List[Dict[str, Any]] = []
        for base in sorted({c // 10 * 10 for c in codes if c in kind}):
            v = {k: 0.0 for k in ROWS}
            used = [c for c in codes if base <= c < base + 10]
            for code in used:
                role = fa_role(chart.name(code))
                bf = opening(code, role)
                mv = float(closing.get(code, 0.0)) - bf
                if role in ("COST", "ADD", "DISP"):
                    v["cost_bf"] += bf
                    if role == "DISP":
                        v["disposals"] -= mv
                    else:
                        v["additions"] += mv
                else:
                    v["dep_bf"] -= bf
                    if role == "DEP_DISP":
                        v["elimination"] += mv
                    else:
                        v["charge"] -= mv
            v["cost_cf"] = v["cost_bf"] + v["additions"] - v["disposals"]
            v["dep_cf"] = v["dep_bf"] + v["charge"] - v["elimination"]
            v["nbv"] = v["cost_cf"] - v["dep_cf"]
            v["nbv_bf"] = v["cost_bf"] - v["dep_bf"]
            if any(abs(x) >= 0.005 for x in v.values()):
                classes.append({"name": class_name(chart, base), "codes": used, **{k: round(x, 2) for k, x in v.items()}})
        total = {k: round(sum(c[k] for c in classes), 2) for k in ROWS}
        return {"classes": classes, "total": total}

    return {
        "tangible": group(TANGIBLE),
        "intangible": group(INTANGIBLE),
        # "last year's job in the app", "the trial balance's opening balances", or "" (b/fwd codes taken as b/f)
        "opening_source": ("last year's job in the app" if getattr(last, "from_job", False)
                           else "the trial balance's opening balances" if last is not None else ""),
    }


def asset_charge(cost_cf: float, dep_bf: float, disposals: float, rate: float, method: str, given: float) -> float:
    """One asset's charge for the year, as the workbook's C1-1 formula: nothing on an asset sold in the year; SLM the
    cost times the rate, never more than the net book value; RBM the net book value times the rate; no rate: the
    register's own charge."""
    if not rate:
        return given
    if disposals > 0:
        return 0.0
    return min(cost_cf * rate, cost_cf - dep_bf) if method == "SLM" else (cost_cf - dep_bf) * rate


def register(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    """The asset register asset by asset (as the C1-1-FA detail): date, description,
    cost b/f, additions, disposals, cost c/f, depreciation b/f, rate and method, charge, depreciation on disposal,
    depreciation c/f, NBV this year and last; a total per class."""
    from backend.app.models.database import FixedAssetRecord
    from backend.app.services.workbook.fixed_assets import _rate_parts

    f = lambda v: float(v or 0)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for a in db.execute(select(FixedAssetRecord).where(FixedAssetRecord.engagement_id == engagement.id)).scalars():
        rate, method = _rate_parts(a.depr_rate_method)
        cost_cf = f(a.cost_bwd) + f(a.additions) - f(a.disposals)
        charge = asset_charge(cost_cf, f(a.depr_bwd), f(a.disposals), rate, method, f(a.depr_charge))
        dep_cf = f(a.depr_bwd) + charge - f(a.depr_disposals)
        groups.setdefault(a.category or "Fixed assets", []).append({
            "id": a.id, "description": a.description, "date": a.acquisition_date.isoformat() if a.acquisition_date else None,
            "rate": rate, "method": method, "cost_bf": round(f(a.cost_bwd), 2), "additions": round(f(a.additions), 2),
            "disposals": round(f(a.disposals), 2), "cost_cf": round(cost_cf, 2), "dep_bf": round(f(a.depr_bwd), 2),
            "charge": round(charge, 2), "dep_disposal": round(f(a.depr_disposals), 2), "dep_cf": round(dep_cf, 2),
            "nbv": round(cost_cf - dep_cf, 2), "nbv_bf": round(f(a.cost_bwd) - f(a.depr_bwd), 2),
            "residual_value": None if a.residual_value is None else round(float(a.residual_value), 2),
            "useful_life_years": a.useful_life_years})
    keys = ("cost_bf", "additions", "disposals", "cost_cf", "dep_bf", "charge", "dep_disposal", "dep_cf", "nbv", "nbv_bf")
    classes = [{"name": name, "assets": sorted(items, key=lambda x: (x["date"] is None, x["date"] or "")),
                "total": {k: round(sum(x[k] for x in items), 2) for k in keys}} for name, items in groups.items()]
    return {"classes": classes, "total": {k: round(sum(c["total"][k] for c in classes), 2) for k in keys}}
