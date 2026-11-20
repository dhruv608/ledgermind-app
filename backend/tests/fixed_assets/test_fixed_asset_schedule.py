"""The fixed asset schedule's code roles (as the workbook's C1-1 tab)."""

from backend.app.services.papers.fixed_asset_schedule import fa_role


def test_roles_from_chart_names():
    assert fa_role("Plant and equipment - cost") == "COST"
    assert fa_role("Plant and equipment - additions") == "ADD"
    assert fa_role("Plant and equipment - disposals") == "DISP"
    assert fa_role("Plant and equipment - depreciation b/fwd") == "DEP_BF"
    assert fa_role("Land and property freehold - depreciation b/ fwd") == "DEP_BF"
    assert fa_role("Plant and equipment - depreciation charge in year") == "CHARGE"
    assert fa_role("Plant and equipment - impairment losses") == "CHARGE"
    assert fa_role("Plant and equipment - depreciation on disposals") == "DEP_DISP"
    assert fa_role("Goodwill - amortisation b/fwd") == "DEP_BF"
    assert fa_role("Goodwill - revaluations") == "ADD"


def test_asset_charge_as_the_workbook():
    from backend.app.services.papers.fixed_asset_schedule import asset_charge
    assert asset_charge(1500, 500, 0, 0.33, "SLM", 0) == 495            # cost times the rate
    assert asset_charge(1500, 1400, 0, 0.33, "SLM", 0) == 100           # never more than the NBV
    assert asset_charge(800, 200, 0, 0.25, "RBM", 0) == 150             # NBV times the rate
    assert asset_charge(800, 200, 50, 0.25, "RBM", 0) == 0              # sold in the year
    assert asset_charge(800, 200, 0, 0, "", 77) == 77                   # no rate: the register's own charge
