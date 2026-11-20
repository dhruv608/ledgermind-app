"""The period starts the day after last year's TB date: a short period after a change of year end is not taken as 12
months (last year's TB as of 31 March, period to 30 September: six months)."""
import os
from datetime import date

import pandas as pd

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.review.last_year_common import last_year_end


def _tb(heading):
    return pd.DataFrame([[None, "EXAMPLE CLIENT LTD", None, None], [None, "Trial Balance", None, None],
                         [None, heading, None, None], [None, None, None, None],
                         ["Code", "Account Name", "Debit", "Credit"], [None, "1007 Business Bank Account", 10000.0, None]])


def test_six_month_period():
    assert last_year_end(_tb("As of 31 Mar, 2026"), date(2026, 9, 30)) == date(2026, 3, 31)


def test_twelve_month_period():
    assert last_year_end(_tb("As of 30 Sep, 2025"), date(2026, 9, 30)) == date(2025, 9, 30)


def test_no_date_or_not_an_earlier_end():
    assert last_year_end(_tb("Trial Balance"), date(2026, 9, 30)) is None
    assert last_year_end(_tb("As of 30 Sep, 2026"), date(2026, 9, 30)) is None          # this year's own date
    assert last_year_end(_tb("As of 30 Sep, 2024"), date(2026, 9, 30)) is None          # two years back
