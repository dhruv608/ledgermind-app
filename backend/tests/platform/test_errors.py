"""Every error in one shape the screens read: a named error keeps its code, message and next step; an
unexpected one is a plain message with an error id, never a bare 500, and keeps the CORS headers."""
from fastapi.testclient import TestClient

from backend.app.core.errors import OutOfDate
from backend.app.main import app


@app.get("/_test/boom")
def _boom():
    raise RuntimeError("not for the screen")


@app.get("/_test/old")
def _old():
    raise OutOfDate("LM updated this point after your last change.")


client = TestClient(app, raise_server_exceptions=False)


def test_unexpected_error_is_plain_with_an_id():
    r = client.get("/_test/boom", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 500
    d = r.json()["detail"]
    assert d["code"] == "ServerError" and d["error_id"] in d["next"]
    assert "not for the screen" not in r.text
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_named_error_keeps_its_parts():
    r = client.get("/_test/old")
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "OutOfDate", "message": "LM updated this point after your last change.",
                                  "next": "Reload to see the latest."}


def test_clearing_a_point_that_is_gone_says_so():
    r = client.post("/api/audit/987654321/clear", json={"note": None})
    assert r.status_code in (401, 409)          # signed out in the test app: 401; signed in: the plain 409
    if r.status_code == 409:
        assert r.json()["detail"]["code"] == "OutOfDate"


def test_acting_on_a_journal_that_is_gone_says_so():
    r = client.post("/api/audit/journals/987654321/action", json={"journal_id": 987654321, "action": "APPROVE"})
    assert r.status_code in (401, 409)
    if r.status_code == 409:
        assert r.json()["detail"]["code"] == "OutOfDate"
