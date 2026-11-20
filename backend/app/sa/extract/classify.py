"""What a document is, from its words. The first rule whose
words are found wins, so the specific kinds come before the general ones. A scan or photo has no words: the AI says
what it is while it reads it (vision.py)."""

import re
from typing import Optional

# (kind, words in the text, words in the file name)
RULES = [
    ("P60", r"\bP60\b|end of year certificate", r"\bp60\b"),
    ("P45", r"\bP45\b|details of employee leaving work", r"\bp45\b"),
    ("P11D", r"\bP11D\b|expenses and benefits", r"\bp11d\b"),
    ("CIS_STATEMENT", r"construction industry scheme|payment and deduction statement", r"\bcis\b|cis300"),
    # A foreign country's tax assessment or return: its income must be on the UK return (R-SA106-07)
    ("FOREIGN_TAX", r"\bITA ?34\b|avis d'imp[oô]t|imp[oô]t sur le revenu|direction g[ée]n[ée]rale des finances|"
                    r"\bIR3NR\b|\bIR3\b.{0,40}(return|inland revenue)|notice of assessment", r"\bita ?34\b|\bir3(nr)?\b|avis|french"),
    # A council's or agency's foster, kinship or shared lives care payments letter (R-SP-01)
    ("FOSTER_LETTER", r"foster(ing)? (care )?allowances?|qualifying care relief|kinship care|shared lives", r"foster|kinship"),
    # HMRC's Self Assessment statement (SA300): the payments on account charged and paid (R-FAM-03)
    ("HMRC_STATEMENT", r"self assessment statement|payment on account due for year", r"self[- ]?assessment statement|sa300|hmrc statement"),
    ("TAX_CALCULATION", r"\bSA302\b|tax calculation|calculation result for", r"sa302|tax ?calc"),
    ("TAX_CODE_NOTICE", r"\bP2\b.*tax code|your tax code for", r"coding notice|\bp2\b"),
    ("PAYSLIP", r"\bpay ?slip\b|payslip|net pay.{0,200}gross pay|gross pay.{0,200}net pay", r"pay ?slip"),
    # A DWP letter: the State Pension or a taxable benefit for the year (R-SP-02)
    ("DWP_LETTER", r"department for work and pensions|your state pension|new state pension|carer'?s allowance|"
                   r"jobseeker'?s allowance|employment and support allowance", r"\bdwp\b|state ?pension"),
    ("PENSION_STATEMENT", r"pension (payment|statement|advice)|annuity statement|pension contributions? statement", r"pension"),
    ("MORTGAGE_INTEREST", r"mortgage interest|interest.{0,60}on your mortgage|interest charged.{0,40}mortgage|"
                          r"annual mortgage statement|mortgage account number", r"mortgage"),
    ("LETTING_STATEMENT", r"letting agent|landlord statement|rent (received|collected)|management fee",
     r"letting|landlord|\brent(al|s)?\b"),          # whole words: 'Current account.csv' is not rent
    # (a broker's year-end tax report with its consolidated tax certificate: read for its interest and dividends)
    ("INTEREST_STATEMENT", r"interest (paid|earned|credited)|annual (savings )?statement|certificate of interest|\bISA\b|"
                           r"consolidated tax certificate|year end tax report|hereby certify that the dividends or interest",
     r"interest|savings|\bisa\b"),                  # 'Visa statement' is not an ISA
    ("DIVIDEND_VOUCHER", r"dividend (voucher|confirmation|tax voucher)|tax voucher", r"dividend"),
    # Charity donations for Gift Aid: a list, a charity's receipt or letter
    ("DONATIONS", r"gift aid (declaration|donation|claim)|thank you for your (kind )?donation",
     r"charit|donat|gift ?aid"),
    # Online banking's own download ('Your transactions ... Paid in ... Paid out', NatWest Bankline) is one too
    ("BANK_STATEMENT", r"sort code.{0,200}(balance|statement)|statement of account|opening balance.{0,300}closing balance|"
                       r"your transactions.{0,300}paid in|paid in.{0,40}paid out|money in.{0,40}money out",
     r"statement|bank|transactions"),
    ("WORKING_PAPER", r"working paper|\[Queries\]|\[Bank 1\]", r"working paper"),
    # A VAT return by its name (a scan has no text; the content test runs first in classify)
    ("VAT_RETURN", r"vat due on sales|vat reclaimed in the period|net vat to pay", r"vat ?return|vat ?100"),
    ("INVOICE", r"\binvoice\b|\breceipt\b", r"invoice|receipt"),
]
KINDS = [k for k, _, _ in RULES] + ["OTHER"]


