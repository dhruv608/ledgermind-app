"""The Adjustments block under the trade debtors / creditors T."""

from datetime import date
from types import SimpleNamespace as N

from backend.app.services.reconciliation import trade_adjustments as ta
from backend.app.services.sop.duplicates import DuplicateFlag, LedgerDocument


def test_lines_from_the_duplicates_sop(monkeypatch):
    flags = [DuplicateFlag("supplier", "duplicate", "Acme", 120.0, "", "same bill twice"),
             DuplicateFlag("supplier", "possible", "Acme", 30.0, "", "no number"),
             DuplicateFlag("supplier", "unallocated", "Bolt", 50.0, "", "bill open, paid direct"),
             DuplicateFlag("customer", "duplicate", "Cust", 999.0, "", "not this side")]
    docs = [LedgerDocument("supplier", "direct", date(2025, 5, 1), "Shop", "", 20.0, "Expense"),
            LedgerDocument("supplier", "document", date(2025, 5, 1), "Acme", "B1", 120.0, "Bill")]
    monkeypatch.setattr("backend.app.services.sop.duplicates.duplicate_review", lambda *a: flags)
    monkeypatch.setattr("backend.app.services.sop.duplicates.ledger_documents", lambda *a: docs)
    monkeypatch.setattr("backend.app.services.papers.rollforward.rollforward",
                        lambda *a: {"difference": 0.0, "opening": -10.0, "opening_source": "x", "tb_closing": -20.0})
    out = {l["key"]: l for l in ta.trade_adjustments(N(id="e", period_end_date=date(2026, 3, 31)), None, "supplier")["lines"]}
    assert out["duplicate"]["amount"] == 150.0 and out["duplicate"]["count"] == 2 and "1 of them possible" in out["duplicate"]["note"]
    assert out["unallocated"]["amount"] == 50.0
    assert out["direct"]["amount"] == 20.0 and out["direct"]["count"] == 1
    assert out["opening"]["amount"] == 0.0
