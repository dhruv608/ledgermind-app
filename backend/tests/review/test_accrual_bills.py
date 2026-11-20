"""Last year's accrual set against the first bill this year on the same account that shares a word with it."""

from datetime import date

from backend.app.services.workbook.accrual_bills import accrued_for, first_bill

START = date(2025, 4, 1)


def _tx(when, code, account, desc, debit=0.0, credit=0.0, source="Bill"):
    return (when, code, "Expense", account, source, desc, "", debit, credit)


def test_what_it_was_for():
    assert accrued_for("Reverse last year's accrual: Rent - Quarter of Jun-2024 (last year's final WP)") == \
        "Rent - Quarter of Jun-2024"


def test_first_matching_bill_in_the_window():
    rows = [_tx("10/04/2025", "3100", "Rent", "Crown Estate - Rent payment", debit=6000),
            _tx("05/04/2025", "3100", "Rent", "Reverse accrual", credit=6000, source="Journal"),
            _tx("01/09/2025", "3100", "Rent", "Crown Estate - Rent", debit=6000),
            _tx("02/04/2025", "3290", "Phone", "BT Rent of line", debit=40)]
    # 'Rent' is the account's own name, so the amount accrued is what finds the bill
    assert first_bill(rows, "3100", "Reverse last year's accrual: Rent - Quarter of Jun-2024", START, 6000) == \
        (date(2025, 4, 10), 6000.0, "Crown Estate - Rent payment")


def test_no_shared_word_or_outside_window_is_none():
    rows = [_tx("10/04/2025", "3631", "Interest", "Bank charge", debit=10),
            _tx("20/09/2025", "3631", "Interest", "Techstars interest", debit=500)]
    assert first_bill(rows, "3631", "Reverse last year's accrual: Interest on Techstars Loan", START) is None


def test_same_amount_counts_without_a_shared_word():
    rows = [_tx("11/09/2025", "3100", "Rent", "@SIPP", debit=1666.67)]
    assert first_bill(rows, "3100", "Reverse last year's accrual: Rent", date(2025, 9, 1), 1666.67) ==         (date(2025, 9, 11), 1666.67, "@SIPP")
    assert first_bill(rows, "3100", "Reverse last year's accrual: Rent", date(2025, 9, 1), 900.0) is None
