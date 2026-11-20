"""Credit card tabs: a creditor code gets a card tab only when every account on it is a card."""
from types import SimpleNamespace as NS

from backend.app.services.workbook.balance_tabs import cards


def _ctx(records):
    return NS(records=records)


def test_card_codes(monkeypatch):
    by_code = {
        5351: [NS(raw_account_name="5351 - MASTERCARD", net_amount=-1777.04, opening_amount=0.0)],
        5352: [NS(raw_account_name="5352 - Pension Payable", net_amount=-400.0, opening_amount=0.0)],
        5353: [NS(raw_account_name="5353 - Capital On Tap Credit Card", net_amount=-331.6, opening_amount=0.0)],
        5354: [NS(raw_account_name="5354 - CAPITAL ON TAP Loan", net_amount=-10000.0, opening_amount=0.0)],
        5355: [NS(raw_account_name="5355 - Amex", net_amount=0.0, opening_amount=0.0)],          # nil all year
    }
    monkeypatch.setattr(cards, "_records", lambda ctx, codes: by_code.get(codes[0], []))
    assert cards.card_codes(_ctx(None)) == [5351, 5353]


def test_a_code_shared_with_other_accounts_is_left(monkeypatch):
    by_code = {5351: [NS(raw_account_name="Credit card", net_amount=-50.0, opening_amount=0.0),
                      NS(raw_account_name="Accruals", net_amount=-900.0, opening_amount=0.0)]}
    monkeypatch.setattr(cards, "_records", lambda ctx, codes: by_code.get(codes[0], []))
    assert cards.card_codes(_ctx(None)) == []
