"""A first period over 12 months files by the later of 21 months from incorporation and 3
months after the year end (CA 2006 s442(3)); the 100% allowance for zero-emission cars ends 31 March 2027 (CA23153)."""
import json
from datetime import date
from types import SimpleNamespace as N

from backend.app.api.endpoints.engagements import accounts_due
from backend.app.services.tax.ct_computation import compute

PL, BS = "Profit and Loss", "Balance Sheet"


def _eng(formed, period_end, prior=None):
    profile = N(companies_house=json.dumps({"incorporated": formed}) if formed else None)
    return N(period_end_date=period_end, prior_period_end_date=prior, profile=profile)


def test_ordinary_year_is_nine_months():
    assert accounts_due(_eng(None, date(2025, 3, 31), date(2024, 3, 31))) == date(2025, 12, 31)


def test_first_period_of_twelve_months_or_less_is_nine_months_after_year_end():
    assert accounts_due(_eng("2024-06-10", date(2025, 6, 9))) == date(2026, 3, 9)       # exactly 12 months
    assert accounts_due(_eng("2024-06-10", date(2025, 3, 31))) == date(2025, 12, 31)    # shortened first period


def test_first_period_over_twelve_months_is_later_of_21_months_and_3_months():
    assert accounts_due(_eng("2024-06-10", date(2025, 6, 30))) == date(2026, 3, 10)     # 21 months from formation
    assert accounts_due(_eng("2024-01-15", date(2025, 6, 30))) == date(2025, 10, 15)    # not 31 Mar 2026 (6 months late)
    assert accounts_due(_eng("2024-01-01", date(2025, 6, 30))) == date(2025, 10, 1)


CHART = {100: N(std_name="Sales", category="Sales", financial_class=PL),
         4131: N(std_name="Motor vehicles additions", category="Fixed assets", financial_class=BS)}


def _car(bought):
    c = compute(date(2026, 4, 1), date(2027, 3, 31) if bought <= "2027-03-31" else date(2028, 3, 31),
                {100: -100000.0, 4131: 40000.0}, CHART, {}, {}, vehicle_lines=[("Tesla Model 3 electric", 40000.0, bought)])
    return [a["suggested"] for a in c.ca_assets if a["key"].startswith("vehicle:")]


def test_zero_emission_car_gets_100_percent_only_until_march_2027():
    assert _car("2027-03-31") == ["FYA"]
    assert _car("2027-04-01") == ["MAIN"]


PLANT = {**CHART, 4121: N(std_name="Plant and equipment additions", category="Fixed assets", financial_class=BS)}


def _plant(start, end, cost, **inputs):
    c = compute(start, end, {100: -3000000.0, 4121: cost}, PLANT, inputs, {})
    fya = sum(l.amount for l in c.capital_allowances if "40%" in l.label)
    return c, fya


def test_plant_over_the_aia_gets_40_percent_from_january_2026():
    c, fya = _plant(date(2026, 4, 1), date(2027, 3, 31), 1500000.0)
    assert fya == 200000.0                                   # 40% of the £500,000 over the £1m AIA
    assert c.main_pool_cf == 300000.0                        # the other 60% joins the pool next period, no WDA now
    assert not any("Main pool writing-down" in l.label for l in c.capital_allowances)


def test_40_percent_not_given_for_a_period_before_or_across_january_2026():
    c, fya = _plant(date(2025, 4, 1), date(2026, 3, 31), 1500000.0)
    assert fya == 0.0 and any("40% first-year allowance" in n for n in c.notes)
    assert _plant(date(2026, 4, 1), date(2027, 3, 31), 800000.0)[1] == 0.0     # within the AIA: nothing over
    assert _plant(date(2026, 4, 1), date(2027, 3, 31), 1500000.0, fya_40=False)[1] == 0.0
