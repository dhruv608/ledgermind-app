"""The reserves movement from a year's final balances."""

from types import SimpleNamespace as N

from backend.app.services.papers.capital import _movement


def test_reserves_movement():
    sections = {8000: "Profit and loss account", 8010: "Profit and loss account"}
    chart = N(section=lambda c: sections.get(c), is_pl=lambda c: 3000 <= c < 4000)
    bal = {8000: -100.0, 8010: 30.0, 3000: -500.0, 3100: 200.0, 3800: 60.0}
    m = _movement(bal, chart)
    assert m == {"bf": 100.0, "profit": 240.0, "dividends": 30.0, "cf": 310.0}
