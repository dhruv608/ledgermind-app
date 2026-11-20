"""HMRC's Self Assessment statement (SA300, made-up figures): the year's payments on account from its lines (R-FAM-03)."""

from backend.app.sa.extract import sa_statement as S
from backend.app.sa.extract.classify import classify


def test_the_years_payments_on_account():
    f = S.clean({"name": "MR P TEST", "lines": [
        {"date": "2025-01-31", "description": "Balancing payment due for year 23/24", "tax_due": "12,000.00"},
        {"date": "2025-01-31", "description": "1st payment on account due for year 24/25", "tax_due": 5000},
        {"date": "2025-01-30", "description": "Payment - thank you", "credit": 17000},
        {"date": "2025-07-31", "description": "2nd payment on account due for year 24/25", "tax_due": 5000}]})
    status, notes = S.checks(f, "2024-25", "Pat Test")
    assert f["poa_total"] == 10000.0 and "first £5,000.00 and second £5,000.00" in notes[0]
    assert S.checks(S.clean({"name": "Mrs A Other", "lines": [{"description": "x"}]}), "2024-25", "Pat Test")[0] == "CHECK"
    assert S.payments_on_account(f, "2025-26") == []


def test_named_as_a_statement():
    assert classify("", "HMRC Self-Assessment Statement Jun 2025.pdf") == "HMRC_STATEMENT"
