"""An account no code is found for goes to other debtors (a current asset) or other creditors (a
liability), not suspense; anything else stays in suspense for the accountant."""
from types import SimpleNamespace as NS

from backend.app.services.mapping.mapping_parts.ai_mapping import AiMapping

CHART = {4420: NS(std_name="Other debtors"), 5350: NS(std_name="Other creditors"), 9999: NS(std_name="Suspense")}


def test_current_asset_to_other_debtors():
    m = AiMapping._ai_answer_to_mapping({"name": "Deposit held", "account_type": "Current Asset"}, None, "timeout", CHART)
    assert m["std_code"] == 4420 and m["mapping_status"] == "NEEDS_REVIEW" and "other debtors" in m["mapping_reason"]


def test_liability_to_other_creditors():
    m = AiMapping._ai_answer_to_mapping({"name": "Owed to X", "account_type": "Current Liability"}, {"code": "123"},
                                        None, CHART)
    assert m["std_code"] == 5350


def test_no_type_or_cost_stays_in_suspense():
    for kind in (None, "", "Expense"):
        m = AiMapping._ai_answer_to_mapping({"name": "Something", "account_type": kind}, None, "no answer", CHART)
        assert m["std_code"] == 9999
