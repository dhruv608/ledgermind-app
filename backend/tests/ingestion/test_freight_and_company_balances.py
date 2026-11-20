"""Freight on goods bought goes to cost of sales (FRS 102 s13.6), and balances named after a company are not trade
debtors or creditors (4400 -> 4420/5350). Freight goes to the firm's own code for it (firm policies: 1100
Purchases), else the chart's 1711."""
from types import SimpleNamespace as NS

from backend.app.services.mapping.mapping_parts.checks import MappingChecks

COA = {c: NS(std_code=c, std_name=n) for c, n in (
    (3275, "Carriage and freight (General admin)"), (1711, "Carriage and freight (Cost of sales)"),
    (1100, "Purchases (Cost of sales)"),
    (4400, "Trade debtors"), (5200, "Trade creditors"), (4420, "Other debtors"), (5350, "Other creditors"))}


def _run(check, name, code, net=0.0, source="AI"):
    rows, results = [{"name": name, "net": net}], [{"std_code": code, "std_name": "", "match_source": source}]
    check(rows, results, COA)
    return results[0]["std_code"]


def test_freight_on_goods_bought_is_cost_of_sales():
    for name in ("Freight and services", "Fright and services", "Sea Freight Charges", "Freight and delivery charges",
                 "Import clearance", "freight and handling"):
        assert _run(MappingChecks._freight_to_cost_of_sales, name, 3275) == 1100, name
    assert _run(MappingChecks._freight_to_cost_of_sales, "Carriage and freight", 1711) == 1100   # the AI's 1711 too


def test_freight_without_a_firm_code_goes_to_the_chart_line(monkeypatch):
    from backend.app.services.shared import rules_store
    monkeypatch.setattr(rules_store, "load", lambda name: {})
    assert _run(MappingChecks._freight_to_cost_of_sales, "Sea Freight Charges", 3275) == 1711


def test_postage_couriers_and_carriage_out_stay_in_overheads():
    for name in ("Postage and carriage", "Courier and delivery charges", "Carriage outwards", "Delivery charges"):
        assert _run(MappingChecks._freight_to_cost_of_sales, name, 3275) == 3275, name
    assert _run(MappingChecks._freight_to_cost_of_sales, "Freight", 3275, source="LAST_YEAR") == 3275   # not the AI's


def test_a_company_named_balance_is_not_trade():
    f = MappingChecks._company_balances_not_trade
    assert _run(f, "Acme Trading", 4400, 517.90) == 4420
    assert _run(f, "SSPA Limited", 4400, 18734.60) == 4420
    assert _run(f, "Beta Holdings Ltd", 5200, -44229.38) == 5350


def test_control_accounts_lenders_and_banks_keep_their_code():
    f = MappingChecks._company_balances_not_trade
    assert _run(f, "Trade debtors - ABC Ltd", 4400, 100.0) == 4400
    assert _run(f, "Loan_Bizlend LTD", 5200, -100.0) == 5200
    assert _run(f, "KAJ WHOLESALE LTD-METRO BANK", 5200, -60.6) == 5200
    assert _run(f, "Sales ledger control", 4400, 100.0) == 4400
    assert _run(f, "Acme Trading", 4400, 517.90, source="LAST_YEAR") == 4400


def test_depreciation_named_charge_not_on_amortisation():
    coa = {**COA, 3400: NS(std_code=3400, std_name="Depreciation"), 3500: NS(std_code=3500, std_name="Amortisation")}
    run = lambda name, src="AI": (lambda rows, res: (MappingChecks._depreciation_not_amortisation(rows, res, coa), res[0]["std_code"])[1])(
        [{"name": name, "net": 100.0}], [{"std_code": 3500, "std_name": "", "match_source": src}])
    assert run("417 - Depreciation Expense - ROU Assets (Allowable)") == 3400
    assert run("Amortisation of goodwill") == 3500
    assert run("Depreciation - software licence") == 3500
    assert run("Depreciation Expense - ROU", src="LAST_YEAR") == 3500
