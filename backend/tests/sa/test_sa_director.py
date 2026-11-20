"""Director's loan account checks (made-up moves): a loan over £10,000 at any time gives a
beneficial loan point at the official rate, an overdrawn year end gives s455 (R-DIR-03; ITEPA s175, EIM26215)."""

from datetime import date

from backend.app.sa.director import balances, loan_points


def test_an_overdrawn_loan_over_10000():
    moves = [(date(2025, 6, 1), 9000.0), (date(2025, 11, 1), 4284.0), (date(2026, 3, 1), -1000.0)]
    pts = loan_points(4000.0, moves, date(2025, 4, 6), date(2026, 4, 5), 0.0375, date(2025, 12, 31))
    assert "up to £17,284.00" in pts[0] and "about £380.32" in pts[0]       # (4,000 + 16,284) / 2 x 3.75%
    assert "s455" in pts[1] and "£17,284.00" in pts[1]


def test_under_the_limit_and_in_credit():
    assert loan_points(2000.0, [(date(2025, 7, 1), 3000.0)], date(2025, 4, 6), date(2026, 4, 5), 0.0375, None) == []
    path = balances(-500.0, [(date(2025, 5, 1), 200.0)])
    assert path == [(date(2025, 5, 1), -300.0)]
    assert loan_points(-500.0, [], date(2025, 4, 6), date(2026, 4, 5), 0.0375, date(2025, 12, 31)) == []
