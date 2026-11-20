"""Industry rules: the 16 industries and 137 rules load, and SIC codes pick the right industry."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.review.industry_rules import LEVELS, PARTS, catalogue, industry, rules_for
from backend.app.services.setup.companies_house import industry_from_sic
from backend.app.services.setup.engagement_setup import INDUSTRY_NAMES


def test_catalogue_complete():
    c = catalogue()
    codes = [i["code"] for i in c["industries"]]
    assert len(codes) == 16 and len(set(codes)) == 16
    assert len(c["rules"]) == 137
    assert len({r["id"] for r in c["rules"]}) == 137
    for r in c["rules"]:
        assert r["industry"] in codes and r["part"] in PARTS and r["level"] in LEVELS
    for i in c["industries"]:
        assert i["code"] in INDUSTRY_NAMES and len(rules_for(i["code"])) == i["rules"]


def test_rules_by_part():
    assert industry("con")["name"].startswith("Construction")
    asks = rules_for("CON", "Data to request")
    assert asks and all(r["part"] == "Data to request" for r in asks)


def test_sic_picks_the_industry():
    cases = {"68100": "PRD", "41100": "PRD", "41201": "CON", "68209": "PRP", "96020": "HBB", "88990": "CHR",
             "94910": "CHR", "86210": "HLT", "87100": "HLT", "64209": "HLD", "64303": "HLD", "56101": "RES",
             "47910": "ECM", "62020": "SAAS"}
    for sic, code in cases.items():
        assert industry_from_sic([sic]) == code, sic
