"""An LLP's designated members and members are taken from the register as its directors are for a company,
so they need not be typed by hand."""
from datetime import date

from backend.app.services.setup import companies_house as ch


def test_officer_roles():
    assert ch.officer_role("director") == "Director"
    assert ch.officer_role("corporate-director") == "Director"
    assert ch.officer_role("llp-designated-member") == "Designated member"
    assert ch.officer_role("corporate-llp-designated-member") == "Designated member"
    assert ch.officer_role("llp-member") == "Member"
    assert ch.officer_role("secretary") is None


def test_llp_members_found(monkeypatch):
    replies = {
        "/company/OC000001": {"company_name": "TEST CO LLP", "company_status": "active"},
        "/company/OC000001/officers?items_per_page=100": {"items": [
            {"officer_role": "llp-designated-member", "name": "SMITH, Jane Ann", "appointed_on": "2020-01-01"},
            {"officer_role": "llp-designated-member", "name": "JONES, Tom", "appointed_on": "2020-01-01"},
            {"officer_role": "secretary", "name": "BROWN, Sam", "appointed_on": "2020-01-01"}]},
        "/company/OC000001/persons-with-significant-control?items_per_page=100": {"items": []},
    }
    monkeypatch.setattr(ch, "_get", lambda path: replies.get(path, {}))
    found = ch.people("OC000001", date(2025, 3, 31))
    assert {(p["name"], tuple(p["roles"])) for p in found["people"]} == {
        ("Jane Ann Smith", ("Designated member",)), ("Tom Jones", ("Designated member",))}
