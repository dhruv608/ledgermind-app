"""The highest overdrawn balance in date order, and repayments of £5,000+ drawn again within 30 days."""

from datetime import date

from backend.app.services.workbook.dla_tests import bed_and_breakfast, dla_lines, highest_overdrawn


def _tx(when, debit=0.0, credit=0.0, code="5400"):
    return (when, code, "Expense", "Director", "Bank", "line", "", debit, credit)


def test_lines_in_date_order_and_highest():
    rows = [_tx("20/03/2025", debit=9000), _tx("05/01/2025", debit=4000), _tx("10/02/2025", credit=3000),
            _tx("01/01/2025", debit=99, code="5300")]
    lines = dla_lines(rows)
    assert [l[0] for l in lines] == [date(2025, 1, 5), date(2025, 2, 10), date(2025, 3, 20)]
    # from an opening of 1,000 overdrawn: 5,000, 2,000, then 11,000 on 20 March
    assert highest_overdrawn(1000.0, lines) == (11000.0, date(2025, 3, 20))


def test_owed_to_the_director_is_not_overdrawn():
    assert highest_overdrawn(-5000.0, dla_lines([_tx("05/01/2025", debit=1000)])) == (0.0, None)


def test_repaid_and_drawn_again_within_30_days():
    lines = dla_lines([_tx("31/03/2025", credit=6000), _tx("10/04/2025", debit=3000), _tx("20/04/2025", debit=2500),
                       _tx("01/06/2025", credit=5000), _tx("15/08/2025", debit=6000)])
    assert bed_and_breakfast(lines) == [(date(2025, 3, 31), 6000.0, 5500.0)]
