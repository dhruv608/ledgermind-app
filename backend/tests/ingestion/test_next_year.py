"""Next year's ledger read with the general ledger reader; the window after the year end."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.ingestion.next_year import WINDOW_DAYS, _number


def test_window_and_numbers():
    assert WINDOW_DAYS == 275          # nine months: s455 repaid in time (s458)
    assert _number("12.5") == 12.5 and _number(None) == 0.0 and _number("x") == 0.0
