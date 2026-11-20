"""A director's loan code in an account name that is the client's own number for another lender is not kept by the
code-in-name rule ('5401 Lloyds Bank Loan'); the other balance sheet codes kept by the rule stay ('4804 - VAT')."""
import os
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.mapping.mapping_parts.code_in_name import code_in_name

CURRENT = "Current liabilities - creditors < 1 year"
CHART = {
    4800: N(std_code=4800, std_name="Bank current account", category="Cash at bank and in hand", financial_class="Balance Sheet"),
    4804: N(std_code=4804, std_name="Bank current account (5)", category="Cash at bank and in hand", financial_class="Balance Sheet"),
    5300: N(std_code=5300, std_name="VAT", category=CURRENT, financial_class="Balance Sheet"),
    5400: N(std_code=5400, std_name="Directors loan account", category=CURRENT, financial_class="Balance Sheet"),
    5401: N(std_code=5401, std_name="Directors loan account - capital", category=CURRENT, financial_class="Balance Sheet"),
    5500: N(std_code=5500, std_name="Bank loans", category="Long term liabilities", financial_class="Balance Sheet"),
}


def test_lender_loan_on_a_directors_loan_code_not_kept():
    assert code_in_name("5401 Lloyds Bank Loan - 804201", CHART, True, None) is None


def test_directors_loan_and_other_codes_kept():
    assert code_in_name("5401 - Directors loan - Martin", CHART, True, None)["std_code"] == 5401
    assert code_in_name("5400 Directors loan account", CHART, True, None)["std_code"] == 5400
    assert code_in_name("4804 - VAT", CHART, True, None)["std_code"] == 4804


def test_personal_items_on_the_directors_loan_kept():
    # A client posting personal items to its director's loan under their own names: they stay on it
    chart = {**CHART, 3140: N(std_code=3140, std_name="Repairs and maintenance", category="Premises expenses",
                              financial_class="Profit and Loss")}
    assert code_in_name("5400 - Repairs & Maintenance", chart, True, None)["std_code"] == 5400
    assert code_in_name("5400 - Barclaycard (Personal Expenses) DLA", chart, True, None)["std_code"] == 5400
