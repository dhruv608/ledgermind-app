"""
Raw data route, step 2: sort every bank line into what it is ("head"), before any posting.

Order, strongest first:
  both       0. money moved between the client's own bank accounts: the same amount out of one account and into
                another within 3 days -> transfer (the accountant's 'Transfers' account 9998 nets to nil)
  money in   1. quotes one of the client's sales invoice numbers, or names one of its customers -> customer receipt
  money out  2. pays one of the Dext purchase bills (same amount, close date)                  -> supplier bill paid
  both       3. the director's name                                                              -> director's loan
             4. the firm's starting rules on the payee (DVLA -> vehicle, HMRC Cotax -> corporation tax, ...)
             5. other money in: a receipt from a customer not yet identified; money out naming a supplier
                with no bill for the amount: an invoice to ask for
             6. anything else is left unsorted for the accountant (never guessed)
Matching receipts to particular invoices is step 3; this step only says what each line is.
"""

# The parts live in this package; sort_bank runs them, and every name callers use is re-exported here.

import re
from typing import List, Optional

from backend.app.services.bank_only.categories import code_for, paid_by_director
from backend.app.services.bank_only.input_files import RawInput, number_key
from backend.app.services.bank_only.bank_sort.heads import (  # noqa: F401
    BY_INDUSTRY, CUSTOMER, DIRECTOR, DIY_STORE, FOOD_INDUSTRIES, FOOD_SHOP, GUIDE_HEADS, HEAD_CODES, OPENING_MONEY,
    PERSONAL_SHOP, RULES, SUPPLIER, TRANSFER, TRANSFERS, UNSORTED, UNSURE_HEADS, _RULES, BankSort, SortedLine,
)
from backend.app.services.bank_only.bank_sort.names import (  # noqa: F401
    _COMMON, CHANNEL_WORDS, OWN_MONEY, PAYER_PREFIX, _director_words, _is_name, _name_matches, _names_director,
    _payer_words, _words,
)
from backend.app.services.bank_only.bank_sort.passes import (  # noqa: F401
    CARD_REPAYMENT, PROPERTY_HOW, PROPERTY_LARGE, TO_ACCOUNT, UNKNOWN_ACCOUNT_HOW, UNKNOWN_ACCOUNT_LINES,
    _card_money_in, _property_money, _refunds, _unknown_accounts, own_transfers,
)
from backend.app.services.bank_only.bank_sort.sort_one import DIRECTOR_PAY, NOT_SALES_KINDS, _sort_one  # noqa: F401

def sort_bank(raw: RawInput, directors: Optional[List[str]] = None, payroll: bool = False,
              industry: Optional[str] = None, first_period: bool = False, industry_from: str = "") -> BankSort:
    """industry_from: where an industry the accountant has not confirmed was taken from ('the company name'); its
    lines are left to check."""
    surnames = _director_words(directors or [])
    suppliers = sorted({i.party for i in raw.purchases if i.party}, key=len, reverse=True)
    numbers = {number_key(i.number): i for i in raw.sales if number_key(i.number)}
    # Invoice numbers of letters and a short count ('PSOCT25') quoted whole on a receipt: added to its references
    whole = {k for k in numbers if not k.isdigit()} | \
        {number_key(i.number) for i in raw.opening_sales if number_key(i.number) and not number_key(i.number).isdigit()}
    if whole:
        for b in raw.bank:
            for token in re.findall(r"[A-Za-z0-9]+", b.description.upper()):
                if token in whole and token not in b.refs:
                    b.refs.append(token)
    customers = sorted({i.party for i in raw.sales if i.party}, key=len, reverse=True)
    # A bill the director paid personally is never paid from the bank
    open_bills = [i for i in raw.purchases if not paid_by_director(i.category)]
    # No sales invoices kept (a takeaway banking its takings): money in from customers is sales
    takings = not raw.sales and not raw.opening_sales
    pairs = own_transfers(raw)
    own = _words(raw.client_name)
    result = BankSort()
    for b in raw.bank:
        other = pairs.get(id(b))
        if other is not None:
            way = "to" if b.money_out else "from"
            result.lines.append(SortedLine(b, TRANSFER, TRANSFERS, f"moved {way} {other.account} "
                                           f"(£{other.money_in or other.money_out:,.2f} on {other.when:%d/%m/%Y})",
                                           True, pair=other))
            continue
        s = _sort_one(b, numbers, customers, open_bills, surnames, suppliers, payroll, industry, own, industry_from)
        matched = s.head == SUPPLIER or (s.head == CUSTOMER and s.customer)
        given = code_for(b.head_given, raw.materials_code)
        # A director's loan head written on money in that does not name a director, for a client with sales invoices,
        # is not taken ('DLA' written on every line, including large receipts from customers): the line is read as
        # any other
        doubt = (given is not None and 5400 <= given < 5410 and b.money_in > 0 and bool(raw.sales)
                 and not _names_director(b.description, surnames))
        if b.head_given and given is not None and not matched and not doubt:
            # The head the accountant already wrote on the statement, over the firm's rules (never over a line
            # matched to one of the client's invoices or bills)
            s = SortedLine(b, b.head_given, given, "head on the statement", True)
        elif b.money_in > 0 and not matched and OPENING_MONEY.match(b.description):
            s = SortedLine(b, DIRECTOR, HEAD_CODES[DIRECTOR], "money in the account before the company was formed: "
                           "the director's (pre-incorporation)", False) if first_period else                 SortedLine(b, UNSORTED, HEAD_CODES[UNSORTED], "an opening balance adjustment, not a sale: check it "
                           "against last year's closing bank balance", False)
        elif takings and b.money_in > 0 and s.head == CUSTOMER:
            s = SortedLine(b, "Sales (no invoice)", HEAD_CODES["Sales (no invoice)"],
                           "no sales invoices kept: money in taken as takings (sales)", True)
        if industry == "PRP" and not industry_from and not matched and _property_money(s):
            s = SortedLine(b, UNSORTED, HEAD_CODES[UNSORTED], PROPERTY_HOW + (f" (the statement says {s.head})"
                                                                              if s.head != UNSORTED else ""), False)
        result.lines.append(s)
    _refunds(raw, result)
    _unknown_accounts(raw, result)
    _card_money_in(raw, result)
    # A loan repayment reduces the loan last year's TB holds, when it holds one (e.g. 5500 bank loan)
    loans = [c for c in (5100, 5110, 5500, 5510) if abs(raw.last_year_tb.get(c, 0.0)) >= 0.005]
    if len(loans) == 1:
        for s in result.lines:
            if s.head == "Loan repayment":
                s.code = loans[0]
    # Pension contributions reduce the pension owed on last year's code (5352 or 5351), else 5352 Pension payable
    pension = next((c for c in (5352, 5351) if abs(raw.last_year_tb.get(c, 0.0)) >= 0.005), None)
    if pension:
        for s in result.lines:
            if s.head == "Pension paid":
                s.code = pension
    return result
