"""Codes, patterns, the statutory synonym rules and name helpers the mapping parts share."""

import re


AI_BATCH_SIZE = 10

AI_PARALLEL_CALLS = 6

AI_AUTO_ACCEPT_CONFIDENCE = 0.90

SUSPENSE_CODE = 9999

DIVIDEND_CODES = (8010, 8011)     # final and interim dividends paid

# A client whose coded accounts mostly agree with the firm chart (by code and name) is using the firm's codes.
# Measured: Xero-numbered clients 0%, firm-coded clients 52-80%.
FIRM_CODES_MIN_SHARE = 0.40

FIRM_CODES_MIN_ACCOUNTS = 5

CLIENT_CODE_RE = re.compile(r"^(\d{3,4})(?:-\d+)?[\s\-_:]")

# Some exports put '0 - ' before every account as a blank placeholder ('0 - Savings by FRS', '0 - Discount allowed'):
# the code is the one after it ('0 - 0000 - Sales' is 0000 Sales), and with none after it there is no code
PLACEHOLDER_PREFIX_RE = re.compile(r"^0\s+-\s+(?=\d{3,4}\b)")

# A one or two digit firm code before a name ('0 - Retainer fees': 0 Sales), read only for a client on the firm's codes
# (otherwise the AI may split such accounts between income and deferred income)
SHORT_CODE_RE = re.compile(r"^(\d{1,2})\s+-\s+(?=\D)")

NAME_FILLER_WORDS = {"and", "of", "the", "account", "accounts", "cost", "costs"}

# Fixed asset roll-forward at the start of a year (firm chart groups of ten, e.g. 4120-4129 plant and equipment)
FIXED_ASSET_CODES = (4000, 4199)

IN_YEAR_DEPRECIATION = re.compile(r"(depreciation|amortisation)\s+(charge|on\b)|impairment|reversal", re.IGNORECASE)

IN_YEAR_COST = re.compile(r"additions|disposals|revaluations", re.IGNORECASE)

BROUGHT_FORWARD = re.compile(r"b/\s*fwd", re.IGNORECASE)

# Account types reported by client software (Xero) and the class they must map to
PL_ACCOUNT_TYPES = {"revenue", "sales", "other income", "direct costs", "cost of sales", "expense", "expenses", "overhead", "overheads", "depreciation"}

BS_ACCOUNT_TYPES = {"current asset", "fixed asset", "non-current asset", "bank", "inventory", "prepayment", "current liability", "liability", "non-current liability", "equity", "accounts receivable", "accounts payable", "credit card"}

# Firm chart sections the AI may choose from, by the account type in the client's software (Xero / QuickBooks).
# Types not listed (or missing) get the whole standard chart. Suspense is always offered.
_INCOME = {"Other operating income", "Income from shares in group undertakings", "Income from participating interests",
           "Income from other fixed asset investments", "Income from other current asset investments",
           "Interest receivable and similar income"}

_COSTS = {"Cost of sales", "Distribution costs", "Employee costs", "Premises expenses", "General admin", "Depreciation",
          "Other operating and exceptional costs", "Interest payable and similar charges", "Current tax", "Deferred tax"}

_CURRENT_ASSETS = {"Stock", "Debtors < 1 year", "Debtors > 1 year", "Current assets - investments",
                   "Cash at bank and in hand", "Prepayments and accrued income"}

_CURRENT_LIABILITIES = {"Current liabilities - creditors < 1 year", "Hire purchase and Finance Leases", "Provisions and liabilities"}

