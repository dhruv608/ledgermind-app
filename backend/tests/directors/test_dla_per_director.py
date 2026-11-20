"""U-DLA-010: a director overdrawn while another is owed, hidden by the net balance (SI 2008/409 Sch 1 para 8; CTA 2010
s455 per participator). Figures from a client's 2026 review, made anonymous."""
from datetime import date
from types import SimpleNamespace as N

from backend.app.services.review.dla_per_director import overdrawn_hidden

A = lambda name, net: N(raw_account_name=name, std_code=5400, net_amount=net, opening_amount=None)


def _eng(directors='["Paul Cook", "Matthew Mountford-Platts"]'):
    return N(id="e", period_end_date=date(2026, 9, 30), profile=N(directors=directors))


def test_overdrawn_director_hidden_by_another_directors_credit():
    tb = [A("Directors Loan Account - Paul Cook", -234649.24), A("DLA - Matthew Mountford-Platts", 62418.80)]
    point = overdrawn_hidden(_eng(), tb)
    assert point[0].procedure_ref == "U-DLA-010" and point[0].severity == "HIGH"
    assert point[0].quantified_amount == 62418.80
    assert "30/06/2027" in point[0].finding_details and "Matthew Mountford-Platts £62,418.80" in point[0].finding_details


def test_nothing_when_all_owed_or_the_net_already_shows_it():
    assert overdrawn_hidden(_eng(), [A("DLA - Paul Cook", -5000.0), A("DLA - Matthew Mountford-Platts", -200.0)]) == []
    # Both overdrawn: the net shows it all, and the usual s455 point (U-DLA-001) covers it
    assert overdrawn_hidden(_eng(), [A("DLA - Paul Cook", 5000.0), A("DLA - Matthew Mountford-Platts", 2000.0)]) == []
    # One director's account only: nothing to set off
    assert overdrawn_hidden(_eng('["Paul Cook"]'), [A("Directors loan account", 5000.0)]) == []
