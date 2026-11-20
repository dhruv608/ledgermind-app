"""Raw data route, step 1: read a client's input file (no accounting software) and check it.

The input is one workbook (or several files) as the firm prepares it: one bank statement tab per bank account (from
the client's bank), and the sales invoices and purchase bills (exported from Dext); a client with no sales invoices
(cash takings banked) has no sales tab. Tabs and columns are found by their headings, not their position, since every
bank and every Dext export words them a little differently. Nothing is posted here: this only reads the lists and
reports what is wrong with them before matching.

One module per area: bank, common, invoices, opening, parts, reader."""

from backend.app.services.bank_only.input_files.common import (  # noqa: F401
    AMOUNT_EXACT, BANK_CODES, BANK_KINDS, BANK_TYPES, BankAccount, BankLine, CARD_CODE, CARD_NAME, DAMAGED_NUMBER,
    DESC_WORDS, HEAD_COLUMN, INVOICE_REF, IN_EXACT, IN_WORDS, Invoice, NARRATIVE_KINDS, OPENING_WORDS, OUT_EXACT,
    OUT_WORDS, OpeningCoder, PARTY_WORDS, Problem, RawInput, UNDATED_NOT_A_LINE, YEAR_END, _amount, _col, _date,
    _find_tab, _header, _money_columns, _title_values)
from backend.app.services.bank_only.input_files.parts import (  # noqa: F401
    BANK, BILLS, LEDGER_COLUMNS, OPENING_BILLS, OPENING_SALES, OPENING_TB, RAW_ROLES, REPEATED_MIN_LINES,
    REPEATED_SHARE, ROLE_LABELS, SALES, SKIP, STATEMENT_IN_OUT, _LAST_YEAR, _all_before, _csv_value,
    _drop_repeated_statements, _parts, _read_parts, _titled_ledger, identify_parts, is_raw_upload,
    looks_like_statement, part_role)
from backend.app.services.bank_only.input_files.opening import (  # noqa: F401
    _code_opening_names, _read_opening_tb, brought_forward_code, close_last_year)
from backend.app.services.bank_only.input_files.bank import (  # noqa: F401
    SUSPENSE_CODE, _account_name, _bank_codes, _bank_kind, _breaks, _chain, _check_bank, _in_order,
    _line_date_column, _owed_balances, _read_bank)
from backend.app.services.bank_only.input_files.invoices import (  # noqa: F401
    _check_invoices, _read_invoices, number_key)
from backend.app.services.bank_only.input_files.reader import (  # noqa: F401
    read_input_files)
