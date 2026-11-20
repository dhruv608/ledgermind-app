"""The headings a bank line can go under outside the business, and the words and limits the sorting rules use."""

import re
from typing import Dict, Optional


DRAWINGS, CAPITAL, TRANSFER, NOT_TRADE, LOAN, UNSORTED = "DRAWINGS", "CAPITAL", "TRANSFER", "NOT_TRADE", "LOAN", "UNSORTED"
# The other 'Record as' choices for money in and money out
LOAN_IN, VAT, ASSET, TAX, ASK = "LOAN_IN", "VAT", "ASSET", "TAX", "ASK"
OUTSIDE = {
    DRAWINGS: "Drawings (not a cost)", CAPITAL: "Capital introduced (not income)", TRANSFER: "Own accounts transfer",
    NOT_TRADE: "Not the trade's income", LOAN: "Loan or HP repaid (capital)",
    LOAN_IN: "Loan received (not income)", VAT: "VAT paid or refunded (not income or a cost)",
    ASSET: "Capital asset (capital allowances, not a cost)", TAX: "Tax and NI paid (personal: drawings)",
    ASK: "Ask the client", UNSORTED: "Not sorted yet",
}
FROM_BANK = "From the bank statements"

# The firm's bank heads (bank_sort.HEAD_CODES) under the SA103 headings, or out of the business
SA_HEADS: Dict[str, str] = {
    "Customer receipt": "TURNOVER", "Sales (card takings)": "TURNOVER", "Sales (no invoice)": "TURNOVER",
    "Supplier bill paid": "COST_OF_SALES", "Purchases (no bill)": "COST_OF_SALES",
    "Vehicle running costs": "TRAVEL", "Travel and subsistence": "TRAVEL", "Vehicle hire": "TRAVEL",
    "Insurance": "PREMISES", "Light and heat": "PREMISES", "Water rates": "PREMISES", "Rates": "PREMISES",
    "Repairs and maintenance": "REPAIRS",
    "Telephone and internet": "OFFICE", "Computer software": "OFFICE", "Postage": "OFFICE", "Courier": "OFFICE",
    "Advertising": "ADVERTISING",
    "Bank charges": "FINANCE", "Card charges": "FINANCE",
    "Accountancy fees": "PROFESSIONAL", "Legal fees": "PROFESSIONAL",
    "Subscriptions": "OTHER", "Filing fees": "OTHER", "Security": "OTHER",
    "Net wages": "STAFF",
    "Director's loan": DRAWINGS, "Personal (director's loan)": DRAWINGS, "Cash withdrawn": DRAWINGS,
    "Donations": DRAWINGS, "Pension paid": DRAWINGS, "HMRC (check which tax)": DRAWINGS,
    "Corporation tax paid": DRAWINGS, "PAYE and NI paid": UNSORTED, "VAT paid": VAT,
    "Transfer between own accounts": TRANSFER,
    "Bank interest received": NOT_TRADE,
    "Loan repayment": LOAN, "Vehicle finance (HP)": LOAN,
    "Refund received": UNSORTED, "Ask the client": ASK, "Unsorted": UNSORTED,
}
# Heads a rule gives that the accountant should still look at for a sole trader
DRAWINGS_WORD = re.compile(r"\bdrawings?\b", re.I)
# Money in on a person's own account that is not the trade's: benefits, pensions, wages, refunds (the person's own
# account is often their business account too; the company rule 'no sales invoices: money in is sales' is not safe)
# Personal-looking payees: supermarkets, clothes, gyms, streaming, holidays, leisure.
# Sorted as a business cost (by the AI or a choice) and regular, they are a point to confirm, never moved by themselves
PERSONAL_PAYEE = re.compile(r"\basda\b|\btesco\b|\baldi\b|\blidl\b|sainsbury|morrisons|waitrose|\bco-?op\b|\biceland\b|"
                            r"primark|\bzara\b|\bh ?& ?m\b|\basos\b|next retail|\bm ?& ?s\b|marks (and|&) spencer|"
                            r"\bgym\b|puregym|the gym group|david lloyd|nuffield health|virgin active|anytime fitness|"
                            r"netflix|spotify|disney ?plus|\bdisney\+|apple\.com/bill|amazon prime|prime video|now tv|"
                            r"\bsky\b(?! ?bet)|deliveroo|just ?eat|uber ?eats|\btui\b|jet2|easyjet holidays|"
                            r"booking\.com|airbnb|cinema|odeon|cineworld|\bvue\b", re.I)
