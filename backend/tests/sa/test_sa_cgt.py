"""Capital gains (SA108), made-up figures; no database."""

from datetime import date
from types import SimpleNamespace as N

from backend.app.sa import cgt

TODAY = date(2026, 11, 3)


def disp(id=1, **kw):
    base = dict(id=id, kind="LISTED", name=f"Asset {id}", acquired="2015-04-06", contract_date="2025-10-06",
                completion_date="2025-10-06", proceeds=0, cost=0, costs=0, improvements=0, share=1, uk=1,
                main_home_months=None, badr=0, negligible=0, rtt_date=None, rtt_gain=None, rtt_tax=None, doc_id=None)
    return N(**{**base, **kw})


def rows(*ds, year="2025-26"):
    return [cgt.one(d, year, TODAY) for d in ds]


def test_annual_exempt_amount_and_bands():
    s = cgt.compute(rows(disp(proceeds=30000, cost=9500, costs=500)), 0, "2025-26", 30000, 37700)
    assert (s["gains"], s["exempt_used"], s["chargeable"]) == (20000, 3000, 17000)
    assert [(l["amount"], l["rate"]) for l in s["lines"]] == [(7700, 0.18), (9300, 0.24)] and s["tax"] == 3618


def test_losses_this_year_in_full_brought_forward_down_to_exempt():
    s = cgt.compute(rows(disp(1, proceeds=12000, cost=2000), disp(2, proceeds=1000, cost=3000)), 10000, "2025-26", 30000, 37700)
    assert (s["net"], s["losses_bf_used"], s["exempt_used"], s["tax"], s["loss_cf"]) == (8000, 5000, 3000, 0, 5000)


def test_badr_uses_the_band_first_and_exempt_goes_to_other_gains():
    s = cgt.compute(rows(disp(1, kind="UNLISTED", proceeds=60000, cost=10000, badr=1), disp(2, proceeds=25000, cost=5000)),
                    0, "2025-26", 30000, 37700)
    assert [(l["band"], l["amount"], l["rate"]) for l in s["lines"]] == [("BADR", 50000, 0.14), ("higher", 17000, 0.24)]
    assert s["tax"] == 11080 and s["badr_gains"] == 50000


def test_2024_25_rates_by_date_and_best_order():
    got = rows(disp(1, proceeds=12000, cost=2000, contract_date="2024-06-01"),
               disp(2, kind="RESIDENTIAL", uk=0, proceeds=12000, cost=2000, contract_date="2024-06-01"), year="2024-25")
    s = cgt.compute(got, 0, "2024-25", 30000, 37700)
    # exempt amount to the home (24%); the band to the shares (10% instead of 20%)
    assert [(l["name"], l["band"], l["amount"], l["rate"]) for l in s["lines"]] == [
        ("Asset 1", "basic", 7700, 0.1), ("Asset 1", "higher", 2300, 0.2), ("Asset 2", "higher", 7000, 0.24)]
    assert s["tax"] == 2910
    late = cgt.one(disp(3, proceeds=12000, cost=2000, contract_date="2024-11-01"), "2024-25", TODAY)
    assert late["rates"]["other"] == [0.18, 0.24]


def test_main_home_relief_and_60_day_return():
    home = cgt.one(disp(kind="RESIDENTIAL", acquired="2015-10-06", contract_date="2025-10-06", completion_date="2025-10-20",
                        proceeds=400000, cost=280000, main_home_months=51), "2025-26", TODAY)
    assert home["relief"] == 60000 and home["gain"] == 60000                       # 60 of 120 months
    assert [(i["key"], i["block"]) for i in home["issues"]] == [("rtt:1", True)]    # due 19/12/2025, not sent
    sent = cgt.one(disp(kind="RESIDENTIAL", completion_date="2025-10-20", rtt_date="2025-11-01", rtt_gain=100000, rtt_tax=20000,
                        proceeds=400000, cost=280000), "2025-26", TODAY)
    assert sent["issues"] == []
    sec = cgt.sections([home, sent])[0]
    assert {r["box"]: r["value"] for r in sec["rows"]}["10"] == 20000 and {r["box"]: r["value"] for r in sec["rows"]}["8"] == "PRR"


