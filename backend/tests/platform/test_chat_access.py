"""The test chat page (/chat): the 4-digit code, the device remembered, what the code reaches, the daily limit, and
the cost meter at AWS's real London prices."""
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/chat_access.db"

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.api import api_router
from backend.app.core import ai_usage
from backend.app.core.config import settings
from backend.app.core.database import Base, SessionLocal, engine
from backend.app.models.chat import AssistantSpend, ChatMessage, ChatSession
from backend.app.services.assistant import chat_access

Base.metadata.create_all(engine)

app = FastAPI()
app.include_router(api_router, prefix="/api/v1")
PAGE = {chat_access.CHAT_HEADER: "1"}


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_PIN", "2005")
    monkeypatch.setattr(settings, "CHAT_DAILY_LIMIT_USD", 5.0)
    chat_access.reset_tries()
    monkeypatch.setattr("backend.app.api.endpoints.chat_access.WRONG_DELAY", 0)
    yield
    chat_access.reset_tries()


def _client(ip="1.1.1.1"):
    return TestClient(app, headers={"x-forwarded-for": ip})


def test_off_without_a_code(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_PIN", "")
    c = _client()
    assert c.get("/api/v1/chat-access/status").json() == {"enabled": False, "unlocked": False}
    assert c.post("/api/v1/chat-access/code", json={"code": "2005"}).status_code == 404


def test_right_code_remembers_the_device_and_reaches_only_the_assistant():
    c = _client()
    assert c.get("/api/v1/chat-access/status").json()["unlocked"] is False
    assert c.get("/api/v1/assistant/sessions", headers=PAGE).status_code == 401
    r = c.post("/api/v1/chat-access/code", json={"code": "2005"})
    assert r.status_code == 200 and chat_access.CHAT_COOKIE in r.cookies
    assert c.get("/api/v1/chat-access/status").json()["unlocked"] is True
    # The chat page's own chats, with no client
    chat = c.post("/api/v1/assistant/sessions", json={}, headers=PAGE).json()
    assert chat["engagement_id"] is None
    assert any(x["id"] == chat["id"] for x in c.get("/api/v1/assistant/sessions", headers=PAGE).json())
    # A client cannot be attached: the test user owns none
    assert c.post("/api/v1/assistant/sessions", json={"engagement_id": "someone-elses"}, headers=PAGE).status_code == 404
    # Without the page's header, or anywhere else in the app, the code's cookie is not a sign-in
    assert c.get("/api/v1/assistant/sessions").status_code == 401
    assert c.get("/api/v1/assistant/sessions?chat=1").status_code == 200        # a picture or download link
    assert c.get("/api/v1/engagements/?chat=1").status_code == 401
    assert c.get("/api/v1/engagements/").status_code == 401
    assert c.get("/api/v1/firm-rules/").status_code == 401
    # Put in the sign-in cookie, the token is refused too (the test user is not active)
    token = r.cookies[chat_access.CHAT_COOKIE]
    assert TestClient(app, cookies={"ff_session": token}).get("/api/v1/engagements/").status_code == 401
    # Forgotten: asked for the code again
    c.post("/api/v1/chat-access/forget")
    assert c.get("/api/v1/assistant/sessions", headers=PAGE).status_code == 401


def test_the_test_user_can_never_sign_in():
    db = SessionLocal()
    from backend.app.services.shared.auth import authenticate
    user = chat_access.tester(db)
    assert user.active is False and authenticate(db, chat_access.TESTER_EMAIL, "none") is None
    db.close()


def test_wrong_codes_lock_the_address_then_everyone():
    c = _client("2.2.2.2")
    for _ in range(chat_access.PER_ADDRESS_TRIES):
        assert c.post("/api/v1/chat-access/code", json={"code": "1234"}).status_code == 401
    # Locked: even the right code waits
    assert c.post("/api/v1/chat-access/code", json={"code": "2005"}).status_code == 429
    # Another address may still try, until 20 wrong codes in the hour lock the code for everyone
    for i in range(chat_access.ALL_TRIES - chat_access.PER_ADDRESS_TRIES):
        _client(f"3.3.3.{i}").post("/api/v1/chat-access/code", json={"code": "0000"})
    assert _client("4.4.4.4").post("/api/v1/chat-access/code", json={"code": "2005"}).status_code == 429


def test_daily_limit_and_meter():
    c = _client("5.5.5.5")
    c.post("/api/v1/chat-access/code", json={"code": "2005"})
    chat = c.post("/api/v1/assistant/sessions", json={}, headers=PAGE).json()
    db = SessionLocal()
    user = chat_access.tester(db)
    db.query(AssistantSpend).filter(AssistantSpend.user_id == user.id).delete()
    db.query(ChatMessage).filter(ChatMessage.session_id.in_(
        db.query(ChatSession.id).filter(ChatSession.user_id == user.id))).delete(synchronize_session=False)
    db.add(ChatMessage(session_id=chat["id"], role="assistant", content="An answer", model="deepseek.v3.2",
                       tokens_in=10000, tokens_out=1000, cost_usd=Decimal("0.012")))
    db.commit()
    chat_access.add_spend(db, user, "voice", seconds=10, usd=ai_usage.transcribe_cost(10, streams=2))
    m = c.get(f"/api/v1/assistant/meter?session_id={chat['id']}", headers=PAGE).json()
    assert m["today"]["tokens_in"] == 10000 and m["today"]["answers"] == 1
    assert m["today"]["voice_seconds"] == 10 and m["today"]["voice_usd"] == pytest.approx(0.005, abs=1e-4)
    assert m["today"]["usd"] == pytest.approx(0.017, abs=1e-4)
    assert m["limit_usd"] == 5.0 and m["prices"]["deepseek.v3.2"] == {"in": 0.961, "out": 2.8675}
    # Over the day's limit: no more answers, voice or files today
    db.add(AssistantSpend(user_id=user.id, kind="voice", cost_usd=Decimal("5")))
    db.commit()
    db.close()
    r = c.post(f"/api/v1/assistant/sessions/{chat['id']}/messages", json={"text": "What is the VAT threshold?"},
               headers=PAGE)
    assert r.status_code == 429 and "limit" in r.json()["detail"]
    assert c.post("/api/v1/assistant/voice", content=b"\0" * 32000, headers=PAGE).status_code == 429


def test_real_london_prices_and_the_collector():
    assert ai_usage.cost("deepseek.v3.2", 1_000_000, 1_000_000) == pytest.approx(0.961 + 2.8675)
    assert ai_usage.transcribe_cost(3) == pytest.approx(15 * ai_usage.TRANSCRIBE_PER_SECOND)      # 15 s at least
    with ai_usage.collect() as calls:
        ai_usage.record("deepseek.v3.2", "text", "order the pages", {"usage": {"inputTokens": 1000, "outputTokens": 10}})
    ai_usage.record("deepseek.v3.2", "text", "outside", {"usage": {"inputTokens": 5, "outputTokens": 5}})
    assert len(calls) == 1 and calls[0]["in"] == 1000
