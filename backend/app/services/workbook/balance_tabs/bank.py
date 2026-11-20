"""One tab per bank account (F3.n), the bank summary (F2) and the bank lead (F1)."""

import re
from collections import Counter
from typing import Dict, List, Tuple
from datetime import date
from openpyxl.utils import get_column_letter
from statistics import median

from backend.app.services.workbook.balance_tabs.common import (
    BANK_CODES, BOLD, CURRENCY, INPUT_FILL, Context, TITLE, _blank, _etb, _has_balance, _input, _money, _new_sheet,
    _records, _sheet_title, _when
)


# ------------------------------------------------------------------------------------------------------------------
# Bank: one tab per account, and the F1 lead with one line each
# ------------------------------------------------------------------------------------------------------------------
def bank_tabs(ctx: Context) -> List[str]:
    # Every bank account in the TB, a nil one too: its statement still confirms the nil
    codes = [c for c in BANK_CODES if _has_balance(ctx, [c]) or _records(ctx, [c])]
    made: List[Tuple[str, str, int, Dict[str, object]]] = []
    after = ["F2.1-NL Transaction", "F2-Bank", "F1 (LEAD)"]
    for i, code in enumerate(codes, 1):
        names = [t.raw_account_name for t in _records(ctx, [code])] or [ctx.account_name(code)]
        made.append(_account_tab(ctx, code, f"F3.{i}", names, after, "Balance c/fwd (negative = overdrawn)"))
        after = [made[-1][0]]

    if made:
        _bank_lead(ctx, made)
        _bank_summary(ctx, made)
        ctx.notes.append(f"{len(made)} bank account tab(s) (F3): enter each statement balance to reconcile")
        # Each bank's tab lists its own ledger lines beside its reconciliation, so the template's one tab of every
        # bank's lines would only repeat them
        if "F2.1-NL Transaction" in ctx.wb.sheetnames:
            del ctx.wb["F2.1-NL Transaction"]
    return [m[0] for m in made]


def _account_tab(ctx: Context, code: int, ref: str, names: List[str], after: List[str], cf_label: str,
                 statement: str = "bank statement", key: str = "bank") -> Tuple[str, str, int, Dict[str, object]]:
    """One account's control tab, as the screen shows it (one T, its lines named): the T
    (balance_tabs/t_shape), its checks, the reconciliation to its statement, the statement's own lines when one was
    read (unrecorded, unmatched, matched), and its ledger lines. Used for each bank (F3.n) and each credit card (F4.n).
    Returns (title, label, code, refs): refs hold formula terms on this tab (debit +) for bf, adj, jnl, cf and the
    statement and difference cells."""
    from backend.app.services.workbook.balance_tabs.t_shape import t_account
    label = " / ".join(dict.fromkeys(names))
    ws = _new_sheet(ctx, _sheet_title(ctx.wb, ref, names[0]), after)
    ws["E1"] = ref
    ws["A4"] = f"{label} ({code})"
    ws["A4"].font = TITLE
    t = t_account(ctx, ws, code, top=6)
    cf = t["cf"]

    top = t["end"] + 2                            # the reconciliation below the T
    stmt, cur_amt, rate, diff = f"D{top + 1}", f"D{top + 2}", f"D{top + 3}", f"D{top + 4}"
    ws.cell(row=top, column=1, value="Reconciliation").font = BOLD
    ws.cell(row=top + 1, column=2, value=f"Balance as per {statement} at {ctx.period_end:%d/%m/%Y} (£)")
    currency = CURRENCY.search(label)
    entered = ctx.statements.get(f"{key}:{code}") or {}       # typed on the control accounts screen
    if currency:
        cur = currency.group(0).upper().replace("$", "USD").replace("€", "EUR")
        ws.cell(row=top + 2, column=2, value=f"Statement balance in {cur}")
        _input(ws[cur_amt], entered.get("currency_amount"))
        ws.cell(row=top + 3, column=2, value=f"Exchange rate at the year end ({cur} per £1)")
        _input(ws[rate], entered.get("rate"))
        ws[rate].number_format = "0.00000"
        if entered.get("balance") is not None:
            _input(ws[stmt], entered["balance"])     # the £ balance was typed instead of the currency one
        else:
            _money(ws[stmt]).value = f'=IF(OR({cur_amt}="",{rate}=""),"",ROUND({cur_amt}/{rate},2))'
        ws.cell(row=top + 2, column=5, value="Type these two")
    else:
        _input(ws[stmt], entered.get("balance"))
        ws.cell(row=top + 1, column=5, value="Type this")
    # Where the figure came from: the statement's date and page, and for a currency account the
    # rate's source (HMRC monthly rate, Bank of England, the bank's own rate)
    ws.cell(row=top + 1, column=6, value="Statement date / page")
    ref_cell = ws.cell(row=top + 1, column=7, value=_statement_ref(entered))
    ref_cell.fill = INPUT_FILL
    if currency:
        ws.cell(row=top + 3, column=6, value="Rate source")
        ws.cell(row=top + 3, column=7, value=entered.get("rate_source")).fill = INPUT_FILL
    ws.cell(row=top + 4, column=2, value="Difference: books less statement (must be nil)").font = BOLD
    _money(ws[diff], bold=True).value = f'=IF({stmt}="","Statement balance not entered",ROUND({cf}-{stmt},2))'
    row = top + 6
    if currency:
        ws.cell(row=top + 5, column=2, value=("A foreign currency account: a difference after the year-end rate is "
                                               "an exchange gain or loss to post (code 3562)."))
        row += 1
    # The statement's own lines against the books (unrecorded / unmatched / matched), when a statement was read on
    # the screen
    from backend.app.services.workbook.balance_tabs.statement_lines import statement_lines_block
    row = statement_lines_block(ctx, ws, code, row)
    # The account's own ledger lines on its own tab (the screen's Ledger), running from the b/f
    lines = sorted((tx for tx in ctx.tx_rows if str(tx[1]) == str(code)), key=lambda tx: (_when(tx[0]) or date.min))
    _bank_ledger(ws, row, lines, f"({t['bf']})")
    refs: Dict[str, object] = {"bf": t["bf"], "adj": t["adj"], "jnl": t["jnl"], "cf": cf, "stmt": stmt, "diff": diff}
    ctx.schedule_cf[code] = (f"('{ws.title}'!E{t['cf_row']}-'{ws.title}'!D{t['cf_row']})", 1)
    return ws.title, label, code, refs


