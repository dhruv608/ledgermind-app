"""A dividend to clear an overdrawn director's loan goes to every shareholder by shareholding: the
directors' part of the shares from the client setup. Made-up people."""
import json
from types import SimpleNamespace as N

from backend.app.services.review.dividends import directors_share


def eng(directors, details, shareholders):
    setup = {"people": {"director_details": details, "shareholders": shareholders}}
    return N(profile=N(setup=json.dumps(setup), directors=json.dumps(directors)))


def test_director_with_half_the_shares():
    e = eng(["A Director"], {"A Director": {"shares": 50}}, [{"name": "B Spouse", "shares": 50}])
    assert directors_share(e) == 0.5


def test_directors_hold_everything_or_not_known():
    assert directors_share(eng(["A Director"], {"A Director": {"shares": 100}}, [])) is None
    assert directors_share(eng(["A Director"], {}, [{"name": "B Spouse", "shares": 50}])) is None
    # shares that do not add to 100% are not trusted
    assert directors_share(eng(["A Director"], {"A Director": {"shares": 60}}, [{"name": "B", "shares": 30}])) is None


def test_a_director_also_listed_as_shareholder_is_not_counted_twice():
    e = eng(["A Director"], {"A Director": {"shares": 75}},
            [{"name": "A Director", "shares": 75}, {"name": "C Investor", "shares": 25}])
    assert directors_share(e) == 0.75