_SECTION_GROUPS = {
    ("revenue", "sales", "income"): {"Sales", "Other operating income"},
    ("other income",): _INCOME,
    ("direct costs", "cost of sales", "cost of goods sold"): {"Cost of sales", "Distribution costs", "Employee costs"},
    ("expense", "expenses", "overhead", "overheads", "other expense", "other expenses"): _COSTS,
    ("depreciation",): {"Depreciation"},
    ("fixed asset", "fixed assets", "non-current asset", "non current asset"): {"Intangible assets", "Tangible assets", "Investments"},
    ("current asset", "current assets", "inventory", "prepayment", "accounts receivable", "accounts receivable (a/r)"): _CURRENT_ASSETS,
    ("bank", "credit card"): {"Cash at bank and in hand", "Current liabilities - creditors < 1 year"},
    ("current liability", "current liabilities", "accounts payable", "accounts payable (a/p)"): _CURRENT_LIABILITIES,
    ("liability", "non-current liability", "non current liability", "long term liabilities"):
        _CURRENT_LIABILITIES | {"Long term liabilities - creditors > 1 year"},
    ("equity",): {"Share capital", "Share premium account", "Revaluation reserve", "Capital redemption reserve", "Profit and loss account"},
}

SECTIONS_BY_ACCOUNT_TYPE = {t: frozenset(sections) for types, sections in _SECTION_GROUPS.items() for t in types}

# The firm's usual code where the chart has several close ones (Christmas party, software, travel...) is data, edited
# on the Account rules page (firm_rules.py).

