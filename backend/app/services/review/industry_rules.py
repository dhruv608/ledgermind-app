"""Industry rules: per industry, each rule's part (Data to request, Coding, Reconciliation, Red flags), what LM does,
the working paper tab, its level (Info / Amber / Red) and the firm codes it looks at. Kept in the rules store
(industry_rules) so a firm can edit them; 'built' says whether LM carries the rule out (the rest are shown as the
industry's checklist)."""

from typing import Any, Dict, List, Optional

from backend.app.services.shared import rules_store

PARTS = ("Data to request", "Coding", "Reconciliation", "Red flags")
LEVELS = ("Info", "Amber", "Red")


def catalogue(db=None) -> Dict[str, Any]:
    return rules_store.load("industry_rules", db)


def industry(code: str, db=None) -> Optional[Dict[str, Any]]:
    return next((i for i in catalogue(db)["industries"] if i["code"] == (code or "").upper()), None)


def rules_for(code: str, part: Optional[str] = None, db=None) -> List[Dict[str, Any]]:
    """The industry's rules, in catalogue order; only one part when asked."""
    code = (code or "").upper()
    return [r for r in catalogue(db)["rules"] if r["industry"] == code and (part is None or r["part"] == part)]
