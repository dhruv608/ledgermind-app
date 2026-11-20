"""A cost the chart has in overheads and in cost of sales goes to the cost of sales one when the client's books put it
there ('Cost of sales:Commissions payable' -> 1520, not 3306)."""
from types import SimpleNamespace as NS

from backend.app.services.mapping.mapping_service import MappingService

COA = {c: NS(std_code=c, std_name=n, category=k) for c, n, k in [
    (3306, "Commissions payable (General admin)", "General admin"),
    (1520, "Commissions payable (Cost of sales)", "Cost of sales"),
    (3260, "Insurance (General admin)", "General admin"),
    (1660, "Insurance (Cost of sales)", "Cost of sales"),
    (3301, "Accountancy fees", "General admin")]}


def _run(name, code, source="COA_NAME", account_type=None):
    rows = [{"name": name, "account_type": account_type, "net": 100.0}]
    results = [{"std_code": code, "std_name": COA[code].std_name, "match_source": source, "mapping_reason": ""}]
    MappingService._cost_of_sales_twin(rows, results, COA)
    return results[0]["std_code"]


def test_cost_of_sales_parent_moves_to_twin():
    assert _run("Cost of sales:Commissions payable", 3306) == 1520


def test_direct_costs_type_moves_to_twin():
    assert _run("Insurance", 3260, account_type="Direct Costs") == 1660


def test_overhead_stays_without_the_client_saying_so():
    assert _run("Commissions payable", 3306) == 3306
    assert _run("Expenses:Insurance", 3260) == 3260


def test_no_twin_or_fixed_source_stays():
    assert _run("Cost of sales:Accountancy fees", 3301) == 3301
    assert _run("Cost of sales:Commissions payable", 3306, source="LAST_YEAR") == 3306
