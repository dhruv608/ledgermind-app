"""Payroll month by month, shared by the workbook (G6 net wages, G6.2 summary, G7 PAYE / NI, G8 pension) and the
Payroll by month card on the VAT & payroll tab, so both show the same figures: what each control account was owed
each month (credits), what was paid or cleared (debits), the balance at each month end and a note when a month looks
wrong; and the payroll cost each month against what was owed out.

Ledger lines here are the workbook's rows: (date 'dd/mm/yyyy', code, type, account, source, description, ref, debit,
credit); approved journals are one line each: {"no", "code", "debit", "credit", "narrative"}."""

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from backend.app.services.mapping.chart_lookup import (DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM, NET_WAGES, PAYE_NIC,
                                                       account_name_keys)

Month = Tuple[int, int]

PENSION_NAME = re.compile(r"pension|nest\b|auto.?enrol", re.IGNORECASE)
EMPLOYMENT_ALLOWANCE = re.compile(r"employ(ment|er'?s?) allowance|\bEA\b", re.IGNORECASE)
EMPLOYER_NI_CODES = {"3001", "3011"}
PAYROLL_TEXT = re.compile(r"payroll|salary|salaries|wage|net pay|brightpay|sage payroll|staffology", re.I)
COST_COLS = [("Directors' pay", (3010, 3014, 3015)), ("Staff wages", (3000, 3004)),
             ("Employer NI", (3001, 3011)), ("Employer pension", (3002, 3003, 3012, 3013))]


def code_text(val: Any) -> str:
    """A journal line's code as the workbook writes it ('3000', never '3000.0'; blank -> '1999')."""
    if val is None or str(val).strip() == "":
        return "1999"
    try:
        return str(int(str(val).split(".")[0]))
    except (ValueError, TypeError):
        return str(val).strip()


