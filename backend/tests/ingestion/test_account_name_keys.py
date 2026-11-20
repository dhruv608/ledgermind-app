"""Matching a TB account to its ledger lines by name: a TB that writes the firm's code before the client's
('5200 - 800 - Creditors') matches a ledger naming the account alone ('Creditors')."""
from backend.app.services.mapping.chart_lookup import account_name_keys


def test_double_coded_name_matches_the_plain_ledger_name():
    assert "creditors" in account_name_keys("5200 - 800 - Creditors")
    assert "purchases" in account_name_keys("1100 - 304 - Purchases")


def test_existing_keys_kept_most_exact_first():
    assert account_name_keys("2305 - Directors Loan") == ["2305 - directors loan", "directors loan"]
    assert account_name_keys("Sub-Contractors:Mira")[0] == "sub-contractors:mira"
    assert account_name_keys("Rent") == ["rent"]
