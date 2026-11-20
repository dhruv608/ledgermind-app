"""Bank statements read line by line, the firm's code for each account, and the balance chain checked."""

from typing import Dict, List, Optional
from datetime import date, timedelta
import re
from dataclasses import replace

from backend.app.services.bank_only.input_files.common import (
    BANK_CODES, BANK_KINDS, BANK_TYPES, BankAccount, BankLine, CARD_CODE, CARD_NAME, DESC_WORDS, HEAD_COLUMN,
    INVOICE_REF, NARRATIVE_KINDS, OPENING_WORDS, Problem, RawInput, UNDATED_NOT_A_LINE, _amount, _col, _date,
    _header, _money_columns)


SUSPENSE_CODE = 9999    # as ledger.SUSPENSE


def _bank_codes(out: RawInput) -> None:
    """The firm's code for each bank account: the code whose balance in last year's TB the statement opens with;
    else the next free code, accounts open last year (an opening line on the statement) first, then accounts opened
    this year, in the order of the tabs (Virgin 4800, Tide Current 4801, Tide Saving 4802). A credit card is
    on 5351 Credit card, a creditor, whatever its order."""
    for a in out.accounts:
        if a.is_card:
            a.code = CARD_CODE
    last_year = [c for c in sorted(out.opening_tb) if c in BANK_CODES]
    taken: set = set()
    rest = []
    for a in [a for a in out.accounts if not a.is_card]:
        match = next((c for c in last_year if c not in taken and a.opening is not None
                      and abs(out.opening_tb[c] - a.opening) <= 0.01), None)
        if match is None:
            rest.append(a)
        else:
            a.code = match
            taken.add(match)
    # Then by name: the statement's account named in last year's TB ('Tide Saver' -> 'Tide Saver account')
    words = lambda text: set(re.findall(r"[a-z]{3,}", text.lower())) - {"bank", "account", "current", "the", "ltd"}
    for a in list(rest):
        own = words(a.name)
        scored = sorted(((len(own & words(out.opening_names.get(c, ""))), c) for c in last_year if c not in taken),
                        reverse=True)
        if own and scored and scored[0][0] and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            a.code = scored[0][1]
            taken.add(a.code)
            rest.remove(a)
    rest.sort(key=lambda a: not (a.opening and not a.opening_worked_out))       # stable: tab order otherwise
    free = [c for c in last_year if c not in taken] + [c for c in BANK_CODES if c not in out.opening_tb]
    for a in rest:
        a.code = next(c for c in free if c not in taken)
        taken.add(a.code)


def _account_name(name: str, ws) -> str:
    """'Bank Statement ( Tide Current).xlsx' -> 'Tide Current'; 'Main -Bank' -> 'Main'; a plain 'Bank Statement' -> 'Bank'."""
    text = re.sub(r"\.(xlsx|xlsm|csv)$", "", name, flags=re.I)
    text = re.sub(r"bank\s*statements?|statements?|\bbank\b|[()\-_]", " ", text, flags=re.I)
    text = " ".join(text.split())
    return text or "Bank"


def _bank_kind(type_text: str, desc: str) -> str:
    """The line's kind: from the bank's type column, else the kind written at the end of the narrative ('... Card
    purchase'), else the bank's own words in it ('Direct Debit IGNITIONPAY', 'Automated Credit ...', 'A CUSTOMER CD
    4931', 'Card 98 Apple.com/UK', '... FP 15/04/24')."""
    for pattern, kind in BANK_TYPES:
        if type_text and pattern.search(type_text.strip()):
            return kind
    ending = next((k for k in BANK_KINDS if desc.lower().endswith(k.lower())), "")
    return ending or next((kind for pattern, kind in NARRATIVE_KINDS if pattern.search(desc)), "")


def _line_date_column(heads: Dict[str, int]) -> Optional[int]:
    """The column with each line's own date: a transaction, posting or value date before a statement or due date (a
    NatWest statement typed up with 'Statement Date' on every line and the line's 'Posting Date' beside it)."""
    dates = sorted((i, h) for h, i in heads.items() if "date" in h)
    own = [i for i, h in dates if re.search(r"transaction|posting|posted|value|entry|txn", h)]
    other = [i for i, h in dates if not re.search(r"statement|due|period|report", h)]
    return (own or other or [i for i, _ in dates] or [None])[0]