PERSONAL_REGULAR = 3            # lines a year from one payee before it is 'regular'
# Costs used partly for personal life: kind -> (label, heading, the bank words)
MIXED = {
    "PHONE": ("Phone and broadband", "OFFICE",
              re.compile(r"vodafone|\bo2\b|\bee\b|\bthree\b|giffgaff|tesco mobile|\bbt\b|broadband|virgin media|\bsky\b"
                         r"(?! ?bet)|talktalk|plusnet|smarty|lebara|lycamobile|\bid mobile\b|mobile", re.I)),
    "VEHICLE": ("Car or van running costs", "TRAVEL",
                re.compile(r"\bfuel\b|petrol|diesel|\bshell\b|\besso\b|\btexaco\b|\bbp\b|\bpfs\b|pay ?at ?pump|\bgarage\b|"
                           r"\bmot\b|\btyres?\b|kwik fit|halfords|service station|filling station|car insurance|"
                           r"motor insurance|\bdvla\b|vehicle tax", re.I)),
}
# A VAT repayment from HMRC ('HMRC VAT REPAYMENT'); a loan paid in ('FUNDING CIRCLE LOAN ADVANCE', 'IWOCA DRAWDOWN')
VAT_IN = re.compile(r"\bhmrc\b.*\bvat\b|\bvat\b.*\bhmrc\b|\bvat (repayment|refund)\b", re.I)
LOAN_ADVANCE = re.compile(r"\bloan (advance|drawdown|payout|funds?)\b|\bfunding circle\b|\biwoca\b|\bbounce ?back\b|"
                          r"\bcbils\b|\bdrawdown\b.*\bloan\b|\bloan\b.*\bdrawdown\b", re.I)
NOT_TRADE_IN = re.compile(r"\bDWP\b|\bHMRC\b|universal credit|child benefit|carer'?s? allowance|\bpension|\bcouncil\b|"
                          r"county fund|\bsalary\b|\bwages?\b|\bpayroll\b|\bpay ?roll\b|\brefund\b|\bcashback\b|"
                          r"\bSLC\b|student loans? company|student finance", re.I)
# An investment or pension account's statement (its value going up and down): not a bank account the trade uses. A
# change in value is not income (a gain is taxed only on a sale, as a capital gain), so none of its lines are the trade's
INVESTMENT_VALUE = re.compile(r"change in (investment|market|portfolio|fund) value|unreali[sz]ed (gain|loss)", re.I)
# Mortgage money paid in (an advance, a further advance, the surplus after a redemption or sale): a loan or capital
MORTGAGE_IN = re.compile(r"\bmortgage\b|\bmtg\b|\bremortgage\b|\bfurther advance\b", re.I)
# Platforms that pay a seller's takings over (their fees are costs; what they pay in is sales)
PAYOUT_PLATFORMS = {"ebay", "etsy", "amazon", "paypal", "stripe", "sumup", "zettle", "izettle", "square", "shopify",
                    "worldpay", "dojo", "teya", "vinted", "depop", "takepayments", "gocardless",
                    # gig work: what the app pays a driver or courier is their takings
                    "uber", "deliveroo", "bolt", "justeat", "stuart", "gophr"}
# A selling platform's own payout of the seller's balance to their bank, as its report prints it
PLATFORM_PAYOUT = re.compile(r"\bpayouts?\b|transfer to (your )?bank|withdraw(al)? to (your )?bank|bank (deposit|withdrawal)", re.I)
# Money the person puts into a platform account from their own card or bank (PayPal's 'General Credit Card Deposit')
PLATFORM_FUNDING = re.compile(r"credit card deposit|debit card deposit|electronic funds transfer|\bfunds? transfer\b|"
                              r"deposits? and credits|\btop ?up\b|added money|add money", re.I)
# A card statement's summary of the month ('New transactions, fees and charges', 'Previous balance'): the total of
# lines it lists, not a payment itself
CARD_SUMMARY = re.compile(r"^\W*(new transactions(,? fees,? and charges)?|payments and credits|your new activity|previous balance"
                          r"|new balance|total new (spend|transactions)|balance from (your )?last statement|opening balance"
                          r"|closing balance)\W*$", re.I)
# Paying off a credit card from the bank ('Direct Debit to Aqua Credit Card'): the person's own money moved; the card's
# own purchases are the costs (its fees and interest stay costs)
PAY_CARD_OFF = re.compile(r"\bcredit ?card\b|\bbarclaycard\b|\bamex\b|american exp|\bmbna\b|\bcapital one\b|\bvanquis\b|"
                          r"\bnewday\b|\bmarbles\b|\baqua\b|\b\d{6}\*{4,}\d{4}\b", re.I)
# Paying off a card whose statements were not sent: the purchases on it are unknown, so it waits for the statements and
# the AI is not asked (it would guess a heading such as travel for the whole payment)
CARD_UNSENT = "paying off a credit card: send the card's statements"
CARD_COST_WORDS = re.compile(r"\bfees?\b|\bcharges?\b|\binterest\b|\binsurance\b", re.I)
# Paying off a credit card, as the card's statement prints it: the person's own money, never takings
# (the whole line 'Payments received': a customer's 'Faster payment received from ...' stays takings)
CARD_REPAYMENT = re.compile(r"^\W*payments? received\W*$|direct debit payment\W{0,5}thank you|\bpayment\W{0,5}thank you\b", re.I)