def test_dates_costs_and_negligible_value():
    early = cgt.one(disp(contract_date="2025-03-30", proceeds=5000, cost=1000), "2025-26", TODAY)
    assert not early["in_year"] and early["issues"][0]["key"] == "year:1"
    no_cost = cgt.one(disp(proceeds=5000), "2025-26", TODAY)
    assert [i["key"] for i in no_cost["issues"]] == ["cost:1"]
    worthless = cgt.one(disp(kind="UNLISTED", cost=4000, negligible=1), "2025-26", TODAY)
    assert worthless["gain"] == -4000 and [i["key"] for i in worthless["issues"]] == ["income_loss:1"]
    sec = cgt.sections(rows(disp(1, proceeds=5000, cost=1000), disp(2, kind="CRYPTO", proceeds=800, cost=1000)))
    assert [(s["kind"], [r["box"] for r in s["rows"]]) for s in sec] == [
        ("CRYPTO", ["13.1", "13.2", "13.3", "13.4", "13.5"]), ("LISTED", ["23", "24", "25", "26", "27"])]


def test_60_day_point_only_with_tax_and_cost_and_gift_points():
    """G12/RP9 the 60-day return only when tax is due; G02 no cost asked, but not for a share sale the
    matching costed; G04/G2 nothing received asks whether it was a gift (market value)."""
    small = cgt.one(disp(kind="RESIDENTIAL", proceeds=102000, cost=100000), "2025-26", TODAY)    # a £2,000 gain
    assert [i["key"] for i in small["issues"]] == ["rtt:1"]
    summary = cgt.compute([small], 0, "2025-26", 30000, 37700)
    cgt.no_return_when_no_tax([small], summary)
    assert summary["tax"] == 0 and small["issues"] == [] and "no 60-day" in small["notes"][-1]
    big = cgt.one(disp(kind="RESIDENTIAL", proceeds=150000, cost=100000), "2025-26", TODAY)
    cgt.no_return_when_no_tax([big], cgt.compute([big], 0, "2025-26", 30000, 37700))
    assert [i["key"] for i in big["issues"]] == ["rtt:1"]
    matched = cgt.one(N(**{**vars(disp(proceeds=500)), "matched": True}), "2025-26", TODAY)
    assert matched["issues"] == []
    gift = cgt.one(disp(cost=20000), "2025-26", TODAY)
    assert [i["key"] for i in gift["issues"]] == ["gift:1"] and "market value" in gift["issues"][0]["text"]


def test_non_resident_reports_every_uk_home_sale_within_60_days():
    """HS307: a person not resident in the UK sends the 60-day return even with no tax to pay, or a loss."""
    small = cgt.one(disp(kind="RESIDENTIAL", proceeds=102000, cost=100000), "2025-26", TODAY, non_resident=True)
    cgt.no_return_when_no_tax([small], cgt.compute([small], 0, "2025-26", 30000, 37700), non_resident=True)
    assert [i["key"] for i in small["issues"]] == ["rtt:1"]
    loss = cgt.one(disp(kind="RESIDENTIAL", proceeds=90000, cost=100000), "2025-26", TODAY, non_resident=True)
    assert [i["key"] for i in loss["issues"]] == ["rtt:1"]
    assert cgt.one(disp(kind="RESIDENTIAL", proceeds=90000, cost=100000), "2025-26", TODAY)["issues"] == []


def test_2026_27_rates_held():
    from backend.app.sa.engine.calc import rates_for
    r = rates_for("2026-27")
    assert r["dividend_rates"] == {"basic": 0.1075, "higher": 0.3575, "additional": 0.3935}
    assert r["cgt"]["periods"][0]["badr"] == 0.18 and r["mileage"]["car_first"] == 0.55
    assert r["student_loan"]["PLAN_5"] == 25000 and r["investment"]["VCT"] == [0.2, 200000]
    from backend.app.sa.foster import care_amounts
    assert care_amounts("2026-27") == (rates_for("2025-26")["qualifying_care"], "2025-26")
    assert care_amounts("2025-26")[1] == "2025-26"
