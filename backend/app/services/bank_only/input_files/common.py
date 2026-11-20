"""The raw data route's records (bank lines, accounts, invoices, problems, the whole input) and cell readers."""

from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import date, datetime
import re


# How the bank shows the kind of line, at the end of the description ('... Card purchase')
BANK_KINDS = ("Card purchase", "Bank transfer", "Direct debit", "Direct credit", "Scheduled payment",
              "Standing order", "Faster payment", "Internet Refund", "Cash withdrawal", "Interest", "Charge")
# The bank's own type column, where it has one ('DEB', 'Card Transaction', 'Own Account Transfer'), as those kinds
BANK_TYPES = [(re.compile(p, re.I), kind) for p, kind in (
    (r"^(deb|pos|card|cd)\b|card transaction|card payment", "Card purchase"),
    (r"^(dd|ddr)\b|direct debit", "Direct debit"),
    (r"^(so|sto)\b|standing order", "Standing order"),
    (r"^(fpi|fpo|bgc|tfr|bac|bacs|cr|fps)\b|transfer|faster payment", "Bank transfer"),
    (r"interest", "Interest"),
    (r"^(chg|chgs)\b|charge|fee", "Charge"),
    (r"^(atm|cash)\b|cash withdrawal", "Cash withdrawal"),
)]
# The kind in the narrative itself, as UK banks write it (statements with no type column), first match wins
NARRATIVE_KINDS = [(re.compile(p, re.I), kind) for p, kind in (
    (r"returned d/?d|unpaid d/?d|\bdd return|direct debit (return|refund)", "Internet Refund"),
    (r"direct debit|\(dd\)|^dd\b|\bddr\b", "Direct debit"),
    (r"standing order|^so\b|^sto\b|\(standing", "Standing order"),
    (r"^bcard\d|barclaycard|^elavon|merchant services|card takings", "Card takings"),
    (r"card payment|card purchase|\bcd \d{4}\b|^card \d{2}\b|contactless|\bpos\b|^deb\b|visa debit|"
     r"\b(gbr|usa|irl|fra|deu|nld)\s*$|orig\. amt", "Card purchase"),
    (r"\bcharges?\b|account fee|monthly fee|non[- ]?sterling|non gbp", "Charge"),
    (r"\binterest\b", "Interest"),
    (r"\batm\b|cash withdrawal|cash machine", "Cash withdrawal"),
    (r"automated credit|direct credit|\bbgc\b|\bfpi\b|\bfpo\b|faster payments?|\bfp \d{2}/\d{2}|bill payment|"
     r"\btfr\b|transfer|\bbacs\b|sent from (monzo|revolut)|\bref(erence)?:", "Bank transfer"),
)]
# A row with no date that is not a bank line: a total, or the balance brought or carried forward
UNDATED_NOT_A_LINE = re.compile(r"^\s*(sub[- ]?)?totals?\b|balance\s+(b/?f|c/?f|brought|carried)|brought forward|"
                                r"carried forward|opening balance|closing balance", re.I)
# Invoice numbers quoted on a bank line ('Bd200487', 'Invoice BD200622', '200645'); a short number only after
# 'Inv'/'Invoice' ('Invoice 167', 'Inv 111')
INVOICE_REF = re.compile(r"\b(?:bd)?(\d{5,7})\b|\binv(?:oice)?\.?\s*(?:no\.?\s*)?#?\s*(\d{2,4})\b", re.I)

# A credit card account, by its file or tab name
CARD_NAME = re.compile(r"credit\s*card|\bamex\b|american express|barclaycard|capital on tap|\bmastercard\b|\bvisa\b", re.I)
# Bank statement headings, as different banks word them
DESC_WORDS = ("description", "details", "narrative", "particulars")
OUT_WORDS = ("debit", "paid out", "money out", "out amount", "amount out", "withdrawal", "withdrawn", "payments", "moneyout",
             "paidout")
IN_WORDS = ("credit", "paid in", "money in", "in amount", "amount in", "deposit", "receipts", "moneyin", "paidin")
# Headings that are the whole word only ('£ IN' / '£ OUT'; a signed 'Amount': money in positive, out negative)
OUT_EXACT, IN_EXACT, AMOUNT_EXACT = ("out",), ("in",), ("amount", "value")
# A head the client or the preparer already wrote against each line: taken as the suggestion for the line
HEAD_COLUMN = re.compile(r"^(account\s+)?heads?$|^classification$|^analysis$|^category$|^allocation$|^nominal( code)?$")
OPENING_WORDS = ("opening", "opening balance", "balance brought forward", "brought forward", "balance b/f", "b/f",
                 "previous statement", "previous balance")
