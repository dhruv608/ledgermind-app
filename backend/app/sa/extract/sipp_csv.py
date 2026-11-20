"""A SIPP's activity export (a CSV from the platform: Freetrade and the like) read by code: the person's own top-ups in the
tax year are relief at source pension contributions, entered as paid (net); the engine grosses them up (net / 0.8) and
extends the basic rate band (R-SAV-07). Dividends and interest inside the SIPP are never on the return (R-SAV-05)."""

import csv
import io
import re
from typing import Any, Dict, List, Optional

from backend.app.sa.extract.bank_csv import _money, _text

TOP_UP = re.compile(r"^(top[ _-]?up|deposit|contribution|personal contribution|pension contribution)$", re.I)


def looks_like(name: str, data: bytes) -> bool:
    """A CSV named for a SIPP whose header has a type and an amount column."""
    if not re.search(r"\bsipp\b|_sipp|sipp_", (name or "").lower()):
        return False
    head = _text(data[:2000]).splitlines()[:1]
    return bool(head) and bool(re.search(r"\btype\b", head[0], re.I)) and bool(re.search(r"amount", head[0], re.I))


def read(data: bytes, start: str, end: str) -> Dict[str, Any]:
    """{contributions: [(date, amount)], total} for the top-ups dated in the period."""
    rows = list(csv.DictReader(io.StringIO(_text(data))))
    out: List = []
    for r in rows:
        kind = (r.get("Type") or r.get("type") or "").strip()
        when = (r.get("Timestamp") or r.get("Date") or r.get("date") or "")[:10]
        amount = next((_money(v) for k, v in r.items() if k and re.search(r"total amount|^amount", k, re.I) and _money(v)), None)
        if TOP_UP.match(kind) and amount and start <= when <= end:
            out.append((when, abs(amount)))
    return {"contributions": out, "total": round(sum(a for _, a in out), 2)}


def as_pension(name: str, data: bytes, start: str, end: str) -> Optional[Dict[str, Any]]:
    """The fields a pension statement gives (pension.py), for the pension sync: one relief at source contribution."""
    f = read(data, start, end)
    if not f["total"]:
        return None
    provider = re.sub(r"[_-]+", " ", (name or "").replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]).strip()
    return {"items": [{"kind": "CONTRIBUTION", "basis": "RELIEF_AT_SOURCE", "amount": f["total"],
                       "name": f"SIPP top-ups ({provider[:60]})"}], "sipp_contributions": f["contributions"]}
