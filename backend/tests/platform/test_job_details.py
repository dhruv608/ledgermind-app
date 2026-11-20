"""Job details are kept apart in the setup, and a client details save keeps them."""

import json
from types import SimpleNamespace as N

from backend.app.api.endpoints import job_details as jd
from backend.app.services.setup.profile_service import ProfileService


class Db:
    def get(self, *_):
        return object()

    def commit(self):
        pass


def test_save_and_keep(monkeypatch):
    profile = N(setup=json.dumps({"client": {"x": 1}, "data": {"first_year": True}}))
    monkeypatch.setattr(ProfileService, "get_or_create_profile", staticmethod(lambda db, eid: profile))
    saved = jd.save_job_details("e", jd.JobDetails(due_date="2026-12-31", partner=" A Partner "), Db())
    assert saved["due_date"] == "2026-12-31" and saved["partner"] == "A Partner" and saved["assigned_to"] is None
    setup = json.loads(profile.setup)
    assert setup["client"] == {"x": 1} and setup["data"] == {"first_year": True} and setup["job"]["partner"] == "A Partner"
    assert jd.get_job_details("e", Db())["due_date"] == "2026-12-31"


def test_client_details_save_keeps_job(monkeypatch):
    profile = N(setup=json.dumps({"job": {"partner": "P"}, "data": {"d": 1}}), confirmed_fields="[]")
    monkeypatch.setattr(ProfileService, "get_or_create_profile", staticmethod(lambda db, eid: profile))
    db = N(commit=lambda: None, refresh=lambda p: None)
    ProfileService.update_profile(db, "e", {"setup": {"client": {"name": "X"}}})
    setup = json.loads(profile.setup)
    assert setup == {"job": {"partner": "P"}, "data": {"d": 1}, "client": {"name": "X"}}
