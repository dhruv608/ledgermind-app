"""Power bills stating their periods, the latest ending before the year end: the days to the year end are owed (a
2026 client: monthly bills in arrears, February's posted 2 March, March not billed by 31 March)."""
from datetime import date

from backend.app.services.sop.accruals import billed_to_before_year_end
from backend.app.services.sop.common import GLLine


def _bill(posted, text, amount, account="Expenses:Light and heat", code=3130, source="Bill"):
    return GLLine(posted, code, account, amount, 0.0, text, source, "", "")


def test_last_month_not_billed_is_owed():
    lines = [_bill(date(2025, 11, 6), "Pozitive Energy - E 01.10.25-31.10.25", 1507.95),
             _bill(date(2025, 12, 8), "Pozitive Energy - E 01.11.25-30.11.25", 1732.85),
             _bill(date(2026, 1, 2), "Pozitive Energy - E 01.12.25-31.12.25", 1767.45),
             _bill(date(2026, 2, 3), "Pozitive Energy - E 01.01.26-31.01.26", 1783.16),
             _bill(date(2026, 3, 2), "Pozitive Energy - From 1/02/2026 - 28/02/2026", 1666.35)]
    [f] = billed_to_before_year_end(date(2026, 3, 31), lines)
    assert f.covered_to == date(2026, 2, 28) and f.days == 31 and f.code == 3130
    assert 1650 < f.estimate < 1800


def test_billed_to_the_year_end_owes_nothing():
    lines = [_bill(date(2026, 1, 5), "E 01.12.25-31.12.25", 100.0), _bill(date(2026, 2, 5), "E 01.01.26-31.01.26", 100.0),
             _bill(date(2026, 3, 5), "E 01.02.26-28.02.26", 100.0), _bill(date(2026, 3, 31), "E 01.03.26-31.03.26", 100.0)]
    assert billed_to_before_year_end(date(2026, 3, 31), lines) == []


def test_needs_three_stated_bills_and_not_journals():
    lines = [_bill(date(2026, 1, 5), "E 01.12.25-31.12.25", 100.0), _bill(date(2026, 2, 5), "E 01.01.26-31.01.26", 100.0),
             _bill(date(2026, 3, 5), "E 01.02.26-28.02.26", 100.0, source="Journal")]
    assert billed_to_before_year_end(date(2026, 3, 31), lines) == []


def test_not_rent_or_other_costs():
    lines = [_bill(date(2026, m, 1), f"Rent 01.{m - 1:02d}.26-28.{m - 1:02d}.26", 900.0, "Expenses:Rent", 3100)
             for m in (2, 3, 4)]
    assert billed_to_before_year_end(date(2026, 5, 31), lines) == []