# Deterministic UK Standard Chart of Accounts Mapping Rules (Master 555 TaxCalc/Audit COA)
STATUTORY_SYNONYM_RULES = [
    # Bank & Cash
    (r"^(?!.*\b(loans?|overdrafts?|liabilit\w*|interest|charges?|fees?)\b).*bank.*current", 4800),
    (r"bank.*deposit", 4810),
    (r"(petty cash|cash in hand|cash at bank)", 4830),

    # Credit cards and online banks are bank accounts in the firm's 4800 series, one code per account; their fee /
    # interest accounts are not
    (r"^(?!.*\b(fees?|charges?|interest|cashback)\b).*(credit\s*card|c/card|barclaycard|\bamex\b|american express|mastercard|visa card|capital on tap)", 4800),
    (r"^(?!.*\b(fees?|charges?|interest)\b).*\b(revolut|monzo|wise|transferwise|starling|tide)\b", 4800),

    # Tax paid abroad (e.g. Japanese taxes) is foreign tax (3821), not UK corporation tax; the balance sheet account
    # for it stays a creditor
    (r"^(?!.*(\(bs\)|\b(payable|liabilit\w*|creditors?|owed)\b)).*\b(foreign|overseas|japanese|withholding)\s+tax(es)?\b", 3821),

    # Sales & Income
    (r"^(sales|turnover|revenue|income from contracts|amazon sales|shop takings|takings|other income|online sales)$", 0),
    (r"^(consulting|consultancy income|fee income|services income)$", 440),
    (r"^(interest income|bank interest receivable|deposit interest)$", 900),
    (r"^(realised currency gains|unrealised currency gains|exchange gains)$", 550),
    (r"\b(forex|fx|exchange|currency)\b.*\bgains?\b.*\bloss(es)?\b", 3562),  # 'Exchange Gain or Loss', 'Forex Gain/Loss'

    # Cost of Sales & Stock
    (r"^(cost of sales|direct costs|materials|purchases|goods for resale)$", 1100),
    # CIS: the tax accounts, then CIS labour income and expense, before the general subcontractor rule
    (r"\bcis\b.*\b(asset|suffered|withheld|receivable|recoverable|reclaim\w*)\b|\b(suffered|withheld)\b.*\bcis\b", 4421),
    (r"\bcis\b.*\b(liabilit\w*|payable|deductions?|creditors?)\b", 5321),
    (r"\bcis\b.*\b(expenses?|costs?|subcontract\w*)\b|^subcontract\w*\s*\(cis\)", 1440),
    (r"\bcis\b.*\b(income|sales|turnover)\b|^(labour|sales)\s*[-(]\s*cis\b", 0),
    (r"\bsub[\s-]?contract", 1440),  # the firm uses Cost of sales 1440, not Employee costs 3020
    (r"^(opening stock|opening stock and work in progress)$", 1000),
    (r"^(closing stock|closing stock - materials)$", 1910),
    (r"^(work in progress movement|wip movement)$", 1020),
    (r"^(direct expenses|direct wages|production wages)$", 1500),

    # Balance Sheet - Stock / Inventory
    (r"^(stocks:finished|stock - finished goods)$", 4302),
    (r"^(stocks?|stock - materials|raw materials|stock.*wip)$", 4300),

    # Fixed Assets (Cost & Depreciation). Computer equipment first: 'Computer equipment cost brought forward' is
    # computers (4150), not the plant and equipment the word 'equipment' would give
    (r"computer.*cost.*add", 4151),
    (r"computer.*cost.*\b(b/?f|b/?fwd|brought)", 4150),
    (r"computer.*dep\w*.*(charge|for the year|this year)", 4154),
    (r"computer.*(dep\w*|accumulated).*\b(b/?f|b/?fwd|brought)", 4153),
    (r"equipment.*cost.*add", 4121),
    (r"equipment.*cost.*b", 4120),
    (r"equipment.*depn.*charge", 4124),
    (r"equipment.*depn.*b", 4123),
    (r"leasehold.*cost.*add", 4111),
    (r"leasehold.*cost.*b", 4110),
    (r"leasehold.*depn.*b", 4114),
    (r"^investment properties$", 4160),
    (r"^(motor vehicles|motor vehicle cost|company cars)$", 4130),
    (r"^(computer equipment|computers & it hardware|it equipment)$", 4150),
    (r"^(fixtures and fittings|furniture & fittings|office equipment)$", 4140),
    (r"^(plant and machinery|equipment)$", 4120),

    # Debtors & Current Assets (< 1 yr & > 1 yr)
    (r"^(accounts receivable|trade debtors|debtors control account|debtors)$", 4400),
    # A debtors / creditors ledger per currency ('Debtors - EUR', 'Creditors (USD)') is still trade debtors / creditors
    (r"^(trade\s+)?(debtors?|accounts receivable)\s*[-–:(]\s*(eur|usd|jpy|gbp|aud|cad|chf|sek|nok|dkk|cny|hkd|sgd|euro|dollars?|yen)\b", 4400),
    (r"^(prepayments?|prepaid expenses?|debtors:prepayments)$", 4900),

    # Current Liabilities (< 1 yr)
    (r"^(accounts payable|trade creditors|creditors control account|creditors)$", 5200),
    (r"^(trade\s+)?(creditors?|accounts payable)\s*[-–:(]\s*(eur|usd|jpy|gbp|aud|cad|chf|sek|nok|dkk|cny|hkd|sgd|euro|dollars?|yen)\b", 5200),
    (r"^(accruals?|accrued expenses?|accruals and deferred income|creditors:accruals)$", 5360),
    (r"^(corporation tax|corporation tax payable|ct liability|creditors:corporation tax)$", 5310),
    (r"^(vat|vat control|vat liability|hmrc vat|vat control account|net vat.*|vat - input|vat - output|vat suspense)$", 5300),
    (r"^(paye|paye and ni|paye/nic payable|paye liability|hmrc paye|creditors:paye.*)$", 5320),
    (r"^(net wages|wages payable|net wages payable|creditors:net wages)$", 5330),
    # A wages / salaries control or payable account is the net wages owed, not the cost
    (r"^((wages|salar(y|ies))( and (wages|salar(y|ies)))? (control|payable)( account)?|net pay( payable)?)$", 5330),
    # A pension payable / creditor account is the pension owed (5352 Pension Payable), not the cost
    (r"^(pensions? (payable|creditors?|liabilit(y|ies)|control)( account)?|nest( pension)? payable)$", 5352),
    # The firm puts director's loan, DLA, director's current / capital account, capital introduced and drawings all on
    # one code; share capital keeps its own code (7000)
    (r"^(director.*current|director.*loan.*|creditors:director.*)$", 5400),
    (r"^(?!.*\b(interest|supplies|office|fees?|charges?)\b).*(director'?s?'?\s*(loan|current|capital)|\bdla\b|\bdrawings?\b|personal\s+(loan|current)\s+account|capital introduced|owner'?s?'?\s*(capital|drawings?))", 5400),
    (r"^(nest|other creditors)$", 5350),
    (r"^bank loans?\s*<", 5100),
    # A loan named after its lender ('Lloyds Bank Loan - 804201', 'Funding Circle Loan-short term'): a bank loan,
    # short term when the name says so (not a director's or group loan; not the interest on it)
    (r"^(?!.*\b(interest|fees?|charges?|director|dla|intercompany|group|to|debtors?|receivable)\b)(?=.*\b(bank|lloyds|barclays|hsbc|natwest|santander|san uk|nationwide|metro|starling|tide|funding circle|iwoca|esme|bounce back|recovery loan|cbils|youlend|liberis|aldermore|allica|shawbrook|fleximize|bus(?:iness)?|term|commercial)\b)(?=.*\bloans?\b).*(short[\s-]*term|current|< ?1)", 5100),
    (r"^(?!.*\b(interest|fees?|charges?|director|dla|intercompany|group|to|debtors?|receivable)\b)(?=.*\b(bank|lloyds|barclays|hsbc|natwest|santander|san uk|nationwide|metro|starling|tide|funding circle|iwoca|esme|bounce back|recovery loan|cbils|youlend|liberis|aldermore|allica|shawbrook|fleximize|bus(?:iness)?|term|commercial)\b).*\bloans?\b", 5500),

    # Long Term Liabilities (> 1 yr)
    (r"^bank loans?\s*>", 5500),

    # Directors' pension (defined contribution) in employee costs; plant / equipment hire
    (r"^(?!.*\b(payable|liabilit\w*|creditor|owed)\b).*director'?s?'?\s+pensions?(?!.*\bdefined\s+benefit)", 3012),
    (r"^(?!.*\b(income|sales|revenue|recharged?)\b).*(\b(equipment|plant|machinery|tools?)\s+hire\b|\bhire of (plant|equipment|machinery|tools?))", 3205),
    (r"^(bounce back loan|bbls loan|long term loans?)$", 5500),

    # Equity & Capital
    (r"^(ordinary shares|called up share capital|share capital|share capital.*brought forward)$", 7000),
    (r"^(share premium|shares issued|share capital.*issued)$", 7110),
    (r"^(retained earnings|profit and loss account|retained profit|profit and loss.*brought forward)$", 8000),
    # Dividends paid to shareholders: the firm uses 8011 Interim dividend paid
    (r"^(dividends? paid|interim dividends?|dividends?|profit and loss account:equity dividends)$", 8011),

    # Staff Costs & Payroll
    # QuickBooks' payroll accounts: 'Payroll Expenses' (and its ':Wages', ':Taxes', ':Pension') are costs, not net
    # wages owed; 'Payroll Liabilities' (':HMRC', ':PAYE') is what is owed to HMRC
    (r"^payroll expenses?\s*:\s*(taxes|employer'?s? (ni|nic|national insurance)|ers? ni|ni|nic|national insurance)$", 3001),
    (r"^payroll expenses?\s*:\s*(pensions?|employer'?s? pensions?|nest)$", 3002),
    (r"^payroll expenses?(\s*:\s*(wages|salar(y|ies)|gross pay|staff wages))?$", 3000),
    (r"^payroll liabilit(y|ies)\s*:\s*(pensions?|nest)$", 5352),
    (r"^payroll liabilit(y|ies)\s*:\s*(net (wages|pay)|wages)$", 5330),
    (r"^payroll liabilit(y|ies)(\s*:\s*(hmrc|paye|taxes|ni|nic|paye.*))?$", 5320),
    (r"^(salaries|wages|staff salaries|gross wages|payroll|wages and salaries|expenses:wages.*)$", 3000),
    (r"^(directors? salaries|directors? remuneration|expenses:directors.*)$", 3010),
    (r"^(employer'?s national insurance|employer ni|ers ni|expenses:employers ni)$", 3001),
    (r"^(employers nest|employers pension.*)$", 3002),
    (r"^(pensions costs|pension expense|auto enrolment)$", 3002),

    # Premises & Admin Expenses
    (r"^(rent|property rent|office rent|rent and rates)$", 3100),
    (r"^(rates|business rates|water rates|expenses:rates)$", 3110),
    (r"^(light & heat|light and heat|electricity|gas|utilities|expenses:light.*)$", 3130),
    (r"^(repairs & maintenance|repairs and maintenance|repairs and renewals|expenses:repairs.*)$", 3140),
    (r"^(cleaning|waste disposal|cleaning and hygiene|expenses:cleaning)$", 3150),
    (r"^(advertising & marketing|advertising and pr|marketing|advertising|promotions|expenses:advertising.*)$", 3280),
    (r"^(telephone & internet|telephone and fax|telecommunications|broadband|mobile phone|expenses:telephone.*)$", 3290),
    (r"^(motor vehicle expenses|vehicle running costs|motor expenses|expenses:motor.*)$", 3230),
    (r"^(insurance|general insurance|public liability|expenses:insurance)$", 3260),
    (r"^(general expenses|sundry expenses|miscellaneous|other expenses)$", 3590),
    (r"^(bank fees|bank charges|merchant fees|stripe fees|paypal fees|expenses:bank charges)$", 3351),

    # Professional Fees
    (r"^(accountancy fees|accountancy|accountant fees|expenses:accountancy.*)$", 3301),
    (r"^(audit fees|statutory audit)$", 3300),
    # Legal, or legal and professional mixed: 3302; professional fees alone: 3303
    (r"^(legal & professional.*|legal and professional.*|legal fees|other legal and prof.*|expenses:other legal.*)$", 3302),
    (r"^professional fees$", 3303),

    # Depreciation
    (r"^(depreciation expense|depreciation|expenses:depreciation)$", 3400),

    # Finance Charges & Interest
    (r"^(interest - bank|bank loan interest|loan interest|expenses:interest - bank)$", 3615),
    (r"^(interest - other|late payment charges|tax charges|expenses:interest - other)$", 3670),
]

