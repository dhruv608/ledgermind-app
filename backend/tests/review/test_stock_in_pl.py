"""Opening and closing stock shown in the P&L when the stock account moved during the year
('Opening reversed, closing posted'): profit and the balance sheet unchanged, the difference to cost of sales. The
figures are from two clients (made anonymous): a contractor's work in progress and a retailer's goods."""
from types import SimpleNamespace as N

from backend.app.services.review import yearend_journals as yj


class Chart:
    def name(self, code, default=""):
        return str(code)


def _run(opening, in_books, after=None, reversed_now=None):
    findings, journals, got = [], [], {}

    def fake_lines(engagement, counter, description, lines, chart, point):
        got["lines"] = lines
        return description
    import backend.app.services.review.payroll_journals as pj
    real, pj._journal_lines = pj._journal_lines, fake_lines
    try:
        yj.stock_in_pl(N(id="e"), [], Chart(), [0], after or {}, opening, in_books, reversed_now or {}, None,
                       findings, journals)
    finally:
        pj._journal_lines = real
    return findings, got.get("lines")


def _net(lines):
    return round(sum(dr - cr for _c, dr, cr in lines), 2)


def test_work_in_progress_run_through_purchases():
    findings, lines = _run({4302: 16900.0, 4303: 115585.87}, {4302: 0.0, 4303: 118688.12})
    assert findings[0].procedure_ref == "U-STK-004"
    assert sorted(lines) == sorted([(1030, 16900.0, 0.0), (1020, 115585.87, 0.0), (1920, 0.0, 118688.12),
                                    (1100, 0.0, 13797.75)])
    assert _net(lines) == 0                                     # profit unchanged


def test_goods_that_grew_in_the_year():
    _f, lines = _run({4302: 261649.58}, {4302: 408418.84})
    assert sorted(lines) == sorted([(1030, 261649.58, 0.0), (1930, 0.0, 408418.84), (1100, 146769.26, 0.0)])


def test_nothing_when_the_books_already_show_stock_in_the_pl_or_it_did_not_move():
    assert _run({4302: 1000.0}, {4302: 1500.0}, after={1010: 1000.0})[1] is None
    assert _run({4302: 1000.0}, {4302: 1500.0}, reversed_now={4302: 1000.0})[1] is None
    assert _run({4302: 1000.0}, {4302: 1000.0})[1] is None     # unchanged: the opening reversal's case
    assert _run({}, {})[1] is None
