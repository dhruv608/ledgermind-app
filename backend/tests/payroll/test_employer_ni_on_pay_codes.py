"""Employer NI the firm codes with the wages (an account named employer NI on 3000 / 3010 / 1500) is NI, not gross pay:
the payroll report's NI is then not posted a second time (e.g. 'Employers NI' on 1500)."""
from types import SimpleNamespace as NS

from backend.app.services.review.payroll_journals.common import EMPLOYER_NI_NAME, employer_ni_on_wage_codes


def _tb(name, code, amount):
    return NS(raw_account_name=name, std_code=code, net_amount=amount)


def test_names_that_are_employer_ni():
    for n in ("Employers NI", "1500 - Employers NI (Employee costs)", "Employer's NI contributions",
              "3010 - 3001 Employer's NI contributions", "Employers National Insurance", "Er's NIC", "Employer NIC"):
        assert EMPLOYER_NI_NAME.search(n), n


def test_names_that_are_not():
    for n in ("Wages and salaries", "Employee NI", "Directors' salaries", "Employers NEST", "Employer pension",
              "Employment allowance", "Nicholas Smith wages"):
        assert not EMPLOYER_NI_NAME.search(n), n


def test_only_on_pay_codes():
    tb = [_tb("Gross Wages", 1500, 105627.11), _tb("Employers NI (Employee costs)", 1500, 8578.01),
          _tb("Employers NI", 3001, 400.0), _tb("Employers NI", 5320, -900.0), _tb("3000 - Employers NI", 3000, 693.21)]
    assert employer_ni_on_wage_codes(tb) == 9271.22