BROUGHT_FORWARD_RE = re.compile(r"\bb\s*/\s*f(?:wd|d)?\b|\bbfwd\b|\bbrought\s+forward\b|\bb\.\s*f\.?")

def same_words(text: str) -> frozenset:
    """An account name's words for an exact match however it is written: no note in brackets, '&' as 'and', every
    spelling of brought forward as one word, plurals as singular (name_words)."""
    text = re.sub(r"\s*\(.*?(\)|$)", " ", (text or "").lower())
    text = BROUGHT_FORWARD_RE.sub(" bfwd ", text.replace("&", " and "))
    return frozenset(name_words(text))

def name_words(text: str) -> set:
    """The words of an account name in a simple singular form, so 'Prepayment' agrees with 'Prepayments',
    'Taxes' with 'Tax' and 'Companies' with 'Company'."""
    words = set()
    for w in re.findall(r"[a-z]+", (text or "").lower()):
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 4 and w.endswith(("ses", "xes", "ches", "shes")):
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        words.add(w)
    return words

def account_key(raw_name: str) -> str:
    """A client account name for matching across uploads: lower case, single spaces."""
    return re.sub(r"\s+", " ", (raw_name or "").strip().lower())

# Bank codes in the firm chart: current 4800-4809, deposit 4810-4819, reserve 4820-4829 (4830 is cash in hand)
BANK_CODES = (4800, 4829)