def year_months(period_end: date) -> List[Month]:
    """The twelve months of the year, oldest first."""
    months: List[Month] = []
    y, m = period_end.year, period_end.month
    for _ in range(12):
        months.insert(0, (y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return months


def month_end(mo: Month) -> date:
    return date(mo[0], mo[1], calendar.monthrange(mo[0], mo[1])[1])


# Payroll is posted in two halves: the payroll journal (cost and liabilities) and the payments.
# A journal's debit on a payroll control account (a payslip line, a correction, a reclass to another control) is part
# of what the payroll owes, not a payment, so payslip values are not counted as paid; payments are the bank's lines
# (spend money, bill payment, bank). Sage writes journals as JD / JC.
JOURNAL_SOURCE = re.compile(r"journal|^\s*J[DC]\s*$", re.I)
# A journal that settles the pay through the director's loan account is a settlement: it stays a payment
# ... as does one that moves a payment posted to another account ('Move from NET Wages': an HMRC payment coded to net wages)
SETTLED_THROUGH_LOAN = re.compile(
    r"\bdirector|\bdla\b|\bloan\b|\bmove|\btransfer|\brecla|\bpaid\b|\bpayments?\b", re.I)


def journal_debit(tx: tuple) -> bool:
    """A debit on a payroll control account that the payroll journal makes, not a payment."""
    # Employment allowance has its own column on PAYE; posted to net wages or pension (e.g. 'Employment Allowance
    # Adjustment' debits on net wages) it is a misposting, not net pay, so it is left as the ledger has it
    text = f"{tx[5]} {tx[6]}"
    return bool(tx[7]) and bool(JOURNAL_SOURCE.search(f"{tx[4]}")) and not SETTLED_THROUGH_LOAN.search(text) \
        and not EMPLOYMENT_ALLOWANCE.search(text)


class LedgerMonths:
    """The ledger lines by month of the year."""

    def __init__(self, tx_rows: List[tuple], months: List[Month]):
        self.tx_rows, self.months = tx_rows, months
        self._month_set = set(months)
        self._seen: Dict[Any, Optional[Month]] = {}      # each date text worked out once (the tables ask ~140k times)

    def month_of(self, tx) -> Optional[Month]:
        text = tx[0]
        if text not in self._seen:
            try:
                d = datetime.strptime(text, "%d/%m/%Y")
                self._seen[text] = (d.year, d.month) if (d.year, d.month) in self._month_set else None
            except (TypeError, ValueError):
                self._seen[text] = None
        return self._seen[text]

    def monthly(self, select_line: Callable[[tuple], bool], credit_side: bool,
                journals_net: bool = False) -> Dict[Month, List[float]]:
        """Per month: [credits, debits] of the selected ledger lines (or debit-credit for costs). journals_net (a
        payroll control account): a journal's debit lowers what is owed that month instead of counting as paid."""
        out = {mo: [0.0, 0.0] for mo in self.months}
        for tx in self.tx_rows:
            mo = self.month_of(tx)
            if mo is None or not select_line(tx):
                continue
            if credit_side and journals_net and journal_debit(tx):
                out[mo][0] -= tx[7]
                continue
            out[mo][0] += tx[8] if credit_side else tx[7] - tx[8]
            out[mo][1] += tx[7] if credit_side else 0.0
        return out


def journal_debits(led: "LedgerMonths", select_line: Callable[[tuple], bool]) -> Dict[Month, float]:
    """Per month: the payroll journal's own debits on the selected control account (journal_debit)."""
    out = {mo: 0.0 for mo in led.months}
    for tx in led.tx_rows:
        mo = led.month_of(tx)
        if mo is not None and select_line(tx) and journal_debit(tx):
            out[mo] += tx[7]
    return out


def follow_report(per_month: Dict[Month, List[float]], debits: Dict[Month, float],
                  per_report: Optional[Dict[Month, float]]) -> Dict[Month, List[float]]:
    """The payroll report is the base for what the payroll owes. A month's journal debits are netted off what is owed
    (the payroll journal posts the liability); where the report shows the month without them (a correction the report
    does not hold), they are what was cleared instead, so the month agrees with the report. Without a report the
    netting stands."""
    if not per_report:
        return per_month
    out = {}
    for mo, (owed, paid) in per_month.items():
        d, rep = debits.get(mo, 0.0), per_report.get(mo)
        if d >= 0.005 and rep is not None and abs(owed - rep) >= 1 and abs(owed + d - rep) < 1:
            out[mo] = [round(owed + d, 2), round(paid + d, 2)]
        else:
            out[mo] = [owed, paid]
    return out


def by_codes(*codes: int) -> Callable[[tuple], bool]:
    wanted = {str(c) for c in codes}
    return lambda tx: tx[1] in wanted


def pension_accounts(tb_records: Iterable[Any]) -> Tuple[Set[str], List[str]]:
    """The pension accounts by name (5352, or an other-creditors account named pension / NEST) and their codes."""
    tb_records = list(tb_records)
    names = {t.raw_account_name for t in tb_records
             if t.std_code == 5352 or (t.std_code == 5350 and PENSION_NAME.search(t.raw_account_name or ""))}
    codes = sorted({str(t.std_code) for t in tb_records if t.raw_account_name in names})
    return names, codes


def pension_line(names: Set[str]) -> Callable[[tuple], bool]:
    keys = set().union(*(account_name_keys(n) for n in names)) if names else set()
    return lambda tx: any(k in keys for k in account_name_keys(tx[3]))


def series(led: LedgerMonths, pension_names: Set[str]) -> Dict[str, Any]:
    """The month-by-month figures every payroll table is made from."""
    dla_codes = {str(DIRECTORS_LOAN), str(DIRECTORS_LOAN_LONG_TERM)}
    return {
        "net_pay": led.monthly(by_codes(NET_WAGES), credit_side=True, journals_net=True),
        "paye": led.monthly(lambda tx: tx[1] == str(PAYE_NIC) and not EMPLOYMENT_ALLOWANCE.search(str(tx[5])),
                            credit_side=True, journals_net=True),
        "paye_allowance": {mo: v[0] for mo, v in led.monthly(
            lambda tx: tx[1] == str(PAYE_NIC) and EMPLOYMENT_ALLOWANCE.search(str(tx[5])), credit_side=False).items()},
        "pension": led.monthly(pension_line(pension_names), credit_side=True, journals_net=True),
        # A director's net pay posted straight to the director's loan account (always the DLA)
        "dla_pay": led.monthly(lambda tx: tx[1] in dla_codes and PAYROLL_TEXT.search(f"{tx[5]} {tx[6]}"),
                               credit_side=True),
        "costs": [led.monthly(by_codes(*codes), credit_side=False) for _, codes in COST_COLS],
    }


def journal_totals(journals: List[Dict[str, Any]], codes: Set[str]) -> Tuple[float, float]:
    """Approved adjusting journals on these accounts, as (credits, debits)."""
    cr = sum(float(j.get("credit") or 0) for j in journals if code_text(j.get("code")) in codes)
    dr = sum(float(j.get("debit") or 0) for j in journals if code_text(j.get("code")) in codes)
    return cr, dr


def journal_allowance(journals: List[Dict[str, Any]]) -> float:
    """Employment allowance booked by an adjusting journal: Dr PAYE/NI, Cr employer's NI in the same journal."""
    groups: Dict[Any, Dict[str, float]] = {}
    for j in journals:
        g = groups.setdefault(j.get("no"), {"paye_dr": 0.0, "ni_cr": 0.0})
        code = code_text(j.get("code"))
        if code == str(PAYE_NIC):
            g["paye_dr"] += float(j.get("debit") or 0)
        elif code in EMPLOYER_NI_CODES:
            g["ni_cr"] += float(j.get("credit") or 0)
    return sum(min(g["paye_dr"], g["ni_cr"]) for g in groups.values())


def allowance_journal_numbers(journals: List[Dict[str, Any]]) -> List[Any]:
    """The adjusting journals that book employment allowance (Dr PAYE / NI, Cr employer's NI), by number."""
    groups: Dict[Any, Set[str]] = {}
    for j in journals:
        code = code_text(j.get("code"))
        if code == str(PAYE_NIC) and float(j.get("debit") or 0):
            groups.setdefault(j.get("no"), set()).add("paye")
        elif code in EMPLOYER_NI_CODES and float(j.get("credit") or 0):
            groups.setdefault(j.get("no"), set()).add("ni")
    return [no for no, sides in groups.items() if sides == {"paye", "ni"}]


def closing_owed(tb_records: Iterable[Any], select_record) -> float:
    return -sum(float(t.net_amount or 0) for t in tb_records if select_record(t))


def opening_owed(tb_records: Iterable[Any], select_record, codes, opening_by_code: Dict[str, float]) -> float:
    """The b/fwd (as owed): the accounts' opening balances, else last year's TB by code (the ETB's opening)."""
    chosen = [t for t in tb_records if select_record(t)]
    if any(t.opening_amount is not None for t in chosen):
        return -sum(float(t.opening_amount or 0) for t in chosen)
    return -sum(float((opening_by_code or {}).get(str(c), 0.0)) for c in codes)


def other_entries(tb_records, per_month, select_record, opening: float, allowance=None) -> float:
    """What the monthly lines do not explain between the b/fwd and the closing balance: entries outside the twelve
    months, lines with no date, opening lines posted in the ledger."""
    year_net = sum(owed - paid for owed, paid in per_month.values()) - sum((allowance or {}).values())
    return round(closing_owed(tb_records, select_record) - opening - year_net, 2)


NOTE_NOTHING_POSTED = "Nothing posted this month"
NOTE_UNPAID = "More than this month's amount is unpaid"
NOTE_OVERPAID = "Paid more than was owed"
TOLERANCE = 1.0                    # pounds: rounding is not a difference
OVERPAID_GRACE_MONTHS = 2          # an overpayment that clears within this many month ends is timing


def month_rows(months: List[Month], per_month, opening: float, allowance=None,
               allowance_journal: float = 0.0) -> Tuple[List[Dict[str, Any]], int]:
    """Each month's owed, employment allowance, paid, running balance and note; and how many months have a note.

    An overpayment (the running balance below nil) is noted only when it lasts: one that clears within the next
    OVERPAID_GRACE_MONTHS month ends is timing (the pay sent before the payroll journal was posted); one still there
    then, or at the year end, is noted."""
    ea_months = allowance or {}
    ea_left = sum(ea_months.values()) + allowance_journal
    rows, running = [], opening
    anything_posted = any(abs(per_month[x][0]) >= 0.005 for x in months)
    for mo in months:
        owed, paid = per_month[mo]
        ea = ea_months.get(mo, 0.0)
        ea_left -= ea
        running += owed - ea - paid
        rows.append({"month": mo, "owed": owed, "allowance": ea, "paid": paid, "balance": running,
                     "nothing_posted": abs(owed) < 0.005 and anything_posted,
                     "unpaid": running > owed + max(ea_left, 0.0) + TOLERANCE,
                     "overpaid": running < -TOLERANCE})
    for i, row in enumerate(rows):
        later = rows[i + 1:i + 1 + OVERPAID_GRACE_MONTHS]
        lasting = row["overpaid"] and not any(r["balance"] >= -TOLERANCE for r in later)
        row["note"] = (NOTE_NOTHING_POSTED if row["nothing_posted"] else NOTE_UNPAID if row["unpaid"]
                       else NOTE_OVERPAID if lasting else None)
    flags = sum(1 for row in rows if row["note"])
    return rows, flags


# ----------------------------------------------------------------------------------------------------------------
# Status of each month's liability: payments matched by date, not only within the month.
# Net pay is paid on the pay date (the month end or the first days of the next); PAYE / NI and pension are due by the
# 22nd of the next month; a quarterly PAYE payer pays by the 22nd after the quarter (tax quarters to 5 July, October,
# January, April). Payments clear the oldest amount owed first, the balance brought forward before this year's months.
# ----------------------------------------------------------------------------------------------------------------
DUE_DAY = 22
NET_PAY_DAYS = 7               # net pay paid within the first week of the next month is on time
QUARTER_ENDS = (3, 6, 9, 12)   # calendar months closing a PAYE quarter (the tax quarter ends on the 5th after)
MATCH_TOLERANCE = 1.0          # a payment within £1 of a month's amount is that month's
MATCH_WINDOW_DAYS = 60         # ...when made between the month's start and 60 days after it was due
LATER_GRACE_DAYS = 21          # next year's payments counted for the year's months: to 3 weeks after the last due date
PAID_ON_TIME, PAID_LATE, PART_PAID, NOT_PAID, DUE_LATER = (
    "Paid on time", "Paid late", "Part paid", "Not paid", "Due after year end")


def dated_payments(tx_rows: Iterable[tuple], select_line: Callable[[tuple], bool]) -> List[Tuple[date, float]]:
    """The selected payroll control lines' payments (their debits, not the payroll journal's own) with their dates,
    oldest first."""
    out = []
    for tx in tx_rows:
        if not select_line(tx) or not tx[7] or journal_debit(tx):
            continue
        try:
            when = datetime.strptime(tx[0], "%d/%m/%Y").date()
        except (TypeError, ValueError):
            continue
        out.append((when, float(tx[7])))
    return sorted(out)


def pays_quarterly(payments: List[Tuple[date, float]], months_owed: int) -> bool:
    """A quarterly PAYE payer: owed most months but paid in at most five months, at least two months apart, mostly in
    the month after a quarter (January, April, July, October: due by the 22nd). A monthly payer who missed a few
    months pays in other months too."""
    paid_months = sorted({(d.year, d.month) for d, _ in payments})
    if months_owed < 6 or not 2 <= len(paid_months) <= 5:
        return False
    gaps = [(b[0] - a[0]) * 12 + b[1] - a[1] for a, b in zip(paid_months, paid_months[1:])]
    after_quarter = sum(1 for _, m in paid_months if m in (1, 4, 7, 10))
    return all(g >= 2 for g in gaps) and after_quarter >= 0.75 * len(paid_months)


def due_date(mo: Month, kind: str, quarterly: bool = False) -> date:
    """When a month's liability should be paid: kind 'net' (net pay), 'paye' or 'pension'."""
    if kind == "net":
        end = month_end(mo)
        return date.fromordinal(end.toordinal() + NET_PAY_DAYS)
    y, m = mo
    if kind == "paye" and quarterly:
        m = next(q for q in QUARTER_ENDS if q >= m)
    y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return date(y, m, DUE_DAY)


def next_year_rows(engagement_id: str, db) -> List[tuple]:
    """Next year's ledger lines, in the ledger row shape the selectors above read, so the same accounts are
    picked out (empty when none was uploaded)."""
    if db is None:
        return []
    from backend.app.services.ingestion.next_year import next_year_lines
    return [(l.when.strftime("%d/%m/%Y"), str(l.code) if l.code is not None else "", "", l.account, l.source,
             l.description, l.reference, l.debit, l.credit) for l in next_year_lines(str(engagement_id), db)]


def month_status(months: List[Month], per_month, opening: float, payments: List[Tuple[date, float]], kind: str,
                 period_end: date, allowance=None, later: List[Tuple[date, float]] = ()) -> Dict[Month, Tuple[date, str]]:
    """Each month's (due date, status) for the months with something owed. A payment of a month's amount (within £1)
    made from that month to 60 days after its due date settles that month (matched by amount within a window, so a
    skipped month stays the unpaid one, not the latest); the other payments, oldest first, clear the balance brought
    forward and then each month in turn. later: payments in next year's ledger, when uploaded: a month they clear says
    so, with the date, as evidence of what was owed at the year end."""
    own = list(payments)
    ea = allowance or {}
    owed = [(None, max(opening, 0.0))] + [(mo, max(per_month[mo][0] - ea.get(mo, 0.0), 0.0)) for mo in months]
    quarterly = kind == "paye" and pays_quarterly(own, sum(1 for _, v in owed[1:] if v >= 1))
    # Next year's payments up to three weeks after the year's last due date: later ones pay next year's own months
    if later and months:
        cutoff = due_date(max(months), kind, quarterly) + timedelta(days=LATER_GRACE_DAYS)
        payments = sorted(own + [p for p in later if period_end < p[0] <= cutoff])
    covered: Dict[Any, float] = {key: 0.0 for key, _ in owed}
    cleared_on: Dict[Any, date] = {}
    # 1. Payments that are one month's amount, inside that month's window
    matched = set()
    if not quarterly:
        for i, (when, amount) in enumerate(payments):
            fits = [(abs((when - due_date(mo, kind)).days), mo, due_amount) for mo, due_amount in owed[1:]
                    if due_amount >= 1 and mo not in cleared_on and abs(amount - due_amount) <= MATCH_TOLERANCE
                    and date(mo[0], mo[1], 1) <= when <= due_date(mo, kind) + timedelta(days=MATCH_WINDOW_DAYS)]
            if fits:                    # the month whose due date the payment is closest to (equal salaries)
                _, mo, due_amount = min(fits)
                cleared_on[mo], covered[mo] = when, due_amount
                matched.add(i)
    # 2. The rest, oldest owed first
    queue = [[key, amount] for key, amount in owed if amount >= 0.005 and key not in cleared_on]
    for i, (when, amount) in enumerate(payments):
        if i in matched:
            continue
        left = amount
        while left > 0.005 and queue:
            key, still = queue[0]
            used = min(left, still)
            covered[key] += used
            left -= used
            queue[0][1] -= used
            if queue[0][1] <= 0.005:
                cleared_on[key] = when
                queue.pop(0)
    out: Dict[Month, Tuple[date, str]] = {}
    for mo, amount in owed[1:]:
        if amount < 1:
            continue
        due = due_date(mo, kind, quarterly)
        if mo in cleared_on and cleared_on[mo] > period_end:
            status = (f"{DUE_LATER if due > period_end else NOT_PAID}: paid {cleared_on[mo]:%d/%m/%Y} "
                      f"(next year's ledger{', late' if cleared_on[mo] > due else ''})")
        elif mo in cleared_on:
            status = PAID_ON_TIME if cleared_on[mo] <= due else PAID_LATE
        elif covered[mo] >= 0.5:
            status = PART_PAID
        else:
            status = DUE_LATER if due > period_end else NOT_PAID
        out[mo] = (due, status)
    return out


# ----------------------------------------------------------------------------------------------------------------
# The screen: the same tables from the database, as the workbook would build them now
# ----------------------------------------------------------------------------------------------------------------
def _inputs(engagement, db):
    """The ledger rows, approved journals and last year's balances by code, as the workbook build makes them."""
    from sqlalchemy import select
    from backend.app.models.database import GLTransaction, ProposedJournal, TBRecord
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.review.last_year import prior_balances_by_code

    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    gl_codes = ChartLookup.gl_account_codes(tb_records)
    tx_rows = []
    for tx in db.execute(select(GLTransaction).where(GLTransaction.engagement_id == engagement.id)).scalars():
        acc = tx.raw_account_name or ""
        tx_rows.append((tx.transaction_date.strftime("%d/%m/%Y") if tx.transaction_date else "",
                        next((str(gl_codes[k]) for k in account_name_keys(acc) if k in gl_codes), ""), "", acc,
                        tx.source or "GL", tx.description or "", tx.reference or "",
                        float(tx.debit_amount or 0.0), float(tx.credit_amount or 0.0)))
    journals: List[Dict[str, Any]] = []
    approved = db.execute(select(ProposedJournal).where(ProposedJournal.engagement_id == engagement.id,
                                                        ProposedJournal.status == "APPROVED")
                          .order_by(ProposedJournal.id)).scalars().all()
    for i, j in enumerate(approved, start=1):
        if j.lines:
            journals += [{"no": i, "code": str(l.account_code), "debit": float(l.debit) if l.debit else None,
                          "credit": float(l.credit) if l.credit else None} for l in j.lines]
        else:
            journals += [{"no": i, "code": str(j.debit_code), "debit": float(j.amount), "credit": None},
                         {"no": i, "code": str(j.credit_code), "debit": None, "credit": float(j.amount)}]
    opening_by_code: Dict[str, float] = {}
    for t in tb_records:
        if t.opening_amount is not None:
            k = code_text(t.std_code)
            opening_by_code[k] = opening_by_code.get(k, 0.0) + float(t.opening_amount)
    if not opening_by_code:
        prior = prior_balances_by_code(engagement, db)
        this_year: Dict[int, float] = {}
        for t in tb_records:
            if t.std_code is not None:
                this_year[t.std_code] = this_year.get(t.std_code, 0.0) + float(t.net_amount or 0.0)
        repeated = sum(1 for c, v in prior.items() if abs(v) >= 1 and abs(this_year.get(c, 0.0) - v) < 0.01)
        if prior and repeated < 2:
            opening_by_code = {code_text(c): v for c, v in prior.items() if abs(v) >= 0.005}
    return tb_records, tx_rows, journals, opening_by_code


def payroll_by_month(engagement, db) -> Dict[str, Any]:
    """Net wages, PAYE / NI and pension month by month, and the payroll cost against what was owed out."""
    tb_records, tx_rows, journals, opening_by_code = _inputs(engagement, db)
    codes = {code_text(t.std_code) for t in tb_records if t.std_code is not None}
    months = year_months(engagement.period_end_date)
    led = LedgerMonths(tx_rows, months)
    pension_names, pension_codes = pension_accounts(tb_records)
    s = series(led, pension_names)
    iso = lambda mo: month_end(mo).isoformat()

    def table(key, title, per_month, select, opening, journal, allowance=None, allowance_journal=0.0):
        rows, flags = month_rows(months, per_month, opening, allowance, allowance_journal)
        other = other_entries(tb_records, per_month, select, opening, allowance)
        closing = closing_owed(tb_records, select)
        jnl_net = round(journal[0] - journal[1] - allowance_journal, 2)
        return {"key": key, "title": title, "opening": round(opening, 2), "flags": flags + bool(abs(other) >= 0.005),
                "with_allowance": allowance is not None,
                "months": [{**r, "month": iso(r["month"]), **{k: round(r[k], 2) for k in
                                                              ("owed", "allowance", "paid", "balance")}} for r in rows],
                "other": other, "journals": jnl_net, "allowance_journal": round(allowance_journal, 2),
                "closing": round(closing + jnl_net, 2), "tb_closing": round(closing, 2)}

    tables = []
    if codes & {"5330", "2220", "3000", "3010"}:
        sel = lambda t: t.std_code == NET_WAGES
        op = opening_owed(tb_records, sel, [NET_WAGES], opening_by_code)
        tables.append(table("net_wages", "Net wages", s["net_pay"], sel, op, journal_totals(journals, {str(NET_WAGES)})))
    if codes & {"5320", "2210"}:
        sel = lambda t: t.std_code == PAYE_NIC
        op = opening_owed(tb_records, sel, [PAYE_NIC], opening_by_code)
        ea_journal = journal_allowance(journals)
        cr, dr = journal_totals(journals, {str(PAYE_NIC)})
        tables.append(table("paye", "PAYE / NI", s["paye"], sel, op, (cr, dr - ea_journal),
                            allowance=s["paye_allowance"], allowance_journal=ea_journal))
    if pension_names:
        sel = lambda t: t.raw_account_name in pension_names
        shared = any(str(t.std_code) in pension_codes and t.raw_account_name not in pension_names for t in tb_records)
        if shared:
            op = -sum(float(t.opening_amount or 0) for t in tb_records if sel(t))
            jnl = (0.0, 0.0)
        else:
            op = opening_owed(tb_records, sel, pension_codes, opening_by_code)
            jnl = journal_totals(journals, set(pension_codes))
        tables.append(table("pension", "Pension", s["pension"], sel, op, jnl))

    # Payroll cost against what was owed out (G6.2), only when there is payroll at all
    summary = None
    if tables:
        has_net_wages = any(abs(s["net_pay"][mo][0]) >= 0.01 for mo in months)
        rows = []
        for mo in months:
            cost = [round(c[mo][0], 2) for c in s["costs"]]
            owed = {"net_pay": round(s["net_pay"][mo][0], 2),
                    "paye": round(s["paye"][mo][0] - s["paye_allowance"][mo], 2),
                    "pension": round(s["pension"][mo][0], 2)}
            gap = round(sum(cost) - sum(owed.values()), 2)
            via_dla = round(s["dla_pay"][mo][0], 2)
            settled = via_dla if abs(gap) >= 1 and via_dla and abs(gap - via_dla) < 1 else 0.0
            rows.append({"month": iso(mo), "costs": cost, "total_cost": round(sum(cost), 2), **owed,
                         "total_owed": round(sum(owed.values()), 2), "difference": gap, "via_dla": settled,
                         "unexplained": round(gap - settled, 2) if has_net_wages else None})
        summary = {"cost_names": [n for n, _ in COST_COLS], "has_net_wages": has_net_wages, "months": rows,
                   "flags": sum(1 for r in rows if r["unexplained"] is not None and abs(r["unexplained"]) >= 1)}
    return {"tables": tables, "summary": summary}
