"""U-REC-001: a typed statement figure that does not agree to the books and has no reason is a query; agreed, explained,
within £1, or an account with its own statement rule (PAYE, pension, loans) is not."""

from datetime import date
from types import SimpleNamespace

import backend.app.services.review.statement_differences as sd
import backend.app.services.tax.ct_computation as ctc


class Chart:
    def name(self, code, default=""):
        return f"Account {code}"


def _tb(code, name):
    return SimpleNamespace(std_code=code, raw_account_name=name, net_amount=0, opening_amount=0)


def _run(monkeypatch, inputs, bal, tb):
    monkeypatch.setattr(sd, "entered_inputs", lambda db, eid: inputs)
    monkeypatch.setattr(ctc, "final_balances", lambda eid, tb, db: bal)
    eng = SimpleNamespace(id="e1", period_end_date=date(2025, 3, 31))
    return sd.unexplained_differences(eng, tb, Chart(), None, 1000.0)


def test_bank_difference_is_a_query(monkeypatch):
    out = _run(monkeypatch, {"bank:4800": {"balance": 9000.0}}, {4800: 10500.0}, [_tb(4800, "Barclays Current")])
    assert len(out) == 1
    f = out[0]
    assert f.procedure_ref == "U-REC-001" and f.severity == "HIGH" and f.quantified_amount == 1500.0
    assert "Barclays Current" in f.finding_title and "Query to the client" in f.finding_details


def test_agreed_explained_or_small_is_not(monkeypatch):
    tb = [_tb(4800, "Bank"), _tb(4801, "Savings"), _tb(4802, "Card"), _tb(5200, "Creditors")]
    inputs = {"bank:4800": {"balance": 100.0, "note": "cheque 123 not presented"},
              "bank:4801": {"balance": 200.5},
              "code:5200": {"agreed": True},
              "bank:4802": {}}
    assert _run(monkeypatch, inputs, {4800: 500.0, 4801: 200.0, 4802: 50.0, 5200: -900.0}, tb) == []


def test_own_rule_accounts_are_left_to_it(monkeypatch):
    tb = [_tb(5320, "PAYE"), _tb(5352, "Pension"), _tb(5100, "Bank loan")]
    inputs = {"code:5320": {"balance": -10.0}, "code:5352": {"balance": -10.0}, "code:5100": {"balance": -10.0}}
    assert _run(monkeypatch, inputs, {5320: -900.0, 5352: -900.0, 5100: -900.0}, tb) == []


def test_other_account_medium_below_materiality(monkeypatch):
    out = _run(monkeypatch, {"code:5200": {"balance": -900.0}}, {5200: -1000.0}, [_tb(5200, "Trade creditors")])
    assert len(out) == 1 and out[0].severity == "MEDIUM" and "statement / supporting document" in out[0].finding_title
