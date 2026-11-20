"""The E2.2 / G2.2 listing's flags, one rule for the listing and the items to look at."""
from datetime import date
from types import SimpleNamespace as N

from backend.app.services.workbook.open_item_listing import item_flags

YE = date(2025, 3, 31)


def test_flags():
    old = N(contact="Customer A", when=date(2024, 11, 1), number="1", amount=500.0)
    assert item_flags(old, YE, False, {}, set()) == ["Over 90 days"]
    credit = N(contact="Customer B", when=date(2025, 3, 1), number="2", amount=-20.0)
    assert item_flags(credit, YE, False, {}, set()) == ["Credit balance (the company owes the customer)"]
    debit_supplier = N(contact="Supplier C", when=date(2025, 3, 1), number="3", amount=-20.0)
    assert item_flags(debit_supplier, YE, True, {}, set())[0].startswith("Debit balance")
    fresh = N(contact="Customer D", when=date(2025, 3, 20), number="4", amount=100.0)
    assert item_flags(fresh, YE, False, {}, set()) == []


def test_no_vat_flag():
    item = N(contact="Customer E", when=date(2025, 3, 10), number="5", amount=120.0)
    doc = {"gross": 120.0, "vat": 0.0, "texts": {"customer e"}, "contact": "customer e"}
    by_day = {date(2025, 3, 10): [doc]}
    assert "No VAT" in item_flags(item, YE, False, by_day, {"customer e"})[0]
