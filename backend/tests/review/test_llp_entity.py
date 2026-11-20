"""An LLP is not a company for tax (CTA 2009 s1273): no corporation tax, dividends or s455."""
from types import SimpleNamespace as NS

from backend.app.services.setup.entity import COMPANY_ONLY_REFS, is_llp


def test_llp_by_name_or_number():
    assert is_llp(NS(client_name="Acme Kitchen Co LLP"))
    assert is_llp(NS(client_name="Smith & Co Limited Liability Partnership"))
    assert is_llp(NS(client_name="Smith & Co"), NS(companies_house='{"company_number": "OC414093"}'))
    assert not is_llp(NS(client_name="Acme Pie Ltd"), NS(companies_house='{"company_number": "12345678"}'))
    assert not is_llp(NS(client_name="Help Ltd"))


def test_company_only_points():
    assert "U-DIV-001".startswith(COMPANY_ONLY_REFS) and "U-DLA-001".startswith(COMPANY_ONLY_REFS)
    assert not "U-DLA-003".startswith(COMPANY_ONLY_REFS)