SHEET = re.compile(r"\.(xls|xlsx|xlsm|ods)$", re.I)
WP_NAME = re.compile(r"working ?papers?|\bworkings?\b|\bwps?\b", re.I)
WP_WORDS = re.compile(r"working ?papers?|\[Queries\]|\[Bank 1\]|clients name:", re.I)
# The office's brief to the preparer (a 'Notes.docx' per client): it mentions P60s, interest and rent, but is none of
# them
OFFICE_NOTES = re.compile(r"^(notes?|brief|instructions?)\b[^/]*\.(docx?|txt)$", re.I)


CLIENT_RENT = re.compile(r"\brent(al)?\b(?! (?:paid|for (?:the )?(?:office|premises|shop|unit)))", re.I)
CLIENT_RENT_COSTS = re.compile(r"\b(agent|letting|management) fees?\b|\bfees\b|\brepairs?\b|\binsurance\b|\bmaintenance\b|"
                               r"\bboiler\b|\bgas (cert|safety)\b|\bper person\b|\btenan(t|cy)\b", re.I)


LANDLORD = re.compile(r"\bpropert(y|ies)\b|\btenan(t|cy|ts)\b|\bletting\b|\blandlord\b|\brental income\b|\brent received\b|"
                      r"\bper person\b|\bhouse\b", re.I)
VAT_WORDS = re.compile(r"vat due (on sales|in the period)|vat reclaimed (in the period|on purchases)|net vat to (pay|be paid)|"
                       r"total output tax|\bvat ?100\b|\bbox ?5\b.{0,400}\bbox ?6\b", re.I | re.S)
VAT_NAME = re.compile(r"\bvat\b", re.I)
FIRM_WORKINGS = re.compile(r"working|\bcgt\b|\bcomp\b|computation|tax calc", re.I)
TRADE_SHEET = re.compile(r"\binvoice (number|no)\b|\bcustomer\b|\bvan\b|\bsales\b", re.I)


def classify(text: str, filename: str) -> str:
    leaf = filename.replace("\\", "/").split("/")[-1].lower()
    head = (text or "")[:6000]
    # A VAT return or the firm's VAT working for one (the VAT 100 boxes), before the working-paper test: 'VAT working
    # paper.xlsx' is a VAT return's working, not the Self Assessment working paper (R-SA103-16)
    if VAT_WORDS.search(head) and (VAT_NAME.search(leaf) or len(VAT_WORDS.findall(head)) >= 2):
        return "VAT_RETURN"
    # A spreadsheet that is a working paper says so in its name or its sheets: it is one, whatever forms its PAYE sheet
    # names (a P45 or P60 mentioned on it is not the form itself)
    if SHEET.search(leaf) and (WP_NAME.search(leaf) or WP_WORDS.search(head)):
        return "WORKING_PAPER"
    if OFFICE_NOTES.search(leaf):
        return "OTHER"
    # The client's own income and expenses sheet (the firm's Profit and Loss template)
    if SHEET.search(leaf):
        from backend.app.sa.extract.client_sheet import looks_like
        if looks_like(head):
            return "CLIENT_ACCOUNTS"
        # The client's own rent sheet (rent month by month, with fees or costs): read as a rent statement with no agent,
        # so its figures wait for the accountant to confirm it
        if (not leaf.endswith(".csv") and len(CLIENT_RENT.findall(head)) >= 3 and CLIENT_RENT_COSTS.search(head)
                and LANDLORD.search(head + " " + leaf) and not TRADE_SHEET.search(head)):
            return "LETTING_STATEMENT"
        # The client's own income and expenses in their own layout: the model reads the business rows (own_sheet.py)
        # (not when its words make it a property, pension, tax or savings paper, nor the firm's own workings or a CGT
        # computation)
        from backend.app.sa.extract.own_sheet import looks_like as own_layout
        content = next((kind for kind, words, _ in RULES if head and re.search(words.replace(" ", r"\s+"), head, re.I | re.S)), None)
        if (own_layout(head, leaf) and content in (None, "INVOICE", "P60", "BANK_STATEMENT")
                and not FIRM_WORKINGS.search(filename.replace("\\", "/").lower())):
            return "CLIENT_ACCOUNTS"
    # A spreadsheet is never an HMRC or payroll form itself: one that reads like a P60 is someone's summary of it (the
    # firm's 'Master Tax Summary Sheet', a list of pensions). Read as a form, it would go as a picture and the next
    # rule down would make the firm's workings a rent or interest statement: it is the firm's paper, or filed to look at
    sheet = bool(SHEET.search(leaf))
    for kind, words, name in RULES:
        # A space in the words matches any run of spaces or line breaks ('Mortgage' and 'Interest' on two lines)
        if head and re.search(words.replace(" ", r"\s+"), head, re.I | re.S):
            return summary_sheet(filename) if sheet and kind in FORMS else kind
    for kind, _, name in RULES:
        if re.search(name, leaf):
            return summary_sheet(filename) if sheet and kind in FORMS else kind
    return "OTHER"


