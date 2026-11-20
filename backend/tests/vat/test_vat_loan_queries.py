"""VT-01 a VAT return with no payment seen and LN-01 a loan with no repayment in the year. Made-up
figures."""
from datetime import date
from types import SimpleNamespace as N

from backend.app.services.queries import vat_rules
from backend.app.services.queries.loan_rules import loan_queries


def test_unpaid_return_is_asked_recent_one_is_not(monkeypatch):
    returns = [{"period_end": "2024-06-30", "owed": 1200.0, "paid": 1200.0, "opening": False},
               {"period_end": "2024-09-30", "owed": 950.0, "paid": 0.0, "opening": False},
               {"period_end": "2025-03-31", "owed": 700.0, "paid": 0.0, "opening": False}]   # due after the year end
    monkeypatch.setattr("backend.app.services.reconciliation.control_accounts.vat_paid_per_return",
                        lambda eng, db: {"source": "ledger", "returns": returns})
    out = vat_rules.vat_queries(None, N(period_end_date=date(2025, 3, 31)))
    assert len(out) == 1 and "30/09/2024" in out[0]["detail"] and "31/03/2025" not in out[0]["detail"]


def test_no_vat_data_no_query(monkeypatch):
    monkeypatch.setattr("backend.app.services.reconciliation.control_accounts.vat_paid_per_return",
                        lambda eng, db: {"source": "", "returns": []})
    assert vat_rules.vat_queries(None, N(period_end_date=date(2025, 3, 31))) == []


def test_loan_with_no_repayment(monkeypatch):
    monkeypatch.setattr("backend.app.services.review.last_year.last_year_job", lambda eng, db: None)
    tb = [N(std_code=5500, net_amount=-20000.0, opening_amount=-24000.0, raw_account_name="Funding Circle loan"),
          N(std_code=5100, net_amount=-8000.0, opening_amount=-9000.0, raw_account_name="Bank loan")]
    lines = [N(account="Bank loan", code=5100, debit=1000.0, credit=0.0, source="Bank", description="Repayment")]
    out = loan_queries(None, N(period_end_date=date(2025, 3, 31), id="e"), tb, {}, lines)
    ln = [q for q in out if q["ref"] == "LN-01"]
    assert len(ln) == 1 and "Funding Circle loan" in ln[0]["detail"] and "Bank loan:" not in ln[0]["detail"]
