"""Self-employment (SA103) adjusted profit, against TaxCalc's 2025-26 profit computations (figures only)."""

from types import SimpleNamespace as N

from backend.app.sa.trade import mileage, one, use_of_home


def biz(**kw):
    base = dict(id=1, name="Business", home_hours=0, home_months=0, car_miles=0, motorcycle_miles=0, capital_allowances=0,
                balancing_charges=0, losses_bf=0, cis_deducted=0, use_trading_allowance=0)
    return N(**{**base, **kw})


def items(*rows):
    return [N(heading=h, amount=a, disallowed=d) for h, a, d in rows]


def test_trade_with_disallowable_costs():
    r = one(biz(), items(("TURNOVER", 26839, 0), ("COST_OF_SALES", 6517, 0), ("STAFF", 21, 0), ("TRAVEL", 1482, 0),
                         ("PREMISES", 684, 0), ("OFFICE", 634, 144), ("FINANCE", 42, 0), ("PROFESSIONAL", 870, 0),
                         ("OTHER", -1, 0)), "2025-26")
    assert (r["accounts_profit"], r["disallowed"], r["taxable_profit"], r["page"]) == (16590, 144, 16734, "SA103S")


def test_trading_allowance_instead_of_costs():
    r = one(biz(use_trading_allowance=1), items(("TURNOVER", 5400, 0)), "2025-26")
    assert (r["trading_allowance"], r["taxable_profit"]) == (1000, 4400)


def test_simplified_expenses_and_depreciation():
    assert use_of_home(60, 12, "2025-26") == 216          # 51-100 hours: £18 a month
    assert use_of_home(20, 12, "2025-26") == 0            # under 25 hours: nothing
    assert mileage(12000, 0, "2025-26") == 5000           # 10,000 at 45p + 2,000 at 25p
    r = one(biz(home_hours=60, home_months=12, car_miles=12000), items(("TURNOVER", 30000, 0), ("DEPRECIATION", 800, 0)), "2025-26")
    assert (r["disallowed"], r["taxable_profit"]) == (800, 24784)


def test_loss_brought_forward_and_carried():
    r = one(biz(losses_bf=3000), items(("TURNOVER", 10000, 0), ("OTHER", 8000, 0)), "2025-26")
    assert (r["losses_used"], r["taxable_profit"], r["loss_cf"]) == (2000, 0, 1000)
