"""Last year's TB added on the Data check next to a closing TB: kept (not an error) when it balances."""
import os

import pandas as pd

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.review.last_year_openings import _balances


def _tb(rows):
    head = [[None, "EXAMPLE CLIENT LTD", None, None], [None, "Trial Balance", None, None],
            [None, "As of 31 Mar, 2026", None, None], [None, None, None, None], ["Code", "Account Name", "Debit", "Credit"]]
    return pd.DataFrame(head + rows + [[None, "TOTAL", None, None]])


def test_balanced_tb():
    assert _balances(_tb([[None, "1007 Business Bank Account", 10000.0, None], [None, "4000 Sales", None, 9000.0],
                          [None, "Share capital", None, 1000.0]]))


def test_unbalanced_tb():
    assert not _balances(_tb([[None, "1007 Business Bank Account", 10000.0, None], [None, "4000 Sales", None, 7000.0]]))
