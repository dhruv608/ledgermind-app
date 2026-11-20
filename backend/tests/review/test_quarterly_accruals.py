"""Quarterly bills in arrears: the months since the last bill are owed at the year end; anonymous
figures; no database."""

from datetime import date

from backend.app.services.sop.accruals import quarterly_in_arrears
from backend.app.services.sop.common import GLLine


def bill(d, amount, desc="Example Telecom Ltd - quarterly bill", code=3290, account="Telephone"):
    return GLLine(date.fromisoformat(d), code, account, amount, 0.0, desc, "")


def test_months_since_the_last_quarterly_bill():
    lines = [bill("2025-01-02", 1100), bill("2025-04-01", 1100), bill("2025-07-01", 1100), bill("2025-10-28", 1106)]
    [q] = quarterly_in_arrears(date(2025, 12, 31), lines)
    assert q.months_since == 2 and q.estimate == round((4406 / 4) * 2 / 3, 2)


def test_monthly_stopped_and_not_cost_accounts_are_not_quarterly():
    monthly = [bill(f"2025-{m:02d}-05", 50) for m in range(1, 13)]
    assert quarterly_in_arrears(date(2025, 12, 31), monthly) == []
    stopped = [bill("2025-01-10", 300), bill("2025-04-10", 300), bill("2025-07-10", 300)]   # nothing for 5 months
    assert quarterly_in_arrears(date(2025, 12, 31), stopped) == []
    vat = [bill(d, 200, code=5300, account="VAT Control") for d in ("2025-03-01", "2025-06-01", "2025-09-01")]
    assert quarterly_in_arrears(date(2025, 12, 31), vat, lambda c: c != 5300) == []