# An invoice number Excel has turned into a rounded number ('1.00113E+11'): the real number is lost
DAMAGED_NUMBER = re.compile(r"^\d(\.\d+)?e\+\d+$", re.I)
# The name column of a sales or a bills list, however headed
PARTY_WORDS = {"Sales": ("customer", "client", "debtor", "contact", "name", "payer"),
               "Purchases": ("supplier", "vendor", "creditor", "contact", "payee", "name")}
YEAR_END = re.compile(r"(?:year\s*end(?:ed|ing)?|\by\.?\s*e\b\.?)\s*[:.\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", re.I)


@dataclass
class BankLine:
    row: int                    # row in the input file (for the reviewer to find it)
    when: date
    description: str
    money_out: float
    money_in: float
    balance: Optional[float]
    kind: str                   # Card purchase / Bank transfer / Direct debit ... or ""
    refs: List[str]             # invoice numbers quoted on the line (digits only)
    account: str = ""           # which bank account ('Tide Current'): the tab it came from
    head_given: str = ""        # a head the accountant already wrote on the statement ('Heads' column), if any
    ref: str = ""               # the line's id for the accountant's choices: the row, with the account when several


BANK_CODES = range(4800, 4830)      # the firm's bank current, deposit and reserve account codes
CARD_CODE = 5351                    # Credit card: what a company card owes is a creditor due within a year, not cash
                                    # (FRS 102 s11)


@dataclass
class BankAccount:
    name: str
    opening: Optional[float]
    lines: List[BankLine] = field(default_factory=list)
    opening_worked_out: bool = False      # no opening line: worked out from the first line's balance
    code: int = 4800                      # the firm's code for this account (4800, 4801 ...)
    is_card: bool = False                 # a credit card: its statement balances (owed) are read as negative
    year_end: Optional[date] = None       # the client's year end: the closing balance is the one on that day
    starts: Optional[date] = None         # set when the lines before this day are last year's (not booked)

    @property
    def closing(self) -> Optional[float]:
        """The statement's balance at the year end (a statement often runs on past it)."""
        lines = [b for b in self.lines if self.year_end is None or b.when <= self.year_end]
        return lines[-1].balance if lines else self.opening


@dataclass
class Invoice:
    row: int
    when: date
    due: Optional[date]
    number: str                 # as written ('BD200576'); "" if none
    party: str                  # customer or supplier
    description: str
    gross: float
    vat: float
    net: float
    received: Optional[float] = None    # sales only: what Dext shows as received
    link: str = ""
    category: str = ""                  # Dext's category ('Travel And Subsistence', 'Accountancy'), if exported


@dataclass
class Problem:
    where: str                  # Bank / Sales / Purchases
    severity: str               # HIGH (blocks the work) / MEDIUM / LOW
    text: str
    # A HIGH problem in the statement's own figures (a balance that does not follow on, a month or the opening
    # balance missing) does not stop the upload: it is shown on the Data check for the accountant to look at
    blocks_upload: bool = True


