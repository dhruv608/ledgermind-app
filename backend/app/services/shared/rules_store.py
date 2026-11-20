"""The firm's editable rule files in the database: query rules, industry queries and setup, the
checklists, the re-analysis cards, the merchant dictionary, the firm's starting policies.

Each rule file is one JSON document with versions: saving a change adds a new version and keeps the old ones (who, when,
why), so a working paper can say which version it used and a change can be undone. With no version in the database the
file in backend/app/rules is the rule set (the seed), so nothing changes until a firm edits a rule.

Law figures (rates and limits in parameters.json, CT600 and VAT box rules) are not here: they are the same for every
firm and change only with the law, through the code and its tests.

firm_id is kept for the many-firm app; today there is one firm (as firm_settings) and it is NULL."""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from backend.app.core.database import Base, create_table

RULES_DIR = Path(__file__).resolve().parents[2] / "rules"
# The rule files a firm may edit (the names are the files' names without .json)
EDITABLE = ("query_triggers", "all_industry_queries", "engagement_rules", "industry_setup", "industry_detect",
            "checklists", "reanalysis_cards", "merchants", "firm_policies", "industry_rules")
CACHE_SECONDS = 60


class RuleSet(Base):
    __tablename__ = "rule_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(60), nullable=False, index=True)
    firm_id = Column(Integer, nullable=True, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)                  # JSON
    active = Column(Boolean, nullable=False, default=True)
    note = Column(String(255), nullable=True)               # why it was changed
    updated_by = Column(Integer, nullable=True)             # users.id
    updated_at = Column(DateTime, default=datetime.utcnow)


create_table(RuleSet.__table__)

_cache: Dict[str, tuple] = {}
_lock = threading.Lock()


def _seed(name: str) -> Any:
    return json.loads((RULES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _active(db, name: str, firm_id: Optional[int]) -> Optional[RuleSet]:
    q = db.query(RuleSet).filter(RuleSet.name == name, RuleSet.active.is_(True))
    rows = q.filter(RuleSet.firm_id == firm_id).all() if firm_id is not None else []
    rows = rows or q.filter(RuleSet.firm_id.is_(None)).all()
    return max(rows, key=lambda r: r.version) if rows else None


def load(name: str, db=None, firm_id: Optional[int] = None) -> Any:
    """The rule set in use: the firm's active version, else the default one in the database, else the seed file."""
    if name not in EDITABLE:
        return _seed(name)
    key = f"{name}:{firm_id}"
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = None
    try:
        if db is not None:
            row = _active(db, name, firm_id)
        else:
            from backend.app.core.database import SessionLocal
            with SessionLocal() as own:
                row = _active(own, name, firm_id)
        if row is not None:
            value = json.loads(row.content)
    except Exception:
        value = None                  # no table yet or no database: the seed
    if value is None:
        value = _seed(name)
    with _lock:
        _cache[key] = (now, value)
    return value


def save(db, name: str, content: Any, user_id: Optional[int] = None, note: str = "",
         firm_id: Optional[int] = None) -> RuleSet:
    """A new version of a rule set (the earlier ones kept as inactive)."""
    if name not in EDITABLE:
        raise ValueError(f"{name} is not an editable rule set")
    json.dumps(content)               # must be JSON
    rows = db.query(RuleSet).filter(RuleSet.name == name, RuleSet.firm_id.is_(firm_id) if firm_id is None
                                    else RuleSet.firm_id == firm_id).all()
    for r in rows:
        r.active = False
    row = RuleSet(name=name, firm_id=firm_id, version=max([r.version for r in rows] or [0]) + 1,
                  content=json.dumps(content, ensure_ascii=False), active=True, note=note[:255] or None,
                  updated_by=user_id)
    db.add(row)
    db.commit()
    with _lock:
        _cache.pop(f"{name}:{firm_id}", None)
    return row


def versions(db, name: str, firm_id: Optional[int] = None) -> List[Dict[str, Any]]:
    rows = db.query(RuleSet).filter(RuleSet.name == name).order_by(RuleSet.version.desc()).all()
    return [{"version": r.version, "active": r.active, "note": r.note, "updated_by": r.updated_by,
             "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows if r.firm_id == firm_id]
