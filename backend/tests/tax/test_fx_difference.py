"""U-REC-002: a currency bank statement typed at the year-end rate -> the exchange difference journal to 3562."""
import os
from datetime import date
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import backend.app.services.review.fx_difference as fx
import backend.app.services.tax.ct_computation as ctc
from backend.app.services.review.fx_difference import currency_entry, fx_journals


class Chart:
    def name(self, code, default=""):
        return f"Account {code}"


TB = [N(std_code=4806, raw_account_name="Revolut USD", net_amount=1000.0, opening_amount=0)]
ENG = N(id="e1", period_end_date=date(2025, 3, 31))


def _run(monkeypatch, entered, books=1000.0):
    monkeypatch.setattr(fx, "entered_inputs", lambda db, eid: {"bank:4806": entered})
    monkeypatch.setattr(ctc, "final_balances", lambda eid, tb, db: {4806: books})
    return fx_journals(ENG, TB, Chart(), None, [1])


def test_gain_and_loss(monkeypatch):
    points, journals = _run(monkeypatch, {"currency_amount": 1400.0, "rate": 1.25})      # £1,120 v £1,000
    assert journals[0].debit_code == 4806 and journals[0].credit_code == 3562 and journals[0].amount == 120.0
    assert "gain" in points[0].finding_title
    points, journals = _run(monkeypatch, {"currency_amount": 1150.0, "rate": 1.25})      # £920
    assert journals[0].debit_code == 3562 and journals[0].credit_code == 4806 and journals[0].amount == 80.0


def test_sterling_figure_or_no_difference_gives_no_journal(monkeypatch):
    assert not currency_entry({"balance": 900.0})
    assert _run(monkeypatch, {"balance": 900.0}) == ([], [])
    assert _run(monkeypatch, {"currency_amount": 1250.0, "rate": 1.25}) == ([], [])