CARD_CODES = {5351}             # credit card: a card account the mapping took for a bank

# A name that reads as a bank account: a masked or plain account number ('XXXX3248 (3248)'), bank, current account
BANK_LIKE = re.compile(r"[x*]{2,}\s*\d{3,}|\b\d{4,}\b|\bbank\b|current account|savings", re.I)

MOVABLE_SOURCES = {"AI", "RULE", "COA_NAME", "PARENT"}

# Codes the wrong-side check looks at (it only sends them to review, never changes them): also a code remembered from
# another client, or a firm account rule, which can fit one client and not this one; and last year's code, which may
# have been confirmed wrongly once and would otherwise be carried every year
FLAGGED_SOURCES = MOVABLE_SOURCES | {"MEMORY", "FIRM_DEFAULT", "FIRM_HABIT", "LAST_YEAR"}

# Names too general to take another client's code as settled ('Loan' is a director's loan on one client, a bank loan
# on the next): the remembered code is suggested, for the accountant to check
GENERAL_NAMES = {
    "loan", "loans", "other", "others", "sundry", "sundries", "misc", "miscellaneous", "general", "transfer",
    "transfers", "adjustment", "adjustments", "deposit", "deposits", "payment", "payments", "receipt", "receipts",
    "expenses", "costs", "fees", "charges", "income", "other income", "other expenses", "other costs",
    "general expenses", "sundry expenses", "account", "current account", "director", "directors", "drawings",
    "clearing", "control", "holding", "accrual", "accruals", "provision", "provisions", "reserve", "interest",
}

