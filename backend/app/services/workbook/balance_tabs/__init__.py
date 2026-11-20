"""Balance sheet tabs the accountant's working papers have beyond the template: one tab per bank account, loans and
hire purchase per lender with the split due within / after one year, deposits, s455 recoverable and dividends. A tab
is made only when the client has that kind of account.

Every figure links back to the ETB / TTB, as in the rest of the workbook. Cells the accountant fills in (the bank
statement balance, an exchange rate, the loan split) are shaded INPUT_FILL; the loan split starts with the app's
suggestion from the ledger (twelve regular payments, capped at the balance), to check against the agreement.

One module per area: bank, common, debtors, leads, loans, reserves, tabs."""

from backend.app.services.workbook.balance_tabs.common import (  # noqa: F401
    BANK_CODES, BOLD, BROUGHT_FORWARD, CHECK_FILL, CURRENCY, Context, DEPOSIT_WORDS, DIVIDEND_CODES, INPUT_COLOUR,
    INPUT_FILL, LOANS_AFTER_1_YEAR, LOANS_WITHIN_1_YEAR, MONEY, OPENING_LINE, OTHER_DEBTORS, RESERVE_WORDS,
    S455_CODES, TITLE, TOTAL_BORDER, _blank, _criteria, _etb, _etb_bf, _etb_movement, _has_balance, _input,
    _lines_for, _money, _movement_label, _new_sheet, _records, _sheet_title, _ttb_account, _when, _write_lines)
from backend.app.services.workbook.balance_tabs.leads import (  # noqa: F401
    MAX_NAMED_JOURNALS, _journals_on, lead_lines, note_schedule)
from backend.app.services.workbook.balance_tabs.bank import (  # noqa: F401
    _bank_lead, _bank_summary, _regular_payment, bank_tabs)
from backend.app.services.workbook.balance_tabs.loans import (  # noqa: F401
    CREDITOR_LOAN_CODES, DEBTOR_NAME, GENERIC_LOAN, GL_LOAN_NAME, HP_NAME, LOAN_KIND, LOAN_NAME, NOT_A_LOAN,
    PERIOD_WORDS, _loan_groups, _loan_key, _loans_lead, loan_tabs)
from backend.app.services.workbook.balance_tabs.debtors import (  # noqa: F401
    _debtors_lead, deposit_tab, s455_tab)
from backend.app.services.workbook.balance_tabs.reserves import (  # noqa: F401
    dividend_tab)
from backend.app.services.workbook.balance_tabs.tabs import (  # noqa: F401
    add_balance_tabs)
