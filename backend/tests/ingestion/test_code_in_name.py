"""A balance sheet firm code in the account name wins for a client on the firm's codes."""
from types import SimpleNamespace as NS

from backend.app.services.mapping.mapping_parts.code_in_name import code_in_name

CHART = {
    5320: NS(std_code=5320, std_name="Other taxes and social security", financial_class="Balance Sheet", category="Creditors"),
    5352: NS(std_code=5352, std_name="Credit card 2", financial_class="Balance Sheet", category="Creditors"),
    4121: NS(std_code=4121, std_name="Plant and equipment - additions", financial_class="Balance Sheet", category="Fixed assets"),
    3260: NS(std_code=3260, std_name="Insurance", financial_class="Profit and Loss", category="General admin"),
}


def test_code_wins_for_balance_sheet():
    assert code_in_name("5320 - Net wages (Current liabilities)", CHART, True, None)["std_code"] == 5320
    assert code_in_name("5352 - Capital on Tap", CHART, True, None)["std_code"] == 5352


def test_left_to_other_rules():
    assert code_in_name("5352 - Capital on Tap", CHART, False, None) is None       # client not on firm codes
    assert code_in_name("4121 - Plant and equipment - cost", CHART, True, None) is None   # fixed assets
    assert code_in_name("3260 - Motor insurance", CHART, True, None) is None        # P&L
    assert code_in_name("Capital on Tap", CHART, True, None) is None
    assert code_in_name("5352 - Rental and other income from property", CHART, True, None) is None   # income words


def test_zero_is_sales_in_a_double_coded_chart():
    from backend.app.services.mapping.mapping_parts.code_in_name import double_coded, zero_is_sales
    chart = {**CHART, 0: NS(std_code=0, std_name="Sales", financial_class="Profit and Loss", category="Sales")}
    names = ["1440 - 450 - Subcontractor", "3280 - 3280 - Advertising", "5320 - 820 - PAYE", "4800 - 090 - Bank",
             "3260 - 461 - Insurance", "0 - 201 - Casting"]
    assert double_coded(names)
    assert zero_is_sales("0 - 201 - Casting", -1165575.30, chart, True)["std_code"] == 0
    assert zero_is_sales("0 - 610 - Prepayments", 500.0, chart, True) is None          # a debit: other rules
    assert zero_is_sales("0 - 201 - Casting", -10.0, chart, False) is None              # chart not double coded
    assert not double_coded(["0 - Savings by FRS", "0 - Discount allowed", "Sales", "Rent"])