def platform_of(filename: str, bank: Optional[str]) -> Optional[str]:
    """The selling platform whose own report this is (eBay's financial statement, a PayPal statement): the issuer's name
    printed on it decides; with none printed, its file's path. A bank's statement in a platform's folder stays a bank's."""
    words = lambda s: set(re.findall(r"[a-z]{3,}", (s or "").lower()))
    found = (words(bank) if bank else words(filename.replace("\\", "/"))) & PAYOUT_PLATFORMS
    return sorted(found)[0] if found else None


# A vehicle bought from a dealer: a capital purchase, not a running cost. On the cash basis a car is left out of the
# costs and given capital allowances (ITTOIA 2005 s33A); a van may be a cost: the accountant says which. A garage's
# bill ('Motors Ltd', a service) stays a cost
CAR_DEALER = re.compile(r"\bcar sales\b|\bvehicle sales\b|\bcar ?dealers?\b|\bmotor group\b|\barnold clark\b|\bcinch\b|"
                        r"\bcazoo\b|\bcarshop\b|\bevans halshaw\b|\bsytner\b", re.I)
CAR_TRADE = re.compile(r"\bmotors?\b|\bautos?\b|\bcars?\b", re.I)
CAR_BOUGHT = 5000.0
# A payment of £500 or more to an equipment, vehicle or building supplier sorted as a cost is tested as capital first.
# The level is the firm's, not HMRC's. On the cash basis equipment stays a cost (CAA
# 2001 s66A, BIM72073); cars and buildings never do, and on the accruals basis it is capital allowances instead
CAPITAL_TEST = 500.0
ASSET_SUPPLIER = re.compile(r"\bscrewfix\b|\btoolstation\b|\bmachine mart\b|\bwickes\b|\btravis perkins\b|\bjewson\b|"
                            r"\bselco\b|\bhowdens\b|\bb ?& ?q\b|\bcurrys\b|\bapple store\b|\bapple\.com\b|\bdell\b|"
                            r"\blenovo\b|\bmachinery\b|\bequipment\b|\bplant (hire|sales)\b|\bbuilders? merchants?\b|"
                            r"\bcomputers?\b|\blaptops?\b|\btools?\b", re.I)
# Money in for a vehicle ('J SMITH VAN DEPOSIT', 'CAR SALE'): the sale of a business asset, not takings
VEHICLE_SOLD = re.compile(r"\b(van|car|vehicle|truck|lorry)\b.{0,12}\b(deposit|sale|sold)\b|\b(deposit|sale) (for|of) (the |my |a )?(van|car|vehicle)\b", re.I)
CAPITAL_PURCHASE = "a capital purchase"          # in a line's reason: the AI is not asked to sort it as a cost


def not_for_ai(line: Dict) -> bool:
    """A line left to the accountant on purpose (a vehicle bought, a card paid off with no card statements): the AI is
    not asked to sort it as a cost."""
    how = line.get("how") or ""
    return CAPITAL_PURCHASE in how or CARD_UNSENT in how


def car_bought(description: str, out: float) -> bool:
    return bool(out and (CAR_DEALER.search(description or "") and out >= 1000 or CAR_TRADE.search(description or "") and out >= CAR_BOUGHT))


# Wages, a pension or a state benefit paid in (never a supplier's refund)
WAGES_IN = re.compile(r"\bwages?\b|\bsalary\b|\bpayroll\b|\bpay ?roll\b|\bDWP\b|universal credit|child benefit|\bpension\b", re.I)
# Money between the person's own accounts, as the bank prints it ('123456 12345678 INTERNAL TRANSFER'): never takings
OWN_TRANSFER = re.compile(r"\binternal transfer\b|\bown account transfer\b|\btransfer (from|to) (my|own) (account|savings)\b", re.I)
BARE_TRANSFER = re.compile(r"^\W*(transfer|tfr|trf|xfer)\W*$", re.I)
# A card refund from a shop, as banks print it ('CREDIT FROM MARKS&SPENCER PLC ON 04-01-2026'): money back, not takings
CARD_REFUND = re.compile(r"\bcredit from\b.+\bon \d{2}-\d{2}-\d{4}\b", re.I)
# Rent from a let property: a property business (ITTOIA 2005 s264, PIM1051), not the trade's takings. A company's name
# with 'let' in it is not enough (the person may invoice a letting agent for their own work)
RENT_IN = re.compile(r"\brent(al)?\b|\btenan(t|cy)\b|\brent for the month\b", re.I)
TURNOVER_HEAD = "TURNOVER"
# The same money on the client's own sheet and on the bank statement: kept once (the same
# amount, the same way, within 3 days)
SAME_MONEY_DAYS = 3
# Rent the letting agent paid over reaches the bank within this many days of its statement
REMIT_DAYS = 10
UNSURE ={"Pension paid", "HMRC (check which tax)", "Corporation tax paid", "Cash withdrawn", "Net wages", "Donations"}
