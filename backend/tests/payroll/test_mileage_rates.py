"""Approved mileage rates by tax year (HMRC EIM31240: cars 45p to 2025-26, 55p from 2026-27; 25p after)."""
import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.tax.mileage import car_rates, rate_text


def test_rates_by_tax_year():
    assert car_rates(date(2026, 4, 5)) == (0.45, 0.25)
    assert car_rates(date(2026, 4, 6)) == (0.55, 0.25)


def test_text_one_rate_and_spanning_the_change():
    assert rate_text(date(2024, 4, 1), date(2025, 3, 31)).startswith("45p a mile for the first 10,000")
    assert rate_text(date(2026, 4, 6), date(2027, 3, 31)).startswith("55p a mile")
    both = rate_text(date(2025, 10, 1), date(2026, 9, 30))
    assert "45p" in both and "55p from 06 April 2026" in both and "25p after" in both


def test_s455_rate_on_the_g3_table():
    # HMRC CTM61505: 33.75% for loans from 6 April 2022, 35.75% from 6 April 2026
    from backend.app.services.workbook.dla_tests import s455_rate_for
    assert s455_rate_for(date(2026, 3, 31))[0] == 0.3375
    assert s455_rate_for(date(2026, 9, 30))[0] == 0.3575
