"""Payroll year-end journals an accountant makes on most clients, proposed by the review:

  U-PAY-003  Employment allowance: employer NI for the year, less the allowance (P-EA, £10,500 from 6 Apr 2025,
             £5,000 before), not yet claimed in the books -> Dr PAYE / NI owed, Cr employer NI. Books whose employer
             NI is the payroll report's less the allowance already hold it (claimed through the payroll).
  U-PAY-004  Directors' pay in the staff accounts: wages / pension ledger lines that name a director, and employer
             pension paid outside the payroll when the payroll report shows none for the directors.
  U-PAY-007  Directors' pay per the payroll file ('Director Salary' line, a block per director) not in the directors'
             accounts: the rest moved from staff wages (often all posted to 3000).
  U-PRE-002  Last year's prepayment not released: the prepayment brought forward is still in the books unchanged.
  U-ACC-003  Last year's accrual not released: the same for the accruals brought forward (the cost was charged last
             year, so the bill posted this year counts it twice unless the accrual is reversed).

Journals already approved in the app are taken into account, so nothing is proposed twice.

One module per area: allowance, common, directors, hmrc, missing, net_wages, overpaid, released."""

from backend.app.services.review.payroll_journals.common import (  # noqa: F401
    DIRECTOR_PAY_NAME, DIRECTOR_PENSION_CODES, DIRECTOR_SALARY_CODES, EA_BEFORE_APRIL_2025, EA_WORDS,
    EMPLOYER_NI_CODES, MIN_AMOUNT, PENSION_TO_DIRECTORS, SALARY_TO_DIRECTORS, WAGE_COST_CODES, _allowance_for,
    _entry, _gl_codes, _journal, _journal_lines, _last_year_pay, _lines, _month, _names_person, _net_pay,
    _only_director, _only_director_by_books, _report, _words, employer_ni_on_wage_codes)
from backend.app.services.review.payroll_journals.allowance import (  # noqa: F401
    CLASS_1A_WORDS, NETTED_TOLERANCE, _allowance_in_books, _allowance_in_period, _employment_allowance,
    allowance_in_books_total, allowance_in_payroll, employment_allowance, payroll_file_allowance)
from backend.app.services.review.payroll_journals.directors import (  # noqa: F401
    _directors_last_year, director_pay, directors_per_payroll)
from backend.app.services.review.payroll_journals.missing import (  # noqa: F401
    DIRECTORS_LOAN, PENSION_OWED, _salary_as_last_year, _wages_from_bank, missing_payroll)
from backend.app.services.review.payroll_journals.released import (  # noqa: F401
    ACCRUALS, _brought_forward_not_released, accrual_not_released, prepayment_not_released)
from backend.app.services.review.payroll_journals.hmrc import (  # noqa: F401
    HMRC_PAYE, _payroll_year, hmrc_in_net_wages)
from backend.app.services.review.payroll_journals.overpaid import (  # noqa: F401
    DIRECTOR_OVERPAID, OVERPAID_MIN, net_pay_overpaid_to_director)
from backend.app.services.review.payroll_journals.net_wages import (  # noqa: F401
    NET_WAGES_MATCH, NET_WAGES_MONTHS, net_wages_cleared_elsewhere)
