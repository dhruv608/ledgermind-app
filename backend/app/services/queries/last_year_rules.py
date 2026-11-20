"""Queries carried forward from last year's working paper: last year's open queries stay open queries.

  LY-01 last year's Notes & Queries points that asked the client for something (read when last year's final working
        paper is uploaded: ingestion/last_year_adjustments.open_queries): one query for the accountant listing them,
        to check each was answered or still applies this year."""

import json
from typing import Any, Dict, List

from backend.app.models.database import ClientEngagement
from backend.app.services.queries.r1_rules import _query


def last_year_queries(eng: ClientEngagement, profile) -> List[Dict[str, Any]]:
    from backend.app.services.queries.query_list import ACCOUNTANT
    try:
        inputs = json.loads(getattr(profile, "tax_inputs", None) or "{}")
    except ValueError:
        return []
    points = (inputs.get("_last_year_wp") or {}).get("open_queries") or []
    if not points:
        return []
    lines = [f"{p.get('no', '')} {p.get('area', '')}: {p.get('text', '')[:200]}".strip() for p in points]
    return [_query("LY-01", ACCOUNTANT, f"Last year's points for the client: {len(points)}",
                   "Last year's working paper asked the client to check or confirm these points. Check each one was "
                   "answered, and whether it still applies this year (the same balance, loan, stock or accrual).",
                   lines=lines, rule="LY-01")]
