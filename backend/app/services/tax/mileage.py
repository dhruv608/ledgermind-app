"""Approved mileage allowance rates by tax year (ITEPA 2003 s230, HMRC EIM31240), held in a table by
tax year. Cars and vans: 45p a mile for the first 10,000 business miles in the tax year to
2025-26, 55p from 2026-27; 25p after 10,000. Held in rules/parameters.json (P-AMAP-*), like the other rates."""

import json
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Tuple

PARAMETERS_FILE = Path(__file__).resolve().parents[2] / "rules" / "parameters.json"


@lru_cache(maxsize=1)
def _params():
    with open(PARAMETERS_FILE, encoding="utf-8") as f:
        return {p.get("Param_ID"): p for p in json.load(f)}


def _from(param) -> date:
    return datetime.strptime(param["Effective From"], "%d %b %Y").date()


def car_rates(on: date) -> Tuple[float, float]:
    """(pence per mile for the first 10,000 business miles, after 10,000) for a car or van on that date."""
    p = _params()
    first = p["P-AMAP-CAR"] if on >= _from(p["P-AMAP-CAR"]) else p["P-AMAP-CAR-PRIOR"]
    return float(first["Value"]), float(p["P-AMAP-CAR-OVER"]["Value"])


def _pence(v: float) -> str:
    return f"{round(v * 100)}p"


def rate_text(start: date, end: date) -> str:
    """The car rate for a company year, in words: one rate, or both when the year spans the change (6 April 2026)."""
    a, after = car_rates(start)
    b, _ = car_rates(end)
    if a == b:
        return f"{_pence(a)} a mile for the first 10,000 business miles in a tax year, {_pence(after)} after"
    change = _from(_params()["P-AMAP-CAR"])
    return (f"{_pence(a)} a mile for the first 10,000 business miles in the tax year to {change.replace(day=5):%d %B %Y} "
            f"and {_pence(b)} from {change:%d %B %Y}, {_pence(after)} after")