def _statement_ref(entered: dict):
    """The statement's date and page as typed on the screen ('31/03/2025, page 3'); None when neither was typed."""
    if entered.get("reference"):
        return entered["reference"]
    parts = []
    if entered.get("statement_date"):
        try:
            parts.append(date.fromisoformat(entered["statement_date"]).strftime("%d/%m/%Y"))
        except ValueError:
            parts.append(str(entered["statement_date"]))
    if entered.get("page"):
        parts.append(f"page {entered['page']}")
    return ", ".join(parts) or None


LEDGER_HEAD = ("Date", "Type", "No.", "Payee", "Description", "Receipt £", "Payment £", "VAT code", "Running balance £")


def _payee(description: str) -> str:
    """The payee: the ledger readers join a line's name and memo as 'Name - Memo'."""
    head, sep, _rest = (description or "").partition(" - ")
    return head.strip()[:60] if sep else ""


def _bank_ledger(ws, row: int, lines: List[tuple], bf_cell: str) -> int:
    """The account's GL lines: Date | Type | No. | Payee | Description | Receipt | Payment | VAT code |
    Running balance from the balance b/fwd; receipts and payments totalled gross (not netted). Returns the row after
    the totals, as _write_lines (the total row is two above it)."""
    ws.cell(row=row, column=1, value="Ledger lines this year (from the GL)").font = BOLD
    row += 1
    for c, text in enumerate(LEDGER_HEAD, 1):
        ws.cell(row=row, column=c, value=text).font = BOLD
    first = row + 1
    for tx in lines:
        row += 1
        when = _when(tx[0])
        cell = ws.cell(row=row, column=1, value=when or tx[0])
        if when:
            cell.number_format = "dd/mm/yyyy"
        description = (tx[5] or tx[4] or "")
        ws.cell(row=row, column=2, value=(tx[4] or None) if tx[4] != "GL" else None)
        ws.cell(row=row, column=3, value=tx[6] or None)
        ws.cell(row=row, column=4, value=_payee(description) or None)
        ws.cell(row=row, column=5, value=description[:120])
        if tx[7]:
            _money(ws.cell(row=row, column=6, value=round(tx[7], 2)))
        if tx[8]:
            _money(ws.cell(row=row, column=7, value=round(tx[8], 2)))
        if len(tx) > 10 and tx[10]:
            ws.cell(row=row, column=8, value=str(tx[10])[:30])
        prior = bf_cell if row == first else f"I{row - 1}"
        _money(ws.cell(row=row, column=9, value=f"=ROUND({prior}+F{row}-G{row},2)"))
    if not lines:
        row += 1
        ws.cell(row=row, column=2, value="No ledger lines this year")
        return row + 2
    row += 1
    ws.cell(row=row, column=5, value="Total receipts and payments (gross)").font = BOLD
    for c, col in ((6, "F"), (7, "G")):
        _money(ws.cell(row=row, column=c, value=f"=SUM({col}{first}:{col}{row - 1})"), bold=True, total=True)
    return row + 2


