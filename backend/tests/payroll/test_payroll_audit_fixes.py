"""Payroll: missing payroll posted where wages sat; interest or a penalty on late PAYE named on the PAYE account
(CTA 2009 s1303)."""
from types import SimpleNamespace as N

from backend.app.services.review.paye_check import PAYE_INTEREST
from backend.app.services.review.payroll_journals.missing import wage_codes


def test_wages_kept_in_cost_of_sales_when_they_sit_there():
    cos = [N(std_code=1500, net_amount=12000, opening_amount=0), N(std_code=1501, net_amount=900, opening_amount=0)]
    assert wage_codes(cos)[3000] == 1500 and wage_codes(cos)[3001] == 1501
    admin = [N(std_code=3000, net_amount=12000, opening_amount=0), N(std_code=1500, net_amount=500, opening_amount=0)]
    assert wage_codes(admin)[3000] == 3000
    assert wage_codes([])[3000] == 3000


def test_paye_interest_lines():
    assert PAYE_INTEREST.search("HMRC - Late payment interest PAYE")
    assert PAYE_INTEREST.search("HMRC penalty month 6")
    assert not PAYE_INTEREST.search("HMRC - 123PA00012345 PAYE")