def _read_bank(ws, out: RawInput, name: str) -> Optional[BankAccount]:
    hr, heads = _header(ws, ["date", DESC_WORDS])
    c_date = _line_date_column(heads)
    c_desc = _col(heads, *DESC_WORDS)
    c_type = next((i for h, i in heads.items() if "type" in h and i != c_desc), None)
    c_out, c_in, c_amount = _money_columns(heads)
    c_bal = _col(heads, "balance", "closing")
    c_head = next((i for h, i in heads.items() if HEAD_COLUMN.match(h)), None)
    if hr is None or (c_out is None and c_in is None and c_amount is None):
        out.problems.append(Problem("Bank", "HIGH", f"{name}: bank statement headings not found (Date, Description, "
                                                    "Debit, Credit, Balance)."))
        return None
    account = BankAccount(name=name, opening=None)
    undated: List[str] = []

    def cell(row, c):
        return row[c] if c is not None and c < len(row) else None

    for r_idx, row in enumerate(ws.iter_rows(min_row=hr + 1, values_only=True), hr + 1):
        when = _date(cell(row, c_date))
        desc = str(cell(row, c_desc) or "").strip()
        bal = _amount(cell(row, c_bal)) if cell(row, c_bal) not in (None, "") else None
        texts = {str(v).strip().lower() for v in row if isinstance(v, str)}
        if texts & set(OPENING_WORDS):
            account.opening = bal
            continue
        signed = _amount(cell(row, c_amount)) if c_amount is not None else 0.0
        money_out = abs(_amount(cell(row, c_out))) if c_amount is None else max(-signed, 0.0)
        money_in = abs(_amount(cell(row, c_in))) if c_amount is None else max(signed, 0.0)
        if c_amount is None and c_in is not None and money_out < 0.005 and _amount(cell(row, c_in)) < 0:
            # A minus in the money-in column, nothing paid out: money out (a savings statement with one 'Paid In'
            # column, withdrawals shown as -770)
            money_out, money_in = money_in, 0.0
        if when is None:
            # Before the first line, a balance on its own is the opening balance (a totals row comes after the lines)
            moved = money_out or money_in
            if not account.lines and bal is not None and not desc and not moved:
                account.opening = bal
                continue
            if desc and moved and account.lines and not UNDATED_NOT_A_LINE.search(desc):
                # A line the statement printed without its date (the date is on the line above for the same day):
                # read with that date, and said
                when = account.lines[-1].when
                undated.append(f"row {r_idx} '{desc[:30]}'")
            elif desc and not moved and bal is None and account.lines and not UNDATED_NOT_A_LINE.search(desc):
                # The narrative carried onto a second row ('BCARD ...' / 'VIA MOBILE'): part of the line above
                prev = account.lines[-1]
                prev.description = f"{prev.description} {desc}"
                prev.kind = prev.kind or _bank_kind("", prev.description)
                continue
            else:
                continue
        account.lines.append(BankLine(
            r_idx, when, desc, money_out, money_in, bal,
            _bank_kind(str(cell(row, c_type) or ""), desc), [a or b for a, b in INVOICE_REF.findall(desc)], account=name,
            head_given=str(cell(row, c_head) or "").strip()))
    if undated:
        out.problems.append(Problem("Bank", "MEDIUM", f"{name}: {len(undated)} row(s) with an amount but no date were "
                                                      f"read with the date of the line above ({', '.join(undated[:4])}): "
                                                      f"check them against the bank's statement."))
    # A credit card statement (Capital on Tap, Amex ...) shows what is owed: the balance goes up when the card is
    # used. Read from the balances themselves, and kept as a bank balance (negative = owed), so the rest of the route
    # treats the card like an overdrawn account.
    if _owed_balances(account.lines, account.opening):
        account.is_card = True
        for b in account.lines:
            b.balance = -b.balance if b.balance is not None else None
        account.opening = -account.opening if account.opening is not None else None
    elif CARD_NAME.search(f"{name} {ws.title}"):
        # A card typed with what is owed already negative (Debit | Credit | Balance -7,978.90) reads like an
        # overdrawn account: named a card, it is one
        account.is_card = True
    account.lines = _in_order(account.lines, account.opening)
    if account.opening is None and account.lines and account.lines[0].balance is not None:
        first = account.lines[0]
        account.opening = round(first.balance + first.money_out - first.money_in, 2)
        account.opening_worked_out = True
    return account


def _in_order(lines: List[BankLine], opening: Optional[float]) -> List[BankLine]:
    """The order the balances follow: the file's own order (card lines can carry an earlier date than the lines
    around them), the file reversed (newest first), or by date with each day's lines put in balance order (some banks
    list a day newest first). The one with the fewest breaks; the file's order when as good."""
    if len(lines) < 2 or any(b.balance is None for b in lines):
        return sorted(lines, key=lambda b: b.when) if lines and lines[0].when > lines[-1].when else lines
    by_date: List[BankLine] = []
    dated = sorted(lines[::-1] if lines[0].when > lines[-1].when else lines, key=lambda b: b.when)
    running, i = opening, 0
    while i < len(dated):
        day = [b for b in dated[i:] if b.when == dated[i].when]
        by_date += _chain(day, running)
        running = by_date[-1].balance
        i += len(day)
    return min((lines, lines[::-1], by_date), key=lambda order: _breaks(order, opening))