def _on(title: str, term: str) -> str:
    """A formula term written on an account tab, read from another tab: every cell reference gets the tab's name."""
    return re.sub(r"\b([A-Z]{1,2}\d+)\b", lambda m: f"'{title}'!{m.group(1)}", term)


def _bank_summary(ctx: Context, made: List[Tuple[str, str, int, Dict[str, object]]]) -> None:
    """F2 Bank summary, as the screen's: each bank and card with this year, last year,
    the balance per statement and the difference, then the total; the transfers between the client's own accounts."""
    if "F2-Bank" not in ctx.wb.sheetnames:
        return
    ws = ctx.wb["F2-Bank"]
    for r in range(6, max(ws.max_row, 30) + 1):
        for c in range(1, 10):
            _blank(ws.cell(row=r, column=c))
    ws["A4"] = "Bank summary"
    ws["A4"].font = TITLE
    heads = ["Particular", "Tab", "Current year £", "Previous year £", "Per statement £", "Difference £"]
    for c, h in enumerate(heads, 1):
        ws.cell(row=6, column=c, value=h).font = BOLD
    r = 7
    for title, label, code, refs in made:
        ws.cell(row=r, column=1, value=label[:40])
        ws.cell(row=r, column=2, value=title.split(" - ")[0])
        _money(ws.cell(row=r, column=3, value=f"={_on(title, refs['cf'])}"))
        _money(ws.cell(row=r, column=4, value=f"={_on(title, refs['bf'])}"))
        stmt = f"'{title}'!{refs['stmt']}"
        _money(ws.cell(row=r, column=5, value=f'=IF({stmt}="","",{stmt})'))
        _money(ws.cell(row=r, column=6, value=f"='{title}'!{refs['diff']}"))
        r += 1
    ws.cell(row=r, column=1, value="Total").font = BOLD
    for c in range(3, 6):
        col = get_column_letter(c)
        _money(ws.cell(row=r, column=c, value=f"=SUM({col}7:{col}{r - 1})"), bold=True, total=True)
    # Transfers between the client's own accounts, paired; the one-sided ones listed
    from backend.app.services.workbook.balance_tabs.transfers import add_transfers
    add_transfers(ctx, ws, r + 3)


def _bank_lead(ctx: Context, made: List[Tuple[str, str, int, Dict[str, object]]]) -> None:
    if "F1 (LEAD)" not in ctx.wb.sheetnames:
        return
    ws = ctx.wb["F1 (LEAD)"]
    for r in range(8, max(ws.max_row, 12) + 1):
        for c in range(1, 6):
            _blank(ws.cell(row=r, column=c))
    r = 8
    for title, label, code, refs in made:
        ws.cell(row=r, column=1, value=label[:40])
        ws.cell(row=r, column=3, value=title.split(" - ")[0])
        _money(ws.cell(row=r, column=4, value=f"={_on(title, refs['cf'])}"))
        _money(ws.cell(row=r, column=5, value=f"={_on(title, refs['bf'])}"))
        r += 1
    ws.cell(row=r + 1, column=1, value="Total").font = BOLD
    for c, col in ((4, "D"), (5, "E")):
        _money(ws.cell(row=r + 1, column=c, value=f"=SUM({col}8:{col}{r})"), bold=True, total=True)
    ws.cell(row=r + 2, column=1, value="Check: ETB banks and cash (must be nil)")
    _money(ws.cell(row=r + 2, column=4, value=f"=ROUND(D{r + 1}-({_etb(BANK_CODES, 'N')}),2)"))


# ------------------------------------------------------------------------------------------------------------------
# Loans and hire purchase: one tab per lender, and the G4 lead with the split
# ------------------------------------------------------------------------------------------------------------------
def _regular_payment(lines: List[tuple], period_end: date) -> float:
    """The amount paid most often in the last six months of the year (the monthly instalment)."""
    recent = [round(tx[7], 2) for tx in lines if tx[7] and (_when(tx[0]) or date.min) >= date(
        period_end.year - (1 if period_end.month <= 6 else 0), (period_end.month - 6 - 1) % 12 + 1, 1)]
    if not recent:
        recent = [round(tx[7], 2) for tx in lines if tx[7]]
    if not recent:
        return 0.0
    amount, times = Counter(recent).most_common(1)[0]
    if times >= 2:
        return amount
    # A loan whose instalment changes a little each month (interest on the falling balance): the typical payment
    return round(median(recent), 2) if len(recent) >= 2 else 0.0
