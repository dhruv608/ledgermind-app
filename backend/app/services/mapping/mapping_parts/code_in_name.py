"""For balance sheet accounts, the firm code at the start of a client account's name wins ('4804 - Shopify Holding'
goes to 4804 if 4804 is in the chart).

A client whose chart follows the firm's codes names its accounts '5352 - Capital on Tap', '5320 - Net wages',
'4804 - VAT'. The words may point to another firm account (a credit card read as a bank, 'Net wages' as 5330), but the
accountant keeps the code in the name. Fixed assets (4000-4199, where cost / additions / depreciation names and codes
are often mixed) and the P&L keep the normal rules; last year's code and an accountant's confirmation still come
first."""

import re
from typing import Any, Dict, Optional

from backend.app.models.database import MasterCOA
from backend.app.services.mapping.mapping_parts.rules import RuleMapping

FIRST_CODE = 4200            # balance sheet codes after the fixed assets
DIRECTORS_LOAN = {5400, 5401, 5402, 5800}
LENDER_LOANS = {5100, 5110, 5500, 5510}       # bank and other loans (within and after one year)
DIRECTOR_WORDS = re.compile(r"\b(?:director|directors|dla|personal|drawings?|owner|shareholder)\b", re.I)
# Words that make the account income, whatever the code before them ('4400 - Rental and other income from property'
# is P&L rent income, not trade debtors 4400)
INCOME_WORDS = re.compile(r"\b(income|sales|revenue|turnover|takings)\b", re.I)


def _named_as(name: str, coa_by_code: Dict[int, MasterCOA]) -> Optional[int]:
    """The firm code the first naming rule gives the account's words (the code in front left out), if any."""
    from backend.app.services.mapping.mapping_parts.common import STATUTORY_SYNONYM_RULES
    words = re.sub(r"^\s*\d+(?:\.\d+)?\s*[-:]?\s*", "", (name or "").lower())
    for pattern, rule_code in STATUTORY_SYNONYM_RULES:
        if rule_code in coa_by_code and re.search(pattern, words, flags=re.IGNORECASE):
            return rule_code
    return None


def code_in_name(name: str, coa_by_code: Dict[int, MasterCOA], trusted: bool,
                 account_type: Optional[str]) -> Optional[Dict[str, Any]]:
    """The mapping for an account named with a balance sheet firm code, for a client that uses the firm's codes."""
    if not trusted or INCOME_WORDS.search(name):
        return None
    code = RuleMapping._client_code(name)
    if code is None or code < FIRST_CODE or code not in coa_by_code:
        return None
    coa = coa_by_code[code]
    if coa.financial_class == "Profit and Loss" or not RuleMapping._class_matches(account_type, coa):
        return None
    # A director's loan code used by the client for another lender ('5401 Lloyds Bank Loan': 5401 is a director's
    # loan in the firm chart, the words say a bank loan): the naming rules decide, for review, not the number. This
    # applies only to the director's loan, because it brings s455 and benefit in kind; other balance sheet codes in
    # the name are kept. Personal items posted to the director's loan under their own name stay on it
    # ('5400 - Repairs & Maintenance', '5400 - Barclaycard (Personal Expenses) DLA').
    if code in DIRECTORS_LOAN and not DIRECTOR_WORDS.search(name):
        other = _named_as(name, coa_by_code)
        if other is not None and other not in DIRECTORS_LOAN and other in LENDER_LOANS:
            return None
    return {"std_code": code, "std_name": coa.std_name, "mapping_status": "MATCHED", "confidence_score": 0.97,
            "match_source": "CLIENT_FIRM_CODE",
            "mapping_reason": f"The account name starts with the firm code {code:04d} and the client uses the firm's "
                              f"codes: the code is kept ({coa.std_name})."}


# A chart written '<firm code> - <client code> - <name>' ('1440 - 450 - Subcontractor', '3280 - 3280 - Advertising')
DOUBLE_CODED = re.compile(r"^\d{1,4}\s+-\s+\d{3,4}(?:-\d+)?\s+-\s+\S")
ZERO_FIRST = re.compile(r"^0\s+-\s+\d{3,4}(?:-\d+)?\s+-\s+\S")
DOUBLE_CODED_MIN = 5          # accounts written that way before the chart is taken to be double coded


def double_coded(names) -> bool:
    """The client's TB names carry the firm's code before its own on most of its coded accounts."""
    names = list(names)
    coded = [n for n in names if re.match(r"^\d", n or "")]
    double = [n for n in coded if DOUBLE_CODED.match(n) and not ZERO_FIRST.match(n)]
    return len(double) >= DOUBLE_CODED_MIN and len(double) >= 0.4 * len(coded)


def zero_is_sales(name: str, net: float, coa_by_code: Dict[int, MasterCOA], double: bool) -> Optional[Dict[str, Any]]:
    """In a double-coded chart a leading '0 - ' is the firm's Sales code 0, not a blank placeholder ('0 - 201 -
    Casting' is Sales, though its words suggest subcontractors). Only for an income balance (a credit): a debit under
    '0 - ' is left to the other rules."""
    if not double or 0 not in coa_by_code or net >= 0 or not ZERO_FIRST.match(name or ""):
        return None
    coa = coa_by_code[0]
    return {"std_code": 0, "std_name": coa.std_name, "mapping_status": "MATCHED", "confidence_score": 0.95,
            "match_source": "CLIENT_FIRM_CODE",
            "mapping_reason": "The client writes the firm code before its own on its accounts; '0 - ' is the firm's "
                              "Sales code and the balance is income."}

