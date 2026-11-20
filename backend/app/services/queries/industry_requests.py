"""The documents a client in its industry is asked for (the industry rules' 'data to request' part). Once the accountant has confirmed the industry, one client query lists them, each with
what the documents feed in the working papers; the client answers line by line. Nothing is asked before the industry
is confirmed (an app guess from a few ledger lines is not enough: one takeaway lunch does not make a restaurant)."""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement


def industry_requests(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    from backend.app.services.queries.query_list import CLIENT, _query
    from backend.app.services.review.industry_rules import industry, rules_for
    from backend.app.services.setup.profile_service import confirmed_industry
    code = confirmed_industry(getattr(eng, "profile", None))
    if not code:
        return []
    asks = rules_for(code, "Data to request", db)
    if not asks:
        return []
    name = industry(code, db)["name"]
    items = [{"key": r["id"], "text": r["rule"], "answer": "", "answered": False} for r in asks]
    detail = "\n".join(f"- {r['rule']}" for r in asks)
    return [_query(f"industry:{code}", "rules", 1, CLIENT, f"Documents we need for a {name.lower()} business",
                   f"For a {name.lower()} business we also need:\n{detail}", items=items)]
