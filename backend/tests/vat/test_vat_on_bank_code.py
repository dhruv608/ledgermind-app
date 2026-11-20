"""The VAT account on a bank code is sent to review (Xero 'VAT' mapped to 4804)."""
from types import SimpleNamespace as NS

from backend.app.services.mapping.mapping_parts.checks import MappingChecks

BANK = NS(category="Cash at bank and in hand", std_name="Bank current account 5", std_code=4804,
          financial_class="Balance Sheet")
VAT = NS(category="Taxation and social security", std_name="VAT", std_code=5300, financial_class="Balance Sheet")


def test_vat_on_a_bank_code_is_a_problem():
    assert "says VAT" in MappingChecks._nature_problem("vat", -4807.57, BANK)
    assert "says VAT" in MappingChecks._nature_problem("vat control account", -10.0, BANK)


def test_a_bank_account_kept_for_vat_is_not():
    assert MappingChecks._nature_problem("barclays vat savings account", 5000.0, BANK) is None
    assert MappingChecks._nature_problem("vat", -4807.57, VAT) is None
    assert MappingChecks._nature_problem("vat", 6173.77, BANK) is None              # cash put aside for VAT
    assert MappingChecks._nature_problem("monzo vat pot account", -5.0, BANK) is None
    assert MappingChecks._nature_problem("merimakr vat (8524)", -5.0, BANK) is None
    assert MappingChecks._nature_problem("private", 10.0, BANK) is None      # 'private' holds 'vat' inside a word
