"""Industry red flags: the margin against last year and the charity framework tests, and every
new library query has its trigger."""
import json
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import backend.app.services.review.last_year as ly
from backend.app.services.review.qt_industry import framework_is, margin_vs_last_year

RULES = Path(__file__).resolve().parents[2] / "app" / "rules"


class Ctx:
    def __init__(self, bal, framework="FRS102_1A"):
        self.bal, self.engagement, self.db = bal, None, None
        self.record = {"client": {"framework": framework}}
        self.sections = {0: "Sales", 1100: "Cost of sales"}

    def section(self, code):
        return self.sections.get(code, "")

    @property
    def sales(self):
        return -sum(v for k, v in self.bal.items() if self.section(k) == "Sales")


def test_margin_moved_from_last_year(monkeypatch):
    monkeypatch.setattr(ly, "prior_balances_by_code", lambda e, db: {0: -100000.0, 1100: 40000.0})
    hit = margin_vs_last_year(Ctx({0: -100000.0, 1100: 55000.0}), {"points": 10})   # 45% now v 60% last year
    assert hit and "-15.0 points" in hit.title
    assert margin_vs_last_year(Ctx({0: -100000.0, 1100: 45000.0}), {"points": 10}) is None   # 55%: 5 points


def test_charity_on_frs105_is_flagged():
    p = {"frameworks": ["FRS105"], "why": "SORP"}
    assert framework_is(Ctx({}, "FRS105"), p)
    assert framework_is(Ctx({}, "FRS102_1A"), p) is None


def test_every_new_industry_query_has_a_trigger():
    lib = json.load(open(RULES / "all_industry_queries.json", encoding="utf-8"))
    trg = json.load(open(RULES / "query_triggers.json", encoding="utf-8"))
    new = [q["Query_ID"] for q in lib if q["Query_ID"].startswith("IND-")]
    assert len(new) == 24 and all(q in trg for q in new)
    assert all(chr(8) not in str(v) for q in new for v in trg[q].values())   # no backspace character in any trigger
    rules = json.load(open(RULES / "industry_rules.json", encoding="utf-8"))["rules"]
    built = {r["id"] for r in rules if r["built"]}
    assert set(new) <= built
