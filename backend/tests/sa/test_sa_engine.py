"""The Self Assessment engine against TaxCalc's own calculations (figures from the firm's TaxCalc reports, no names
or other personal details). Run: python -m pytest backend/tests/sa/test_sa_engine.py"""

import pytest

from backend.app.sa.engine.calc import Income, calculate

CASES = [
    # 2025-26 TaxCalc report sets
    ("Set 1 2025-26: employment and a small trade", Income(tax_year="2025-26", employment=22638, self_employment=4310, tax_deducted=3054),
     {"income_tax_due": 2875.60, "class4": 0.0, "balance": -178.40, "poa_each": 0.0}),
    ("Set 2 2025-26: sole trader, Class 4", Income(tax_year="2025-26", self_employment=16734),
     {"income_tax_due": 832.80, "class4": 249.84, "liability": 1082.64, "poa_each": 541.32}),
    ("Set 3 2025-26: just over the allowance", Income(tax_year="2025-26", employment=7505, self_employment=4400, pensions=741),
     {"income_tax_due": 15.20, "liability": 15.20, "poa_each": 0.0}),
    # 2024-25 TaxCalc tax summaries
    ("Case A 2024-25: foreign income", Income(tax_year="2024-25", self_employment=11811, foreign=31435),
     {"income_tax_due": 6135.20, "class4": 0.0}),
    ("Case B 2024-25: PSA, dividends, pension band extension",
     Income(tax_year="2024-25", employment=82501, savings=1714, dividends=11592, pension_ras_gross=48000,
            tax_deducted=19588),
     {"income_tax_due": 15099.55, "balance": -4488.45}),
    ("Case C 2024-25: dividend lines rounded down",
     Income(tax_year="2024-25", employment=37356, savings=125, dividends=17000),
     {"income_tax_due": 7453.69}),
    ("Case D 2024-25: finance cost credit",
     Income(tax_year="2024-25", property=75639, finance_costs=70881, payments_on_account_made=3674.30),
     {"income_tax": 17687.60, "income_tax_due": 5073.80, "poa_each": 2536.90, "due_31_january": 3936.40}),
]


@pytest.mark.parametrize("name,inc,want", CASES, ids=[c[0] for c in CASES])
def test_taxcalc(name, inc, want):
    got = calculate(inc)
    for key, value in want.items():
        assert getattr(got, key) == pytest.approx(value, abs=0.005), f"{name}: {key}"


def test_pence_in_income_not_lost_rounding_down():
    # £36,442.70 taxable at 20% is £7,288.54 (in binary 7288.5399...: must not round down to .53)
    got = calculate(Income(tax_year="2025-26", employment=48250, pensions=762.70, savings=2290, dividends=2300,
                           gift_aid_gross=500, tax_deducted=7136))
    assert got.income_tax_due == pytest.approx(8360.58, abs=0.001)
    assert got.poa_each == 0                       # at least 80% taxed at source


def test_personal_allowance_taper():
    # £110,000: the allowance falls by £5,000 (ITA 2007 s35)
    assert calculate(Income(tax_year="2025-26", employment=110000)).personal_allowance == 7570
    # Gift Aid lowers adjusted net income and extends the bands
    got = calculate(Income(tax_year="2025-26", employment=110000, gift_aid_gross=10000))
    assert got.personal_allowance == 12570


def test_payments_on_account_made_come_off_31_january():
    # R-FAM-03: what was paid on account for the year comes off the balancing payment
    base = calculate(Income(tax_year="2025-26", self_employment=40000))
    paid = calculate(Income(tax_year="2025-26", self_employment=40000, payments_on_account_made=2000))
    assert paid.due_31_january == round(base.due_31_january - 2000, 2) and paid.balance == base.balance


def test_class2_below_the_small_profits_threshold():
    # R-NIC-01: under the threshold Class 2 is not treated as paid; voluntary Class 2 only when chosen
    low = calculate(Income(tax_year="2025-26", self_employment=4986))
    assert low.class2_below_threshold and low.class2 == 0
    chosen = calculate(Income(tax_year="2025-26", self_employment=4986, class2_voluntary=True))
    assert chosen.class2 > 0
    assert not calculate(Income(tax_year="2025-26", self_employment=20000)).class2_below_threshold


def test_overseas_finance_costs_get_their_own_credit():
    """ITTOIA s274A per property business: an overseas-only landlord's mortgage interest gets the 20% credit, limited by
    the overseas profit, not the (nil) UK profit."""
    from backend.app.sa.engine.calc import Income, calculate
    inc = Income(employment=40000, foreign=8000, overseas_property=8000, overseas_finance_costs=5000)
    calc = calculate(inc)
    assert calc.reductions["finance_costs"] == 1000 and calc.overseas_finance_costs_relieved == 5000
    # Both: each limited by its own profit (UK 3,000 of 6,000; overseas 2,000 of 2,000)
    both = calculate(Income(employment=40000, property=3000, finance_costs=6000, foreign=2000, overseas_property=2000,
                            overseas_finance_costs=2000))
    assert both.reductions["finance_costs"] == 1000
    assert (both.finance_costs_relieved, both.overseas_finance_costs_relieved) == (3000, 2000)
