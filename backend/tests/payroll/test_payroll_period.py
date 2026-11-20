"""A payroll report for another period is not read as this year's (payroll_period.py): a stale
January - December 2024 report against an April 2024 - March 2025 year."""
from datetime import date
from types import SimpleNamespace as N

from backend.app.services.review.payroll_period import off_period


def eng(end):
    return N(period_end_date=end)


def rows(*months):
    return [N(period_end=date(y, m, 1), period_start=None) for y, m in months]


def year(y1, m1, n):
    out, y, m = [], y1, m1
    for _ in range(n):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_template_calendar_year_against_april_year_is_off():
    why = off_period(eng(date(2025, 3, 31)), rows(*year(2024, 1, 12)))
    assert why and "Jan 2024 to Dec 2024" in why and "Apr 2024 to Mar 2025" in why


def test_report_for_the_year_is_used():
    assert off_period(eng(date(2025, 3, 31)), rows(*year(2024, 4, 12))) is None


def test_a_month_of_pay_date_lag_is_not_off():
    # pay periods dated the 5th of the next month: May 2024 to April 2025
    assert off_period(eng(date(2025, 3, 31)), rows(*year(2024, 5, 12))) is None


def test_whole_year_and_more_is_used():
    assert off_period(eng(date(2025, 3, 31)), rows(*year(2024, 1, 18))) is None


def test_another_year_entirely_is_off():
    assert off_period(eng(date(2026, 3, 31)), rows(*year(2024, 1, 12)))


def test_part_of_the_year_inside_is_not_off():
    # a payroll started in the year (October to March): nothing outside the year
    assert off_period(eng(date(2025, 3, 31)), rows(*year(2024, 10, 6))) is None


def test_no_dates_cannot_tell():
    assert off_period(eng(date(2025, 3, 31)), [N(period_end=None, period_start=None)]) is None
