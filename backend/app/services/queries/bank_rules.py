"""The firm's query rules for bank jobs (bank statements + Dext) that the Books tab does not ask: lines the firm's
rules already put to a head (director, HMRC, cash, card takings, solicitors, personal spending) still need the
client's word or a document. Each gives a query for the Queries tab only: no line's head, code or figure changes.

  BK-03 money to or from a director        BK-04 regular payments to a lender or lessor
  BK-05 money in from a lender (new loan?)  BK-06 payments to HMRC (the HMRC statements)
  BK-07 cash withdrawn or paid in           BK-09 months with no bank lines at the start or end of the year
  BK-10 card machine / online platform takings   BK-11 a large payment to solicitors, estate agents or developers
  BK-12 rent received                       BK-13 spending that looks personal
  BK-15 payments returned unpaid            AS-02 bills unpaid at the year end, kept as creditors
  BK-16 money in the account before the company was formed (first period), put to the director's loan
  BK-04 also: payments through a platform that collects for other firms (IgnitionPay), coded to accountancy fees

The amounts that decide a query are the firm's own (Firm setting "query_limits"), the defaults (LIMITS) otherwise."""

import re
from collections import defaultdict
from typing import Any, Dict, List

from backend.app.services.bank_only.bank_sort import DIRECTOR, OPENING_MONEY, UNSORTED, BankSort, SortedLine
from backend.app.services.bank_only.bills_match import BillsMatch
from backend.app.services.bank_only.input_files import RawInput
from backend.app.services.queries.r1_rules import LIMITS, _money, _query

CLIENT, ACCOUNTANT = "CLIENT", "ACCOUNTANT"

HMRC_HEADS = {"Corporation tax paid": "corporation tax", "VAT paid": "VAT", "PAYE and NI paid": "PAYE and NI",
              "HMRC (check which tax)": "HMRC, tax not clear"}
FINANCE_HEADS = {"Loan repayment", "Vehicle finance (HP)", "Vehicle hire"}
PERSONAL_HEADS = {"Personal (director's loan)"}
CARD_TAKINGS = "Sales (card takings)"
STATEMENT_GAP_DAYS = 14     # BK-09: a statement whose last line is more than this before the year end
# BK-01: money in that is not takings by its words (a loan, wages paid back, a gift or an investment)
OPENING_LINE = re.compile(r"\s*opening balance", re.I)
SALARY = re.compile(r"\bsalar(y|ies)\b|\bwages?\b|\bpayroll\b", re.I)
SAVINGS = re.compile(r"\bpots?\b|savings|deposit account|instant access|reserve account|business saver", re.I)
NOT_TAKINGS = re.compile(r"\b(loan|salary|wages|refund|back|gift|capital|invest\w*|repay\w*)\b", re.I)
# Online platforms that pay the client its takings less their fees (the card machine companies are the firm's rule)
PLATFORMS = re.compile(r"paypal|amazon|\bamzn\b|\bebay\b|\betsy\b|shopify|\buber\b|deliveroo|just ?eat|airbnb|"
                       r"booking\.com|\bvinted\b|\bstripe\b|sumup|zettle|square ?up|takepayments|\bdojo\b|worldpay|"
                       r"paymentsense|elavon|barclaycard|^bcard\d|global payments|first data|card ?net\b", re.I)
PLATFORM_NAMES = {"amzn": "Amazon", "bcard": "Barclaycard", "just eat": "Just Eat", "justeat": "Just Eat",
                  "booking.com": "Booking.com", "square up": "Square", "squareup": "Square", "sumup": "SumUp",
                  "paypal": "PayPal", "ebay": "eBay", "global payments": "Global Payments", "first data": "First Data",
                  "card net": "Cardnet", "cardnet": "Cardnet"}