def _owed_balances(lines: List[BankLine], opening: Optional[float]) -> bool:
    """The balances follow on as an amount owed (up with money out) far better than as money held: a card."""
    with_balance = [b for b in lines if b.balance is not None]
    if len(with_balance) < 3:
        return False
    flipped = [replace(b, balance=-b.balance) for b in with_balance]
    held = _breaks(_in_order(list(with_balance), opening), opening)
    owed = _breaks(_in_order(flipped, -opening if opening is not None else None),
                   -opening if opening is not None else None)
    return owed < held and owed <= len(with_balance) * 0.1


def _breaks(lines: List[BankLine], opening: Optional[float]) -> int:
    """How many balances do not follow from the one before (the first line is taken as right if no opening)."""
    running, n = opening, 0
    for b in lines:
        if running is not None and abs(round(running - b.money_out + b.money_in, 2) - b.balance) > 0.01:
            n += 1
        running = b.balance
    return n


def _chain(day: List[BankLine], before: Optional[float]) -> List[BankLine]:
    """A day's lines in the order each balance follows from the one before (unchanged if no such order is found)."""
    if len(day) < 2:
        return day
    rest, ordered, running = list(day), [], before
    while rest:
        nxt = None
        if running is not None:
            nxt = next((b for b in rest if abs(round(running - b.money_out + b.money_in, 2) - b.balance) <= 0.01), None)
        if nxt is None and not ordered:
            # The day's first line: its balance before is no other line's balance after
            after = {round(b.balance, 2) for b in rest}
            starts = [b for b in rest if round(b.balance + b.money_out - b.money_in, 2) not in after]
            nxt = starts[0] if len(starts) == 1 else None
        if nxt is None:
            return day
        ordered.append(nxt)
        rest.remove(nxt)
        running = nxt.balance
    return ordered


def _check_bank(out: RawInput, account: BankAccount, several: bool) -> None:
    where = f"{account.name}: " if several else ""
    lines = account.lines
    if not lines:
        out.problems.append(Problem("Bank", "HIGH", f"{where}the bank statement has no lines."))
        return
    if account.opening is None:
        out.problems.append(Problem("Bank", "HIGH", f"{where}no opening balance on the bank statement.", False))
    elif account.opening_worked_out:
        out.problems.append(Problem("Bank", "MEDIUM", f"{where}no opening balance line: worked out as "
                                                      f"£{account.opening:,.2f} from the first line's balance. Check "
                                                      "it against last year's closing balance."))
    # Each balance must follow from the one before (a break means a missing or wrong line)
    running = account.opening
    for b in lines:
        expected = None if running is None else round(running - b.money_out + b.money_in, 2)
        if b.balance is not None and expected is not None and abs(expected - b.balance) > 0.01:
            out.problems.append(Problem("Bank", "HIGH",
                f"{where}balance does not follow on at row {b.row} ({b.when:%d/%m/%Y}): expected {expected:,.2f}, "
                f"statement shows {b.balance:,.2f}. A line may be missing.", False))
        running = b.balance if b.balance is not None else expected
    # Every month of the year present: a gap between months with lines is a missing statement; none at the start or
    # end may be an account opened or closed in the year, or not used
    if out.year_end:
        start = (out.year_end.replace(day=1) - timedelta(days=330)).replace(day=1)
        months, m = [], start
        while m <= out.year_end:
            months.append((m.year, m.month))
            m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        have = {(b.when.year, b.when.month) for b in lines}
        used = [i for i, mo in enumerate(months) if mo in have]
        missing = [mo for mo in months if mo not in have]
        inside = [mo for i, mo in enumerate(months) if mo not in have and used and used[0] < i < used[-1]]
        def label(mos):
            return ", ".join(date(y, mo, 1).strftime("%b %Y") for y, mo in mos)
        if inside:
            out.problems.append(Problem("Bank", "HIGH", f"{where}no bank lines in {label(inside)}: is a statement "
                                                        "month missing?", False))
        if len(missing) > len(inside):
            edge = [mo for mo in missing if mo not in inside]
            out.problems.append(Problem("Bank", "MEDIUM", f"{where}no bank lines in {label(edge)}: was the account "
                                                          "opened, closed or not used then, or is a statement missing?"))
        outside = [b for b in lines if b.when > out.year_end or b.when < start]
        if outside:
            out.problems.append(Problem("Bank", "MEDIUM", f"{where}{len(outside)} bank line(s) dated outside the year."))
    unknown = [b for b in lines if not b.kind]
    if unknown:
        out.problems.append(Problem("Bank", "LOW", f"{where}{len(unknown)} bank line(s) do not say their kind "
                                                   "(card, transfer, direct debit)."))
