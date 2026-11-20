"""Year-on-year questions: a change over the firm's limit becomes a client question; £1,000 unless set."""
import json
from types import SimpleNamespace as NS

from backend.app.services.review.last_year_compare import CHANGE_AMOUNT, firm_change_limit, is_big_change


class _DB:
    def __init__(self, value):
        self.value = value

    def get(self, model, key):
        return None if self.value is None else NS(value=json.dumps({"amount": self.value}))


def test_default_and_firm_limit():
    assert firm_change_limit(None) == CHANGE_AMOUNT == 1000.0
    assert firm_change_limit(_DB(None)) == 1000.0
    assert firm_change_limit(_DB(2500)) == 2500.0


def test_limit_decides_the_question():
    assert is_big_change(3000.0, 1500.0)                       # +1,500 and 100%: asked at £1,000
    assert not is_big_change(3000.0, 1500.0, amount=2500.0)    # under the firm's £2,500
