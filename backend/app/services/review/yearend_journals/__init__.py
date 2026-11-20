"""
Year-end journals the accountant posts on every job, proposed from the data (each is approved or rejected on the
Journals tab, and only approved ones reach the ETB):

- Opening stock reversed: last year's closing stock (the stock account's opening balance) goes to the P&L opening
  stock line, so this year's cost of sales carries it.
- Closing stock: the year-end figure entered on the client setup (Policies) goes back onto the balance sheet.
- Depreciation from the fixed asset register: the register's own charge for the assets brought forward, plus this
  year's additions (from the TB) at the class rate for the months held, against the charge already in the books.

Each journal is proposed only while it is still missing, judged on the balances after the journals already approved,
so an approved journal is not proposed again on the next run.
"""

# The parts live in this package; every name callers use is re-exported here.

from backend.app.services.review.setup_checks import ASSET_CLASS_CODES, INTANGIBLE_CLASS_CODES, setup_of  # noqa: F401
from backend.app.services.review.yearend_journals.common import (  # noqa: F401
    CLOSING_STOCK_PL, DEPRECIATION_PL, FAR_CLASS, MIN_AMOUNT, OPENING_STOCK_PL, REGISTER_TOLERANCE, STOCK_LINES,
    _entry, _journal, _point,
)
from backend.app.services.review.yearend_journals.stock import (  # noqa: F401
    COST_OF_SALES, last_year_stock, stock_in_pl, stock_journals,
)
from backend.app.services.review.yearend_journals.depreciation import (  # noqa: F401
    _far_class, _months_held, _rate, far_depreciation, merged_classes, register_unreliable_classes,
)
from backend.app.services.review.yearend_journals.far_register import (  # noqa: F401
    CAPITAL_MATCH_DAYS, CAPITAL_MATCH_TOLERANCE, NOT_CAPITAL_PL, far_additions_in_pl, far_books_check,
)
from backend.app.services.review.yearend_journals.corporation_tax import (  # noqa: F401
    CT_CHARGE_CODE, CT_CREDITOR, CT_PRIOR_YEAR, S455_DEBTORS, ct_prior_year,
)
