"""Payroll liabilities by month with a due date and a status."""

from datetime import date

from backend.app.services.papers.payroll_months import (DUE_LATER, NOT_PAID, PAID_LATE, PAID_ON_TIME, PART_PAID,
                                                 dated_payments, due_date, month_status, pays_quarterly, year_months)

YE = date(2026, 3, 31)
MONTHS = year_months(YE)            # Apr 2025 .. Mar 2026


def _owed(amount=500.0, only=None):
    return {mo: [amount if only is None or mo in only else 0.0, 0.0] for mo in MONTHS}


def test_due_dates():
    assert due_date((2025, 4), "paye") == date(2025, 5, 22)
    assert due_date((2025, 12), "pension") == date(2026, 1, 22)
    assert due_date((2025, 4), "net") == date(2025, 5, 7)
    assert due_date((2025, 4), "paye", quarterly=True) == date(2025, 7, 22)
    assert due_date((2026, 3), "paye", quarterly=True) == date(2026, 4, 22)


def test_monthly_statuses():
    pays = [(date(2025, 5, 20), 500.0),          # April on time
            (date(2025, 7, 1), 500.0),           # May late
            (date(2025, 7, 20), 200.0)]          # June part paid
    out = month_status(MONTHS, _owed(), 0.0, pays, "paye", YE)
    assert out[(2025, 4)][1] == PAID_ON_TIME
    assert out[(2025, 5)][1] == PAID_LATE
    assert out[(2025, 6)][1] == PART_PAID
    assert out[(2025, 7)][1] == NOT_PAID
    assert out[(2026, 3)] == (date(2026, 4, 22), DUE_LATER)


def test_brought_forward_cleared_first():
    pays = [(date(2025, 4, 20), 300.0), (date(2025, 5, 20), 500.0)]
    out = month_status(MONTHS, _owed(only={(2025, 4)}), 300.0, pays, "paye", YE)
    assert out == {(2025, 4): (date(2025, 5, 22), PAID_ON_TIME)}


def test_quarterly_payer():
    pays = [(date(2025, 7, 18), 1500.0), (date(2025, 10, 20), 1500.0), (date(2026, 1, 21), 1500.0)]
    assert pays_quarterly(pays, 12)
    out = month_status(MONTHS, _owed(), 0.0, pays, "paye", YE)
    assert out[(2025, 4)][1] == PAID_ON_TIME and out[(2025, 4)][0] == date(2025, 7, 22)
    assert out[(2025, 12)][1] == PAID_ON_TIME
    assert out[(2026, 1)] == (date(2026, 4, 22), DUE_LATER)


def test_dated_payments_reads_debits():
    rows = [("20/05/2025", "5320", "", "PAYE", "", "HMRC", "", 500.0, 0.0),
            ("30/04/2025", "5320", "", "PAYE", "", "Payroll", "", 0.0, 500.0),
            ("bad", "5320", "", "PAYE", "", "HMRC", "", 1.0, 0.0)]
    assert dated_payments(rows, lambda tx: tx[1] == "5320") == [(date(2025, 5, 20), 500.0)]


def test_skipped_month_stays_unpaid_when_payments_match_by_amount():
    """April skipped, May and June paid on their due dates: April is the unpaid month (oldest-first would
    have marked June unpaid instead)."""
    owed = _owed(only={(2025, 4), (2025, 5), (2025, 6)})
    pays = [(date(2025, 6, 22), 500.0), (date(2025, 7, 22), 500.0)]
    out = month_status(MONTHS, owed, 0.0, pays, "paye", YE)
    assert out[(2025, 4)][1] == "Not paid"
    assert out[(2025, 5)][1] == "Paid on time" and out[(2025, 6)][1] == "Paid on time"
