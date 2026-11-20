"""Box 6 for the accounting year (shared by V-F02 and the Sales reconciliation)."""

from datetime import date

from backend.app.services.tax.vat_review import box6_in_year


def test_box6_by_days_in_the_year():
    returns = [(date(2025, 1, 1), date(2025, 3, 31), 9000.0),     # 31 of 90 days in the year (from 1 Mar)
               (date(2025, 4, 1), date(2025, 6, 30), 6000.0)]
    box6, covered = box6_in_year(returns, date(2025, 3, 1), date(2026, 2, 28))
    assert round(box6, 2) == round(9000 * 31 / 90 + 6000, 2)
    assert covered == 31 + 91
