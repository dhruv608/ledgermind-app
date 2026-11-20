"""Wages / salaries control and pension payable accounts are the amounts owed, not the costs."""
import re

from backend.app.services.mapping.mapping_parts.common import STATUTORY_SYNONYM_RULES


def first_rule(name: str):
    return next((code for pattern, code in STATUTORY_SYNONYM_RULES if re.search(pattern, name.lower())), None)


def test_wages_control_is_net_wages():
    for name in ("Wages and salaries control", "Salaries and wages control", "Wages control", "Salaries payable",
                 "Net pay"):
        assert first_rule(name) == 5330, name
    assert first_rule("Wages and salaries") == 3000


def test_pension_payable_is_owed():
    for name in ("Pension payable", "Pensions creditor", "Pension liability", "NEST payable"):
        assert first_rule(name) == 5352, name
    assert first_rule("Employers pension contributions") == 3002
