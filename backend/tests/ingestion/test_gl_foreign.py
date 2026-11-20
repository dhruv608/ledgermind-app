"""Ledger lines in another currency: the rate and foreign amount kept for a line in euros or dollars,
none for a line in pounds (rate 1, its 'foreign amount' the same pounds)."""

import pandas as pd

from backend.app.api.endpoints.upload import _foreign_of
from backend.app.services.workbook.core_tabs import _foreign_cells


def test_a_line_in_another_currency_keeps_its_rate_and_amount():
    assert _foreign_of(pd.Series({"Exchange Rate": 0.855213, "Foreign Amount": 2350.65, "Currency": "eur"})) == \
        ("EUR", 0.855213, 2350.65)
    assert _foreign_of(pd.Series({"Exchange Rate": "0.752678", "Foreign Amount": "-6"})) == (None, 0.752678, -6.0)
    assert _foreign_cells("USD", 0.78, 100.0) == ("USD", 0.78, 100.0)


def test_a_line_in_pounds_keeps_nothing():
    assert _foreign_of(pd.Series({"Exchange Rate": 1, "Foreign Amount": 100.0})) is None
    assert _foreign_of(pd.Series({"Exchange Rate": 1.0, "Foreign Amount": 100.0, "Currency": "GBP"})) is None
    assert _foreign_of(pd.Series({"Debit": 5.0})) is None
    assert _foreign_of(pd.Series({"Exchange Rate": float("nan"), "Foreign Amount": float("nan")})) is None
    assert _foreign_cells(None, 1, 100.0) == (None, None, None) and _foreign_cells(None, None, None) == (None, None, None)