# Wrong-side check: names and balances that contradict the chosen code
DEBTOR_NAME = re.compile(r"\b(debtors?|receivables?)\b")

CREDITOR_NAME = re.compile(r"\b(creditors?|payables?)\b")

DEBTOR_SECTIONS = {"Debtors < 1 year", "Debtors > 1 year"}

CREDITOR_SECTIONS = {"Current liabilities - creditors < 1 year", "Long term liabilities - creditors > 1 year"}

INCOME_SECTIONS = {"Sales", "Other operating income", "Income from shares in group undertakings",
                   "Income from participating interests", "Income from other fixed asset investments",
                   "Income from other current asset investments", "Interest receivable and similar income"}

WRONG_SIDE_MIN_BALANCE = 1.0

# Income by its name ('Rent in', 'Deposits in', 'Bank interest received', 'Commission income', 'Just Eat Sales'); a
# control or tax account named after sales is not, nor a work in progress or stock adjustment
INCOME_NAME = re.compile(r"(\bincome\b|\breceived\b|\breceipts?\b|\bturnover\b|\brevenue\b|\bcommissions?\b|\bsales\b|"
                         r"\btakings\b|\bin$)")

NOT_INCOME_NAME = re.compile(r"cost of|purchase|\btax\b|\bvat\b|control|ledger|debtor|creditor|receivable|payable|"
                             r"deferred|in advance|suspense|clearing|\bloan\b|\bwip\b|work in progress|\bstock\b")

EXPENSE_CREDIT_MIN = 1000.0     # an expense code more in credit than this is asked about

# Expenses that are normally in credit: closing stock, discounts and rebates received, recoveries, gains
CREDIT_EXPENSE_NAME = re.compile(r"closing stock|closing work in progress|\bwip\b|discount|rebate|recover|grant|refund|reimburs|\bgains?\b|profit on|"
                                 r"\bcontra\b|credit note|recharge|allowance")     # not 'subcontractor'

NOT_EXPENSE_SECTIONS = INCOME_SECTIONS | {"Current tax", "Deferred tax", "Suspense and misposting"}

BANK_NUMBER_NAME = re.compile(r"^[\d\s\-/]{8,}$")    # an account named only by a bank account number

# Words that say an account named after the company is something else than its bank account
NOT_BANK_WORDS = re.compile(r"\b(loans?|director|directors|dla|capital|shares?|dividend|vat|paye|tax|payable|"
                            r"receivable|debtors?|creditors?|liabilit|interest|charges?|fees?|card|hp|lease|wages?)\b")

FIXED_ASSET_SECTIONS = {"Tangible assets", "Intangible assets"}

ASSET_PURCHASE_NAME = re.compile(r"\b(purchases?|additions?|bought)\b")

ASSET_FINANCE_NAME = re.compile(r"financ|\bloans?\b|hire purchase|\bhp\b|\blease\b|\bleasing\b")  # not 'leasehold'

# Firm chart placeholders with no meaning of their own ('Purchases Type D', 'Sales type A')
PLACEHOLDER_ACCOUNT = re.compile(r"\btype [a-z]\b")

# Parent accounts that are only a general heading: their sub-accounts are mapped on their own name
GENERAL_PARENT_HEADINGS = {
    "expenses", "expense", "other expenses", "overheads", "income", "other income", "revenue", "cost of sales",
    "cost of goods sold", "direct costs", "assets", "current assets", "fixed assets", "liabilities",
    "current liabilities", "long term liabilities", "equity", "creditors", "debtors", "bank",
}
