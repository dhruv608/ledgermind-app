"""Payroll owed at the year end, paid after it, shown from next year's ledger."""
import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.papers.payroll_months import DUE_LATER, NOT_PAID, PAID_ON_TIME, month_status

END = date(2025, 3, 31)
MONTHS = [(2025, 1), (2025, 2), (2025, 3)]
PER = {mo: (1000.0, None) for mo in MONTHS}
PAID = [(date(2025, 2, 20), 1000.0), (date(2025, 3, 20), 1000.0)]


def test_march_paye_paid_in_april():
    st = month_status(MONTHS, PER, 0.0, PAID, "paye", END, later=[(date(2025, 4, 18), 1000.0)])
    assert st[(2025, 1)][1] == PAID_ON_TIME
    assert st[(2025, 3)] == (date(2025, 4, 22), f"{DUE_LATER}: paid 18/04/2025 (next year's ledger)")


def test_without_next_year_still_due_later():
    assert month_status(MONTHS, PER, 0.0, PAID, "paye", END)[(2025, 3)][1] == DUE_LATER


def test_next_years_own_month_not_taken():
    # A payment in late May pays April's PAYE, not March's
    st = month_status(MONTHS, PER, 0.0, PAID, "paye", END, later=[(date(2025, 5, 20), 1000.0)])
    assert st[(2025, 3)][1] == DUE_LATER


def test_overdue_month_paid_late_after_year_end():
    per = {**PER, (2025, 1): (1000.0, None)}
    st = month_status(MONTHS, per, 0.0, [(date(2025, 3, 20), 1000.0)], "paye", END,
                      later=[(date(2025, 4, 10), 1000.0), (date(2025, 4, 21), 1000.0)])
    # 20 March pays February; January, unpaid at the year end, is paid late in April; March is paid in April
    assert st[(2025, 2)][1] == PAID_ON_TIME
    assert st[(2025, 1)][1] == f"{NOT_PAID}: paid 21/04/2025 (next year's ledger, late)"
    assert st[(2025, 3)][1] == f"{DUE_LATER}: paid 10/04/2025 (next year's ledger)"