LENDERS = re.compile(r"\bloan\b|\bbbl\b|bounce ?back|\bcbils\b|funding circle|\biwoca\b|\bfleximize\b|\bcapify\b|"
                     r"\byoulend\b|\bliberis\b|\bmerchant cash\b|esme loans|\bfinance\b|\bmortgage|\bcolcap\b|"
                     r"capital on tap|\buncapped\b|boost capital|\bnucleus\b|marketfinance|\bthincats\b", re.I)
PROPERTY_PAYEES = re.compile(r"\b(solicitors?|llp|law|legal|conveyanc\w*|notar\w*|completion|estate agents?|"
                             r"lettings?|homes|developments?|developers?|property|properties|land)\b", re.I)
RENT_IN = re.compile(r"\brent(al)?\b|\blettings?\b|letting agent|estate agents?|property management|\btenant", re.I)
CASH_IN = re.compile(r"\bcash\b|counter credit|\bcdm\b|cash deposit|paid in at", re.I)
RETURNED = re.compile(r"\breturned\b|\bunpaid\b|\breversal\b|\breversed\b|\bbounced\b|refer to drawer|\brtn\b|"
                      r"\br/d\b|recalled", re.I)
# Platforms that take payments for many firms (IgnitionPay is not always the accountant's fee)
COLLECTS_FOR_OTHERS = re.compile(r"ignition ?pay|practice ?ignition", re.I)
WORD = re.compile(r"[a-z][a-z&'.-]+", re.I)


def _payee(description: str) -> str:
    """The first words of a bank description, as the client would recognise the payee."""
    words = [w for w in WORD.findall(description or "") if not re.fullmatch(r"(card|payment|to|from|ref|dd|so|bp|"
                                                                            r"fpi|fpo|tfr|bgc|cr|dr|faster|payments?|direct|debit|"
                                                                            r"internet|banking|gbp|transfer|reference|"
                                                                            r"salary|sallery|wages)", w, re.I)]
    return " ".join(words[:3]).title() or (description or "").strip()[:30]


def _platform(description: str) -> str:
    """The card machine company or platform named on a takings line ('GBP FASTER PAYMENT WORLDPAY 2506' -> Worldpay)."""
    m = PLATFORMS.search(description or "")
    if not m:
        return _payee(description)
    word = re.sub(r"\d+$", "", m.group(0).strip().lower())
    return PLATFORM_NAMES.get(word, word.title())


def _text(s: SortedLine) -> str:
    b = s.line
    amount = b.money_in - b.money_out
    return f"{b.when:%d/%m/%Y} {b.description.strip()}: {'in' if amount > 0 else 'out'} {_money(amount)}"


def _by_payee(lines: List[SortedLine]) -> Dict[str, List[SortedLine]]:
    groups: Dict[str, List[SortedLine]] = defaultdict(list)
    for s in lines:
        groups[_payee(s.line.description)].append(s)
    return dict(sorted(groups.items(), key=lambda kv: -sum(x.line.money_in + x.line.money_out for x in kv[1])))


