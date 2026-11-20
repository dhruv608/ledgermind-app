"""Working papers the accountant adds: create, the reconciliation's difference, update, delete."""

from types import SimpleNamespace as N

import pytest
from fastapi import HTTPException

from backend.app.api.endpoints import custom_papers as cp
from backend.app.core.database import SessionLocal


def test_add_update_delete(monkeypatch):
    monkeypatch.setattr(cp, "_engagement", lambda db, eid: None)
    db = SessionLocal()
    req = N(state=N(user=None))
    body = cp.PaperIn(area="loans", kind="RECONCILIATION", name="Loan to statement",
                      lines=[cp.PaperLine(side="DEBIT", label="Per books", amount=1000),
                             cp.PaperLine(side="CREDIT", label="Per statement", amount=950)])
    p = cp.add_paper("test-eng", body, req, db)
    assert p["difference"] == 50 and p["kind"] == "RECONCILIATION"
    p = cp.update_paper("test-eng", p["id"], cp.PaperUpdate(lines=[cp.PaperLine(side="DEBIT", label="x", amount=5)]), db)
    assert p["debit"] == 5 and p["credit"] == 0
    assert any(x["id"] == p["id"] for x in cp.list_papers("test-eng", db))
    cp.delete_paper("test-eng", p["id"], db)
    with pytest.raises(HTTPException):
        cp.add_paper("test-eng", cp.PaperIn(area="loans", kind="DETAILED", name="No account"), req, db)
    db.close()
