"""Last year's stock is reversed into cost of sales only with this year's count: reversed alone it would leave no
closing stock and the whole stock would fall into cost of sales. Without the count the stock is left as it
is and the count is asked."""
import json
from types import SimpleNamespace as NS

from backend.app.services.review.yearend_journals import stock_journals


class _Chart:
    def name(self, code):
        return f"code {code}"


def _run(closing_stock):
    setup = {"policies": {"closing_stock": closing_stock}} if closing_stock is not None else {}
    profile = NS(setup=json.dumps(setup))
    tb = [NS(std_code=4300, opening_amount=158635.0, net_amount=158635.0, raw_account_name="Stock")]
    return stock_journals(NS(id="e1"), profile, tb, _Chart(), [1], {4300: 158635.0}, db=None)


def test_no_count_no_reversal_and_a_question():
    findings, journals = _run(None)
    assert journals == []
    assert [f.procedure_ref for f in findings] == ["U-STK-003"]


def test_count_entered_reverses_and_books_it():
    findings, journals = _run(160000)
    refs = sorted(f.procedure_ref for f in findings)
    assert refs == ["U-STK-001", "U-STK-002"]
    amounts = sorted(round(j.amount, 2) for j in journals)
    assert amounts == [158635.0, 160000.0]
