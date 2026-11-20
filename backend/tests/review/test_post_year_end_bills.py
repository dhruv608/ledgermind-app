"""U-ACC-010: accruals from next year's ledger, from £500 (small bills are not accrued)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.review.post_year_end_bills import MIN_ACCRUAL, _accrued_codes
from types import SimpleNamespace as N


def test_floor_and_already_accrued_codes():
    assert MIN_ACCRUAL == 500.0
    j = N(lines=[], debit_code=3100, credit_code=5360, amount=6000.0)
    k = N(lines=[N(account_code=3301, debit=1200.0, credit=0.0), N(account_code=5360, debit=0.0, credit=1200.0)])
    assert _accrued_codes([j, k]) == {3100, 3301}