FORMS = ("P60", "P45", "PAYSLIP", "P11D", "TAX_CODE_NOTICE")
SUMMARY = re.compile(r"summary|\bcomp\b|computation", re.I)


def summary_sheet(filename: str) -> str:
    path = filename.replace("\\", "/").lower()
    return "WORKING_PAPER" if FIRM_WORKINGS.search(path) or SUMMARY.search(path.split("/")[-1]) else "OTHER"


FORMS = ("P60", "P45", "PAYSLIP", "P11D", "TAX_CODE_NOTICE")


DATED = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
YEAR_END = re.compile(r"year\s+end(?:ing|ed)?\s*:?\s*(?:31(?:st)?\s+march|5(?:th)?\s+april)\s+(20\d\d)", re.I)


def _tax_year_of_date(y: int, m: int, d: int) -> str:
    start = y if (m, d) >= (4, 6) else y - 1
    return f"{start}-{str(start + 1)[2:]}"


NAME_TAX_YEAR = re.compile(r"(?<!\d)(20\d\d)\s*[-/_]\s*(?:20)?(\d\d)(?!\d)")
NAME_YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")


def working_paper_year(text: str, filename: str = "") -> Optional[str]:
    """The tax year a working paper is for, from the strongest sign to the weakest (a sheet's header or rows are often
    copied from last year's paper, a file's name is set when it is saved):
      1  the file name's tax year ('2025-26', 'FY2025-2026')
      2  the file name's one year: the year the return ends ('workings 2026' is 2025-26)
      3  its 'Year ending' line, 31 March or 5 April (accounts made up to 31 March 2026 are the 2025-26 return)
      4  its rows' dates, when most fall in one tax year
      5  the general reading"""
    leaf = filename.replace("\\", "/").split("/")[-1]
    found = NAME_TAX_YEAR.search(leaf)
    if found and int(found.group(2)) == (int(found.group(1)) + 1) % 100:
        return f"{found.group(1)}-{found.group(2)}"
    one = NAME_YEAR.findall(leaf)
    if len(one) == 1:
        end = int(one[0])
        return f"{end - 1}-{str(end)[2:]}"
    found = YEAR_END.search(text or "")
    if found:
        end = int(found.group(1))
        return f"{end - 1}-{str(end)[2:]}"
    years: dict = {}
    for y, m, d in DATED.findall(text or ""):
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            ty = _tax_year_of_date(int(y), int(m), int(d))
            years[ty] = years.get(ty, 0) + 1
    if years:
        best, n = max(years.items(), key=lambda kv: kv[1])
        if n >= 6 and n >= 0.6 * sum(years.values()):
            return best
    return tax_year_of(text)


def tax_year_of(text: str) -> Optional[str]:
    """'2025-26' when the document names one tax year ('2025/26', '2025-26', 'tax year to 5 April 2026')."""
    found = re.search(r"\b(20\d\d)\s*[/-]\s*(\d\d)\b", text or "")
    if found and int(found.group(2)) == (int(found.group(1)) + 1) % 100:
        return f"{found.group(1)}-{found.group(2)}"
    found = re.search(r"5(th)? april (20\d\d)", text or "", re.I)
    if found:
        end = int(found.group(2))
        return f"{end - 1}-{str(end)[2:]}"
    return None
