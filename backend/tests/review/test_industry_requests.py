"""The 'Data to request' industry rules: one client query once the industry is confirmed, none before."""
import json
import os
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.queries.industry_requests import industry_requests


def _eng(code, confirmed):
    return N(profile=N(industry_code=code, confirmed_fields=json.dumps(["industry_code"] if confirmed else [])))


def test_confirmed_construction_client_is_asked():
    out = industry_requests(None, _eng("CON", True))
    assert len(out) == 1
    q = out[0]
    assert q["key"] == "industry:CON" and q["audience"] == "CLIENT" and q["round"] == 1
    assert any("CIS" in i["text"] for i in q["items"]) and len(q["items"]) >= 3
    assert "construction" in q["title"].lower()


def test_not_confirmed_or_general_is_not_asked():
    assert industry_requests(None, _eng("CON", False)) == []
    assert industry_requests(None, _eng("UNIV", True)) == []
