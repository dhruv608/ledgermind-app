"""Depreciation method and rate per class from the policy note of last year's filed accounts (Companies House iXBRL),
as three clients' 2024-25 accounts state them."""
from backend.app.services.setup.filed_policies import depreciation_policy

SLM = ("Depreciation is provided at rates calculated to write off the cost of the fixed assets, less their estimated "
       "residual value, over their expected useful lives on the following bases: Plant & Machinery 15% SLM Motor "
       "Vehicles 25%SLM Fixtures & Fittings 20%SLM Computer Equipment 33%SLM 2.4. Taxation")
RB = ("Depreciation is provided at rates calculated to write off the cost of the fixed assets on the following bases: "
      "Freehold N/A Leasehold N/A Plant & Machinery 20% reducing balance Motor Vehicles 20% reducing balance 2.5.")
BASIS = ("Depreciation is provided on a straight line basis at the following annual rates: Fixtures and fittings - 20% "
         "Computer equipment - 25%. 3. Employees")
LIVES = "Depreciation is charged so as to write off the cost over useful lives as follows: Office equipment over 4 years."


def test_slm_per_class():
    p = depreciation_policy(SLM)
    assert p["Plant and machinery"] == {"method": "STRAIGHT_LINE", "rate": 15.0}
    assert p["Motor vehicles"] == {"method": "STRAIGHT_LINE", "rate": 25.0}
    assert p["Fixtures and fittings"] == {"method": "STRAIGHT_LINE", "rate": 20.0}
    assert p["Computers"] == {"method": "STRAIGHT_LINE", "rate": 33.33}


def test_reducing_balance_and_na_classes_left_out():
    p = depreciation_policy(RB)
    assert p == {"Plant and machinery": {"method": "REDUCING_BALANCE", "rate": 20.0},
                 "Motor vehicles": {"method": "REDUCING_BALANCE", "rate": 20.0}}


def test_one_basis_for_all():
    p = depreciation_policy(BASIS)
    assert p["Fixtures and fittings"] == {"method": "STRAIGHT_LINE", "rate": 20.0}
    assert p["Computers"] == {"method": "STRAIGHT_LINE", "rate": 25.0}


def test_useful_life():
    assert depreciation_policy(LIVES) == {"Fixtures and fittings": {"method": "STRAIGHT_LINE", "rate": 25.0}}


def test_no_note_no_method():
    assert depreciation_policy("Micro-entity accounts. Fixed assets 12,000") == {}
    assert depreciation_policy("Depreciation is provided at the following rates: Plant 20%") == {}