@dataclass
class RawInput:
    client_name: str
    year_end: Optional[date]
    opening_bank: Optional[float]           # all bank accounts together (None if one is not known)
    bank: List[BankLine] = field(default_factory=list)          # every account's lines, account by account
    accounts: List[BankAccount] = field(default_factory=list)
    sales: List[Invoice] = field(default_factory=list)
    purchases: List[Invoice] = field(default_factory=list)
    problems: List[Problem] = field(default_factory=list)
    # Last year: the closing trial balance (firm code -> balance, debit +) and the invoices and bills still unpaid
    opening_tb: Dict[int, float] = field(default_factory=dict)
    opening_names: Dict[int, str] = field(default_factory=dict)
    # Last year's TB lines with a name but no firm code ('Bank current account | 2,438.06'): (name, balance, debit +).
    # They are given codes from their names when the books are worked out (opening_lines: what each was given)
    opening_uncoded: List[Tuple[str, float]] = field(default_factory=list)
    opening_lines: List[Dict[str, Any]] = field(default_factory=list)
    # Last year's TB as given (with its P&L when it was taken before the year-end close): for last year vs this year.
    # opening_tb is the same closed into the brought-forward accounts (the books' opening balances)
    last_year_tb: Dict[int, float] = field(default_factory=dict)
    materials_code: int = 1100          # Dext 'Materials': 1100, or 1400 when last year used 1400 (raw_categories)
    no_bill_code: int = 1400            # bank payments for goods with no bill: 1400, or 1100 when last year used 1100
    opening_sales: List[Invoice] = field(default_factory=list)
    opening_bills: List[Invoice] = field(default_factory=list)

    @property
    def bank_only(self) -> bool:
        """Bank (and card) statements with no invoice or bill lists at all: a bank-only client."""
        return not (self.sales or self.purchases or self.opening_sales or self.opening_bills)

    def summary(self) -> Dict[str, Any]:
        return {
            "client": self.client_name, "year_end": self.year_end,
            "bank_lines": len(self.bank), "opening_bank": self.opening_bank,
            "money_in": round(sum(b.money_in for b in self.bank), 2),
            "money_out": round(sum(b.money_out for b in self.bank), 2),
            "bank_accounts": [a.name for a in self.accounts],
            "closing_bank": self.closing_bank,
            "sales_invoices": len(self.sales), "sales_total": round(sum(i.gross for i in self.sales), 2),
            "customers": len({i.party for i in self.sales}),
            "purchase_bills": len(self.purchases), "purchases_total": round(sum(i.gross for i in self.purchases), 2),
            "purchases_vat": round(sum(i.vat for i in self.purchases), 2),
            "suppliers": len({i.party for i in self.purchases}),
            "problems": len(self.problems),
        }

    @property
    def closing_bank(self) -> Optional[float]:
        """All accounts' closing balances as the statements show them (None if one is not known)."""
        closings = [a.closing for a in self.accounts]
        return round(sum(closings), 2) if closings and None not in closings else None


def _date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%d.%m.%y", "%d/%m/%y"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except ValueError:
                pass
    return None


def _amount(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    text = str(v).replace("£", "").replace(",", "").strip()
    negative = text.startswith("(") and text.endswith(")")
    try:
        n = float(text.strip("()"))
    except ValueError:
        return 0.0
    return round(-n if negative else n, 2)


def _find_tab(wb, *words: str):
    for ws in wb.worksheets:
        if any(w in ws.title.lower() for w in words):
            return ws
    return None


def _header(ws, required: List[Any], max_row: int = 15):
    """The heading row (the first row holding all the required words; a tuple is any one of its words) and
    {heading: column index}."""
    for r in range(1, max_row + 1):
        # 'Moneyout£', '£ IN', 'Balance £': the pound sign and extra spaces are not part of the heading
        heads = {" ".join(str(c.value).replace("£", " ").split()).lower(): c.column - 1
                 for c in ws[r] if c.value not in (None, "") and str(c.value).replace("£", "").strip()}
        if all(any(w in h for w in (word if isinstance(word, tuple) else (word,)) for h in heads)
               for word in required):
            return r, heads
    return None, {}


def _col(heads: Dict[str, int], *words: str) -> Optional[int]:
    for w in words:
        for h, i in heads.items():
            if w in h:
                return i
    return None


def _money_columns(heads: Dict[str, int]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """(money out, money in, signed amount) columns of a statement: separate in / out columns, or one signed amount."""
    exact = lambda words: next((i for h, i in heads.items() if h in words), None)
    c_out = _col(heads, *OUT_WORDS)
    c_in = _col(heads, *IN_WORDS)
    c_out = c_out if c_out is not None else exact(OUT_EXACT)
    c_in = c_in if c_in is not None else exact(IN_EXACT)
    c_amount = exact(AMOUNT_EXACT) if c_out is None and c_in is None else None
    return c_out, c_in, c_amount


def _title_values(ws) -> Dict[str, Any]:
    """The client's name and year end written above the headings: 'Client: X', and the year end as 'Year End:
    31.03.2026', 'Y.E: 31/10/2025', 'Y.E.: 30.09.2025' or 'Y.E.30.06.2025'."""
    out: Dict[str, Any] = {}
    for r in ws.iter_rows(min_row=1, max_row=5, values_only=True):
        for v in r:
            if not isinstance(v, str):
                continue
            m = YEAR_END.search(v)
            if m and _date(m.group(1).replace("/", ".").replace("-", ".")):
                out.setdefault("year end", _date(m.group(1).replace("/", ".").replace("-", ".")))
            elif (m := re.match(r"\s*client\s*[:\-–]\s*(.+)", v, re.I)) and m.group(1).strip():
                out.setdefault("client", m.group(1).strip())    # 'Client: X' or 'Client - X'
    return out


OpeningCoder = Callable[[List[Tuple[str, float]]], Dict[str, Tuple[Optional[int], str, bool]]]
