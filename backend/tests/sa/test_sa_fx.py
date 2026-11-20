"""Foreign amounts in pounds at HMRC's average rate for the year to 31 March (BIM39505; made-up amounts)."""

from backend.app.sa import fx
from backend.app.sa.extract import letting


def test_hmrc_average_rates():
    assert fx.rate("NZD", "2024-25") == 2.1385            # the rate the firm's own 2024-25 working paper used
    assert fx.rate("nzd", "2025-26") == 2.2772 and fx.rate("GBP", "2025-26") == 1.0
    assert fx.rate("XYZ", "2025-26") is None and fx.rate("NZD", "2019-20") is None
    assert fx.to_gbp(2277.2, "NZD", "2025-26")["gbp"] == 1000.0


def test_an_overseas_let_says_its_rate():
    f = letting.clean({"is_rent_statement": True, "agent": "An Agent", "currency": "NZD", "properties": [{"address": "1 Test St",
        "country": "NZL", "lines": [{"date": "2026-03-31", "description": "Rent", "heading": "RENT", "amount": 27040}]}]})
    status, notes = letting.checks(f, "2025-26", "Pat Test")
    assert status == "CHECK" and any("2.2772 NZD to £1" in n for n in notes)


def test_the_treaty_sets_the_credit():
    # Made-up amounts: NZ took 20% of interest but the treaty allows 10%; US interest is the UK's alone (reclaim it)
    from types import SimpleNamespace as N
    from backend.app.sa import foreign
    nz = N(id=1, country="NZL", kind="INTEREST", payer="A NZ bank", amount=1000, foreign_tax=200, share=1, claim=True,
           doc_id=None, note=None)
    assert foreign.one(nz)["creditable"] == 100.0
    us = N(id=2, country="USA", kind="INTEREST", payer="A US bank", amount=1000, foreign_tax=150, share=1, claim=True,
           doc_id=None, note=None)
    r = foreign.one(us)
    assert r["creditable"] == 0.0 and any("reclaim" in i["text"] for i in r["issues"])
    assert "Art 19" in foreign.one(N(**{**vars(nz), "kind": "PENSION", "id": 3}))["treaty"]
