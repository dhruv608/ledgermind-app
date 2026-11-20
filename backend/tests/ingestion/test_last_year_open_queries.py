"""Last year's Notes & Queries points carried forward."""

import json
from types import SimpleNamespace

from backend.app.services.ingestion.last_year_adjustments import open_queries
from backend.app.services.queries.last_year_rules import last_year_queries

ROWS = [["Client A Ltd"], ["Year Ended 31 March 2025"], [None],
        ["Sr", "NOTES & QUERIES"],
        [1, "Preparation", "Please note that the accounts have been prepared using the general ledger."],
        [None, "These accounts have been prepared under FRS 102 (1A) as in previous years."],
        [2, "Stock", "Please note that the closing stock has been recorded as the opening stock."],
        [None, "Kindly provide the confirmation of the stock at the year end."],
        ["10.1", "Net wages", "Please note that the closing net wages balance was paid after the year end."],
        [None, "Name", "Due Months", "Wages payable"],
        [19649.99, "Total of the table above"],
        [3, "Trade creditors", "Please note that the closing balance of creditors is 2,500. Please check and confirm."]]


def test_points_that_ask_the_client():
    found = open_queries(ROWS)
    assert [(q["no"], q["area"]) for q in found] == [("2", "Stock"), ("3", "Trade creditors")]
    assert "Kindly provide the confirmation" in found[0]["text"]


def test_ly01_query_lists_them():
    tax = {"_last_year_wp": {"open_queries": open_queries(ROWS)}}
    out = last_year_queries(SimpleNamespace(id="x"), SimpleNamespace(tax_inputs=json.dumps(tax)))
    assert len(out) == 1 and out[0]["ref"] == "LY-01" and "Stock" in out[0]["detail"]
    assert last_year_queries(SimpleNamespace(id="x"), SimpleNamespace(tax_inputs="{}")) == []
