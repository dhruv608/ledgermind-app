"""U-DIV-001 reserves: proposed journals on reserves b/f and on dividends count, as their P&L effect does, so an
opening adjustment on 8000 is counted and the dividend proposed is never more than the reserves."""
from types import SimpleNamespace as NS

from backend.app.services.review.dividends import _code_effect


def _j(dr, cr, amount, lines=()):
    return NS(debit_code=dr, credit_code=cr, amount=amount, lines=list(lines))


def test_opening_adjustment_on_reserves_counts():
    journals = [_j(8000, 5310, 3472.06), _j(3400, 4124, 500.0)]
    assert _code_effect(journals, [8000]) == 3472.06


def test_proposed_dividends_and_lines_count():
    lines = [NS(account_code=8011, debit=1000.0, credit=0), NS(account_code=5400, debit=0, credit=1000.0)]
    journals = [_j(8011, 5400, 2000.0), _j(0, 0, 0, lines)]
    assert _code_effect(journals, [8010, 8011]) == 3000.0
