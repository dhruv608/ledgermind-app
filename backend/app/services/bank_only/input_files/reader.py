"""read_input_files: every uploaded file read into one RawInput."""

from typing import Dict, List, Optional, Tuple
from datetime import date, timedelta

from backend.app.services.bank_only.input_files.bank import _account_name, _bank_codes, _check_bank, _read_bank
from backend.app.services.bank_only.input_files.common import OpeningCoder, Problem, RawInput, _date, _title_values
from backend.app.services.bank_only.input_files.invoices import _check_invoices, _read_invoices
from backend.app.services.bank_only.input_files.opening import _code_opening_names, _read_opening_tb, close_last_year
from backend.app.services.bank_only.input_files.parts import (
    BANK, BILLS, OPENING_BILLS, OPENING_SALES, OPENING_TB, RAW_ROLES, ROLE_LABELS, SALES, SKIP,
    _drop_repeated_statements, _parts, part_role)


def read_input_files(files_data: List[Tuple[str, bytes]], roles: Optional[Dict[str, str]] = None,
                     code_names: Optional[OpeningCoder] = None, year_end: Optional[date] = None) -> RawInput:
    """Read every file or tab by what it is (roles: the accountant's choice per name, else read from the headings).
    code_names gives last year's TB lines that have no firm code one from their name: {name: (code, why, sure)}
    (books.opening_coder: the accountant's choice, else the mapping used for a trial balance).
    year_end: the client's year end as kept in the app (typed on the upload screen when no file says it), used when
    the files do not give one."""
    parts = _parts(files_data)
    titles: Dict[str, str] = {}
    for _, ws in parts:
        for k, v in _title_values(ws).items():
            titles.setdefault(k, v)
    year_end = _date(titles.get("year end", "")) or year_end
    out = RawInput(client_name=titles.get("client", ""), year_end=year_end, opening_bank=None)
    chosen = roles or {}
    seen = set()
    for name, ws in parts:
        role = chosen.get(name) or part_role(name, ws, year_end)
        if role == SKIP or role not in RAW_ROLES:
            continue
        if role == OPENING_TB and role in seen:
            out.problems.append(Problem("Files", "HIGH", f"Two files or tabs are the {ROLE_LABELS[role].lower()}: "
                                                          f"{name} was not read. Upload one, or skip the other."))
            continue
        seen.add(role)
        if role == BANK:
            # One statement per bank account (Main and Pot; Tide current, Tide saving and Virgin)
            account = _read_bank(ws, out, _account_name(name, ws))
            if account is not None:
                out.accounts.append(account)
        elif role == SALES:
            out.sales += _read_invoices(ws, out, "Sales")
        elif role == BILLS:
            out.purchases += _read_invoices(ws, out, "Purchases")
        elif role == OPENING_SALES:
            out.opening_sales += _read_invoices(ws, out, "Sales")
        elif role == OPENING_BILLS:
            out.opening_bills += _read_invoices(ws, out, "Purchases")
        elif role == OPENING_TB:
            _read_opening_tb(ws, out)
    _code_opening_names(out, code_names)
    _drop_repeated_statements(out)
    names = [a.name for a in out.accounts]
    several = len(out.accounts) > 1
    for a in out.accounts:
        if names.count(a.name) > 1:
            a.name = f"{a.name} {names[:out.accounts.index(a) + 1].count(a.name)}"
        for b in a.lines:
            b.account = a.name
            b.ref = f"{a.name}:{b.row}" if several else str(b.row)
        _check_bank(out, a, several=several)
    # A statement that runs on past the year end closes with its balance on the year end (closing). Lines before a
    # year counted back from the year end are kept: a company's first accounts can run up to 18 months
    for a in out.accounts:
        a.year_end = year_end
    _bank_codes(out)
    # A statement with no opening balance (none on it, none to work out) opens with last year's closing balance for the
    # account, never at nil
    for a in out.accounts:
        if a.opening is None and a.code in out.opening_tb:
            a.opening = out.opening_tb[a.code]
            where = f"{a.name}: " if several else ""
            out.problems = [p for p in out.problems if p.text != f"{where}no opening balance on the bank statement."]
            out.problems.append(Problem("Bank", "MEDIUM", f"{where}no opening balance on the statement: last year's "
                                                          f"TB gives £{abs(a.opening):,.2f}"
                                                          f"{' owed' if a.opening < 0 else ''} on {a.code}, used as "
                                                          f"the opening balance."))
    # A statement that starts before the year: when last year's TB holds the balance on the day before the year starts,
    # the earlier lines are last year's (in its closing figures), so the account opens there and they are not booked
    # again. When last year's TB holds the statement's own opening instead, the lines are kept (a first period can run
    # up to 18 months)
    if year_end:
        start = year_end.replace(year=year_end.year - 1) + timedelta(days=1)
        for a in out.accounts:
            before = [b for b in a.lines if b.when < start]
            last = out.opening_tb.get(a.code)
            if (before and last is not None and before[-1].balance is not None
                    and abs(before[-1].balance - last) <= 0.01
                    and (a.opening is None or abs(a.opening - last) > 0.01)):
                a.opening, a.opening_worked_out, a.starts = before[-1].balance, False, start
                where = f"{a.name}: " if several else ""
                out.problems.append(Problem("Bank", "LOW", f"{where}{len(before)} line(s) before {start:%d/%m/%Y} are "
                                                           f"last year's (last year's TB holds the balance on the day "
                                                           f"before): not booked again."))
        # The statement's own opening does not matter where the account opens at the year start
        moved = tuple(f"{a.name}: " if several else "" for a in out.accounts if a.starts)
        out.problems = [p for p in out.problems
                        if not any(p.text.startswith(f"{w}no opening balance line: worked out") for w in moved)]
        # One account proves the year starts there (not a first period): every account's earlier lines are last
        # year's too, even one last year's TB does not hold (a card whose earlier repayments from the bank are last
        # year's)
        if any(a.starts for a in out.accounts):
            for a in out.accounts:
                before = [b for b in a.lines if b.when < start]
                if a.starts or not before or before[-1].balance is None:
                    continue
                a.opening, a.opening_worked_out, a.starts = before[-1].balance, False, start
                where = f"{a.name}: " if several else ""
                out.problems.append(Problem("Bank", "MEDIUM", f"{where}{len(before)} line(s) before {start:%d/%m/%Y} "
                                                              f"are last year's: not booked; the account opens at "
                                                              f"£{abs(a.opening):,.2f}{' owed' if a.opening < 0 else ''}, "
                                                              f"which last year's TB does not hold: check last year's "
                                                              f"figures."))
            moved = tuple(f"{a.name}: " if several else "" for a in out.accounts if a.starts)
            out.problems = [p for p in out.problems
                            if not any(p.text.startswith(f"{w}no opening balance line: worked out") for w in moved)]
    # The statement should open with last year's closing balance for the account; a difference is the accountant's
    # to explain
    for a in out.accounts:
        if a.opening is not None and a.code in out.opening_tb and abs(out.opening_tb[a.code] - a.opening) > 0.01:
            out.problems.append(Problem("Opening", "HIGH", (
                f"{a.name}: the statement opens at £{abs(a.opening):,.2f}{' owed' if a.opening < 0 else ''}, last "
                f"year's TB has £{abs(out.opening_tb[a.code]):,.2f}{' owed' if out.opening_tb[a.code] < 0 else ''} "
                f"on {a.code}: a difference of £{abs(a.opening - out.opening_tb[a.code]):,.2f} to explain "
                f"(last year's figure or the statement).")))
        elif (a.opening is not None and abs(a.opening) > 0.01 and not a.opening_worked_out and out.opening_tb
              and a.code not in out.opening_tb):
            # Last year's TB has nothing for the account, yet the statement opens with a balance: the books open it
            # at nil, so the account will not agree with the statement by that much
            out.problems.append(Problem("Opening", "HIGH", (
                f"{a.name}: the statement opens at £{abs(a.opening):,.2f}{' owed' if a.opening < 0 else ''}, but last "
                f"year's TB has nothing for this {'card' if a.is_card else 'account'} ({a.code}): the books start it at "
                f"nil, so it will differ from the statement by £{abs(a.opening):,.2f}. Check last year's accounts (a "
                f"{'card balance' if a.is_card else 'bank account'} missing from them) and the statement's start date."),
                blocks_upload=False))
    out.bank = [b for a in out.accounts for b in a.lines]
    openings = [a.opening for a in out.accounts]
    out.opening_bank = round(sum(openings), 2) if openings and None not in openings else None
    if BANK not in seen:
        out.problems.append(Problem("Bank", "HIGH", "No bank statement found."))
    if SALES not in seen:
        out.problems.append(Problem("Sales", "MEDIUM", "No sales invoices: money in from customers has no invoice to "
                                                       "match (cash takings banked, or the sales list is missing)."))
    if not out.client_name:
        out.problems.append(Problem("Files", "MEDIUM", "The client's name was not found ('Client: …' above the headings)."))
    if year_end is None:
        out.problems.append(Problem("Files", "HIGH", "The year end was not found ('Year End: 31.03.2026' or "
                                                     "'Y.E: 31/03/2026' above the headings)."))
    if OPENING_TB not in seen:
        out.problems.append(Problem("Opening", "MEDIUM", "No closing trial balance for last year: opening balances are "
                                                         "nil unless last year was done in the app."))
    elif out.opening_tb and not out.opening_uncoded and abs(sum(out.opening_tb.values())) > 0.01:
        out.problems.append(Problem("Opening", "HIGH", f"Last year's trial balance does not balance (difference "
                                                       f"£{sum(out.opening_tb.values()):,.2f})."))
    _check_invoices(out)
    out.last_year_tb = dict(out.opening_tb)
    out.opening_tb = close_last_year(out.opening_tb)
    from backend.app.services.bank_only.categories import materials_code, no_bill_code
    out.materials_code = materials_code(out.last_year_tb)
    out.no_bill_code = no_bill_code(out.last_year_tb, bank_only=out.bank_only)
    return out
