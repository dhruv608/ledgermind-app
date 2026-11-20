"""A bank balance's statement date and page (and a currency rate's source) are saved with it and fill the workbook's
'Statement date / page' box."""
from datetime import date
from types import SimpleNamespace as N

from backend.app.api.endpoints import reconciliations as rec
from backend.app.services.workbook.balance_tabs.bank import _statement_ref


def test_saved_with_the_balance(monkeypatch):
    saved = {}
    monkeypatch.setattr(rec, "mark_changed", lambda db, eid: None)
    import backend.app.services.reconciliation.control_accounts as svc
    monkeypatch.setattr(svc, "save_input", lambda db, eid, key, value, uid: saved.update({key: value}))
    monkeypatch.setattr(svc, "reconciliations", lambda eng, db: [])
    monkeypatch.setattr(svc, "summary", lambda rows: {"rows": rows})
    db = N(get=lambda model, eid: N(id=eid))
    req = N(state=N(user=None))
    rec.save_reconciliation_entry("e1", rec.ReconciliationEntry(
        key="bank:4800", balance=125.5, statement_date=date(2025, 3, 31), page=" 3 "), req, db)
    assert saved["bank:4800"] == {"balance": 125.5, "statement_date": "2025-03-31", "page": "3"}
    rec.save_reconciliation_entry("e1", rec.ReconciliationEntry(
        key="bank:4803", currency_amount=100, rate=1.25, rate_source="HMRC monthly rate"), req, db)
    assert saved["bank:4803"]["rate_source"] == "HMRC monthly rate"
    # A rate source is kept only for a currency balance
    rec.save_reconciliation_entry("e1", rec.ReconciliationEntry(key="bank:4801", balance=1, rate_source="x"), req, db)
    assert "rate_source" not in saved["bank:4801"]


def test_workbook_box():
    assert _statement_ref({"statement_date": "2025-03-31", "page": "3"}) == "31/03/2025, page 3"
    assert _statement_ref({"page": "2"}) == "page 2"
    assert _statement_ref({"balance": 5}) is None