def bank_queries(raw: RawInput, bank: BankSort, bills: BillsMatch, limits: Dict[str, float],
                 has_payroll: bool = True) -> List[Dict[str, Any]]:
    """The Queries tab's questions from the firm's bank rules, for one bank job (has_payroll: a payroll report is
    uploaded)."""
    lim = {**LIMITS, **limits}
    ye = f"{raw.year_end:%d %B %Y}" if raw.year_end else "the year end"
    # A line the accountant has already decided (on the line or for the payee) is not asked about again
    lines = [s for s in bank.lines if not (raw.year_end and s.line.when > raw.year_end)]
    out: List[Dict[str, Any]] = []

    def blocking(q: Dict[str, Any]) -> Dict[str, Any]:
        q["blocking"] = True
        return q

    # BK-03: money to or from a director (the firm's rule puts it to the director's loan without asking)
    before = [s for s in lines if s.head == DIRECTOR and OPENING_MONEY.match(s.line.description)
              and not s.how.startswith("chosen")]
    director = [s for s in lines if s.head == DIRECTOR and not s.how.startswith("chosen") and s not in before]
    if director:
        paid_in = sum(s.line.money_in for s in director)
        paid_out = sum(s.line.money_out for s in director)
        seen = " and ".join(p for p in (f"{_money(paid_in)} paid in by the director" if paid_in else "",
                                        f"{_money(paid_out)} paid to the director" if paid_out else "") if p)
        out.append(blocking(_query(
            "bk03:director", CLIENT, f"Money to and from the director: {_money(paid_in + paid_out)}",
            f"We can see {seen}. Please confirm what each was: money lent to or repaid by the company, salary, "
            "dividends, or expenses paid back.",
            paid_in + paid_out, lines=[_text(s) for s in director], rule="BK-03")))

    # BK-16: the statement's opening balance in the company's first period, put to the director's loan
    if before:
        total = sum(s.line.money_in for s in before)
        out.append(_query(
            "bk16:opening", ACCOUNTANT, f"Money in the account before the company was formed: {_money(total)}",
            f"The bank statement starts with {_money(total)} already in the account before the company was "
            "incorporated. We propose to treat it as money introduced by the director (director's loan); costs the "
            "director paid before incorporation are asked for under the first period question. Please approve.",
            total, lines=[_text(s) for s in before], rule="BK-16"))

    # BK-04: payments through a platform that collects for other firms, coded to accountancy fees by the firm's rule
    collected = [s for s in lines if s.line.money_out > 0 and COLLECTS_FOR_OTHERS.search(s.line.description)
                 and not s.how.startswith("chosen")]
    if collected:
        # One question for the platform, whatever the bank adds after its name ('IGNITIONPAY BD', 'IGNITIONPAY AAD')
        payee, group = "IgnitionPay", collected
        total = sum(s.line.money_out for s in group)
        out.append(_query(
            "bk04:ignitionpay", CLIENT, f"Payments to {payee}: {len(group)} payments, {_money(total)}",
            f"There are payments to {payee} ({len(group)} payments, {_money(total)} in total). {payee} collects "
            "payments for many firms: please tell us who each was paid to and what for, and send the invoices.",
            total, lines=[_text(s) for s in group], rule="BK-04"))

    # BK-04: regular payments to a lender or lessor (the firm's rule codes them; the agreement gives the split)
    finance = [s for s in lines if s.head in FINANCE_HEADS and s.line.money_out > 0]
    for payee, group in _by_payee(finance).items():
        months = {(s.line.when.year, s.line.when.month) for s in group}
        total = sum(s.line.money_out for s in group)
        if len(months) >= 3 and total / len(months) >= lim["regular_payment"]:
            out.append(_query(
                f"bk04:{payee.lower()}", CLIENT, f"Regular payments to {payee}: {len(group)} payments, {_money(total)}",
                f"There are regular payments to {payee} ({len(group)} payments, {_money(total)} in total). Please tell "
                f"us what they are for and, if it is a loan, hire purchase or lease, send the agreement and a "
                f"statement showing the balance at {ye}.", total, lines=[_text(s) for s in group], rule="BK-04"))

    # BK-05: money in from a lender: a new loan needs its agreement and statement; and payments to a lender the
    # firm's rules did not sort (BK-04 asks about those they did): a loan we have no record of
    lender_in = [s for s in lines if s.line.money_in >= lim["lender_receipt"] and LENDERS.search(s.line.description)
                 and s.head not in ("Refund received", DIRECTOR)]
    lender_out = [s for s in lines if s.line.money_out > 0 and s.head == UNSORTED and LENDERS.search(s.line.description)]
    if lender_in:
        total = sum(s.line.money_in for s in lender_in)
        out.append(blocking(_query(
            "bk05:lender", CLIENT, f"Money in that looks like a loan: {_money(total)}",
            f"We can see money paid in that looks like a loan ({_money(total)}). Please send the loan agreement and a "
            f"statement showing the balance at {ye}, the interest charged and the repayments.",
            total, lines=[_text(s) for s in lender_in], rule="BK-05")))
    for payee, group in _by_payee(lender_out).items():
        total = sum(s.line.money_out for s in group)
        out.append(blocking(_query(
            f"bk05:{payee.lower()}", CLIENT, f"Payments to {payee}, a lender: {_money(total)}",
            f"We can see payments to {payee} ({len(group)} payment(s), {_money(total)}) that look like loan "
            f"repayments. Please send the loan agreement (if the loan is new) and a statement showing the balance at "
            f"{ye}, the interest charged and the repayments.", total, lines=[_text(s) for s in group], rule="BK-05")))

    # BK-01: money in taken as takings (no sales invoices kept) that does not look like takings: a loan, wages paid
    # back, a gift, or a one-off large amount from a payer seen once or twice
    taken = [s for s in lines if s.head == "Sales (no invoice)" and s.line.money_in >= lim["unknown_in"]]
    seen = defaultdict(int)
    for s in lines:
        if s.line.money_in > 0:
            seen[_payee(s.line.description)] += 1
    # (a lender's money is asked under BK-05; the app's own opening balance line is not a payment)
    odd = [s for s in taken if not LENDERS.search(s.line.description) and not OPENING_LINE.match(s.line.description)
           and (NOT_TAKINGS.search(s.line.description)
                or (seen[_payee(s.line.description)] <= 2 and s.line.money_in >= lim["one_off_in"]))]
    if odd:
        total = sum(s.line.money_in for s in odd)
        out.append(_query(
            "bk01:not_takings", CLIENT, f"Money in that may not be sales: {_money(total)}",
            f"We have taken these amounts paid in as sales, but they may be something else ({_money(total)} in all). "
            "For each one, please tell us what it was: sales, a loan (send the agreement), money from the director, "
            "a refund, or something else.", total, lines=[_text(s) for s in odd], rule="BK-01"))

    # PY-08: pay to people with no payroll report: each person, on the payroll or not (a director's pay is asked
    # with the director's money, BK-03)
    if not has_payroll:
        pay = [s for s in lines if s.line.money_out > 0 and s.head != DIRECTOR
               and (s.head == "Net wages" or SALARY.search(s.line.description))]
        for payee, group in _by_payee(pay).items():
            total = sum(s.line.money_out for s in group)
            if len(group) >= 2 and total >= lim["pay_person"]:
                out.append(blocking(_query(
                    f"py08:{payee.lower()}", CLIENT, f"Pay to {payee}: {len(group)} payments, {_money(total)}",
                    f"We can see regular payments to {payee} ({len(group)} payments, {_money(total)} in total) that "
                    "look like pay. Is this person on the company's payroll? If so, please send the payroll reports; "
                    "if not, tell us what the payments were for (a subcontractor's invoices, expenses paid back, or "
                    "something else).", total, lines=[_text(s) for s in group], rule="PY-08")))

    # BK-06: payments to HMRC: the HMRC statements show which tax and which period each paid
    hmrc = [s for s in lines if s.head in HMRC_HEADS and s.line.money_out > 0]
    if hmrc:
        taxes: Dict[str, float] = defaultdict(float)
        for s in hmrc:
            taxes[HMRC_HEADS[s.head]] += s.line.money_out
        total = sum(taxes.values())
        split = ", ".join(f"{t} {_money(v)}" for t, v in taxes.items())
        out.append(_query(
            "bk06:hmrc", CLIENT, f"Payments to HMRC: {_money(total)}",
            f"We can see payments to HMRC of {_money(total)} ({split}). Please send the HMRC account statements "
            "(PAYE, VAT and corporation tax, as they apply) so we can check which tax and period each one paid.",
            total, lines=[_text(s) for s in hmrc], rule="BK-06"))

    # BK-07: cash withdrawn or paid in
    cash = [s for s in lines if s.head == "Cash withdrawn"
            or (s.line.money_in > 0 and CASH_IN.search(s.line.description) and s.head != DIRECTOR)]
    total = sum(s.line.money_in + s.line.money_out for s in cash)
    if cash and total >= lim["cash_total"]:
        cash_out = sum(s.line.money_out for s in cash)
        cash_in = sum(s.line.money_in for s in cash)
        parts = [p for p in (f"{_money(cash_out)} withdrawn" if cash_out else "",
                             f"{_money(cash_in)} paid in" if cash_in else "") if p]
        out.append(_query(
            "bk07:cash", CLIENT, f"Cash: {' and '.join(parts)}",
            f"We can see {len(cash)} cash transactions ({' and '.join(parts)}). Please tell us "
            + " and ".join(p for p in ("what the cash taken out was used for (with any receipts)" if cash_out else "",
                                       "whether the cash paid in was takings from sales" if cash_in else "") if p) + ".",
            total, lines=[_text(s) for s in cash], rule="BK-07"))

    # BK-09: months with no bank lines at the start or end of the year (the Books tab shows them as a file note)
    for n, p in enumerate(raw.problems):
        if p.where == "Bank" and p.severity == "MEDIUM" and "no bank lines in" in p.text:
            out.append(_query(
                f"bk09:{n}", CLIENT, "Bank statements may be missing at the start or end of the year",
                p.text[0].upper() + p.text[1:] + f" Please send the statements for those months so we have the "
                f"full year to {ye}, or tell us the account was not open then.", round_=1, rule="BK-09"))
    # ... and a statement that stops part-way through the last month (lines to 2 January, year end 31 January)
    if raw.year_end and not any(q["ref"] == "BK-09" for q in out):
        short = [(a, max(b.when for b in a.lines)) for a in raw.accounts if a.lines]
        short = [(a, last) for a, last in short if (raw.year_end - last).days > STATEMENT_GAP_DAYS]
        if short:
            out.append(_query(
                "bk09:end", CLIENT, "Bank statements stop before the year end",
                "The statements we have stop before the year end: "
                + "; ".join(f"{a.name} runs to {last:%d/%m/%Y}" for a, last in short)
                + f". Please send the statements from then to {ye} (showing the balance on {ye}), or tell us there "
                  "were no transactions after that date.", round_=1, rule="BK-09"))

    # BK-08: lines naming a savings pot or deposit account whose statements we do not have (interest paid into it,
    # money moved to it): its balance at the year end is the company's money too
    if not any(SAVINGS.search(a.name or "") for a in raw.accounts):
        pots = [s for s in lines if SAVINGS.search(s.line.description) and s.head != DIRECTOR]
        if pots:
            out.append(_query(
                "bk08:savings", CLIENT, "A savings pot or deposit account we have no statements for",
                f"Some lines mention a savings pot or deposit account. Please send its statements for the year "
                f"(showing the balance on {ye}), or tell us it was closed before the year end.",
                sum(s.line.money_in + s.line.money_out for s in pots), lines=[_text(s) for s in pots], rule="BK-08"))

    # BK-10: takings paid in by a card machine company or an online platform: its statements give the sales before fees
    takings = [s for s in lines if s.line.money_in > 0 and (s.head == CARD_TAKINGS or
                                                            (s.head == UNSORTED and PLATFORMS.search(s.line.description)))]
    platforms: Dict[str, List[SortedLine]] = defaultdict(list)
    for s in takings:
        platforms[_platform(s.line.description)].append(s)
    for payee, group in sorted(platforms.items(), key=lambda kv: -sum(x.line.money_in for x in kv[1])):
        total = sum(s.line.money_in for s in group)
        out.append(_query(
            f"bk10:{payee.lower()}", CLIENT, f"Takings paid in by {payee}: {_money(total)}",
            f"Your sales come in through {payee} ({len(group)} payments, {_money(total)}). Please send {payee}'s "
            "monthly statements showing the gross sales, their fees and any refunds, so we record the sales before fees.",
            total, lines=[_text(s) for s in group], rule="BK-10"))

    # BK-11: a large payment to solicitors, estate agents or developers (a line in suspense is asked on the Books tab)
    property_out = [s for s in lines if s.line.money_out >= lim["property_payment"] and s.head != UNSORTED
                    and PROPERTY_PAYEES.search(s.line.description)]
    for s in property_out:
        b = s.line
        out.append(blocking(_query(
            f"bk11:{b.ref or b.row}", CLIENT, f"{_money(b.money_out)} paid to {_payee(b.description)} on {b.when:%d %B %Y}",
            f"We paid {_money(b.money_out)} to {_payee(b.description)} on {b.when:%d %B %Y} (\"{b.description.strip()}\"). "
            "If this was for buying a property, please send the completion statement and the purchase contract; "
            "otherwise please tell us what it was for.", b.money_out, rule="BK-11")))

    # BK-12: rent received: the letting agent statements give the gross rent and the agent's fees
    rent = [s for s in lines if s.line.money_in > 0 and RENT_IN.search(s.line.description)]
    if rent:
        total = sum(s.line.money_in for s in rent)
        out.append(_query(
            "bk12:rent", CLIENT, f"Rent received: {_money(total)}",
            f"We can see rent received ({_money(total)}). Please send the letting agent statements for the year "
            "(showing the gross rent and their fees) and the tenancy agreement(s).",
            total, lines=[_text(s) for s in rent], rule="BK-12"))

    # BK-13: spending that looks personal (the firm's rule puts it to the director's loan without asking)
    personal = [s for s in lines if s.head in PERSONAL_HEADS and s.line.money_out > 0 and not s.how.startswith("chosen")]
    total = sum(s.line.money_out for s in personal)
    if personal and total >= lim["personal_total"]:
        per = [f"{p}: {_money(sum(x.line.money_out for x in g))} ({len(g)})" for p, g in _by_payee(personal).items()]
        out.append(_query(
            "bk13:personal", CLIENT, f"Spending that looks personal: {_money(total)}",
            f"These payments ({_money(total)}) look personal, so we have charged them to the director's loan account. "
            "Were any of them for the business? If so, please tell us which and what for.",
            total, lines=per, rule="BK-13"))

    # BK-15: payments returned unpaid
    returned = [s for s in lines if RETURNED.search(s.line.description)]
    if returned:
        total = sum(s.line.money_in + s.line.money_out for s in returned)
        out.append(_query(
            "bk15:returned", CLIENT, f"Payments returned unpaid: {len(returned)}",
            "Some payments were returned unpaid. Please tell us whether each was made up later, and send the latest "
            "statement from the payee showing any amount still owed.",
            total, lines=[_text(s) for s in returned], rule="BK-15"))

    # AS-02: bills dated in the year and unpaid at the year end: kept as creditors, for the accountant to confirm
    unpaid = [i for i in bills.outstanding(brought_forward=False) if i.outstanding >= lim["unpaid_bill"]]
    if unpaid:
        total = sum(i.outstanding for i in unpaid)
        out.append(_query(
            "as02:unpaid_bills", ACCOUNTANT, f"Bills unpaid at the year end: {len(unpaid)}, {_money(total)}",
            f"These bills were unpaid at {ye} and are included as creditors ({_money(total)}). Please confirm they are "
            "still owed (not paid personally by the director, disputed or credited).", total,
            lines=[f"{i.invoice.when:%d/%m/%Y} {i.invoice.party} {i.invoice.number}".strip() + f": {_money(i.outstanding)}"
                   for i in sorted(unpaid, key=lambda i: -i.outstanding)], rule="AS-02"))
    return out
