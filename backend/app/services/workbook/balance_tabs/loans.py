"""Loans and hire purchase: one tab per lender (G4.n) and the G4 lead with the split within / after one year."""

from collections import Counter
from typing import Dict, List, Optional, Tuple
from types import SimpleNamespace
from backend.app.services.mapping.chart_lookup import account_name_keys
from datetime import date
import re

from backend.app.services.workbook.balance_tabs.bank import _regular_payment
from backend.app.services.workbook.balance_tabs.leads import _journals_on
from backend.app.services.workbook.balance_tabs.t_shape import account_lines, write_t
from backend.app.services.workbook.balance_tabs.common import (
    BOLD, BROUGHT_FORWARD, CHECK_FILL, Context, LOANS_AFTER_1_YEAR, on_tab, LOANS_WITHIN_1_YEAR, TITLE, _etb, _has_balance,
    _input, _lines_for, _money, _movement_label, _new_sheet, _records, _sheet_title, _ttb_account, _when,
    _write_lines
)


# The kind of finance a code holds: accounts of one loan are only put together within the same kind
LOAN_KIND = {**dict.fromkeys((5000, 5001, 5002, 5005, 5006, 5007), "hire purchase"),
             **dict.fromkeys((5010, 5011, 5012, 5015, 5016, 5017), "finance leases"),
             **dict.fromkeys((5100, 5500), "bank loans"), **dict.fromkeys((5110, 5510), "other loans"),
             **dict.fromkeys((5120, 5520), "debentures"), **dict.fromkeys(range(5350, 5360), "other loans")}
# Words that only say where in the accounts a balance sits ('Bank loans < 1 year', 'Brought forward: ...')
PERIOD_WORDS = re.compile(r"brought forward:|creditors?:|[<>()]|\b(?:less|more|than|between|after|within|due|over|"
                          r"under|and|one|five|years?|yrs?|short|long|term|current|non|liabilit\w*|creditors?)\b|"
                          r"\b[15]\b", re.I)


# Loans kept on other creditors (5350, and the firm's 5351-5359): shown on G4 with the other loans
CREDITOR_LOAN_CODES = list(range(5350, 5360))
LOAN_NAME = re.compile(r"\b(?:loans?|mortgages?|invoice (?:finance|discounting)|factoring)\b", re.I)
NOT_A_LOAN = re.compile(r"\b(?:director|directors|dla|staff|employees?|student|interest|fees?|charges?|repayable to us|"
                        r"to\s+(?:the\s+)?(?:director|staff|employee))\b", re.I)
# Ledger accounts that are loans owed (their opening balance is used when the TB leaves it out)
GL_LOAN_NAME = re.compile(r"\b(?:loans?|mortgages?|hire purchase|hp|bbls?|cbils?|bounce ?back|finance)\b", re.I)
HP_NAME = re.compile(r"\b(?:hire purchase|hp)\b", re.I)
DEBTOR_NAME = re.compile(r"debtors?|receivable|\bto\b", re.I)
# A loan account named only by its kind
GENERIC_LOAN = re.compile(r"(?:bank |other )?(?:loans?|hire purchase|hp|finance leases?|debentures?)?")


def _loan_key(name: str) -> str:
    """A loan account's name without the period words: 'Bank loans < 1 year' and 'Bank loans > 1 year' are one."""
    return re.sub(r"[^a-z0-9]+", " ", PERIOD_WORDS.sub(" ", (name or "").lower())).strip()


def _loan_groups(records: list, closing_of, has_lines) -> List[list]:
    """The loan accounts put together per loan, in the TB's order. Accounts of one kind join when
    (a) their names differ only by the period words (the < 1 year and > 1 year halves of one loan), or
    (b) some went negative (repayments with no opening balance) while last year's balances sit, unmoved, on others:
        last year's balance was kept on a code, not per lender, so they are shown together."""
    groups: List[list] = []
    by_key: Dict[Tuple[str, str], list] = {}
    for t in records:
        kind = LOAN_KIND.get(t.std_code, str(t.std_code))
        key = (kind, _loan_key(t.raw_account_name))
        if key[1] and key in by_key:
            by_key[key].append(t)
            continue
        g = [t]
        groups.append(g)
        by_key[key] = g
    total = lambda g: sum(closing_of(t) for t in g)
    for kind in {LOAN_KIND.get(t.std_code, str(t.std_code)) for t in records}:
        same = [g for g in groups if LOAN_KIND.get(g[0].std_code, str(g[0].std_code)) == kind]
        negative = [g for g in same if total(g) < -0.005]
        unmoved = [g for g in same if total(g) > 0.005 and not any(has_lines(t) for t in g)]
        # Only a balance not tied to a lender ('Brought forward: ...', 'Bank loans < 1 year'), or the kind's one
        # unmoved lender: with several named lenders it is not known whose balance it is
        generic = [g for g in unmoved if all(BROUGHT_FORWARD.search(t.raw_account_name or "")
                                             or GENERIC_LOAN.fullmatch(_loan_key(t.raw_account_name)) for t in g)]
        unmoved = generic or (unmoved if len(unmoved) == 1 else [])
        if negative and unmoved:
            joining = {id(g) for g in negative + unmoved}
            first = min(i for i, g in enumerate(groups) if id(g) in joining)
            merged = [t for g in groups if id(g) in joining for t in g]
            groups = [g for g in groups if id(g) not in joining]
            groups.insert(min(first, len(groups)), merged)
    return groups


def _monthly_rate(lines: List[tuple], payment: float, since: date) -> Optional[float]:
    """The loan's interest rate a month, from the interest the lender charges to the account each month: interest falls
    each month by the rate times the capital repaid (I1 - I2 = r x (payment - I1)), so r = (I1 - I2) / (payment - I1).
    At least three months in a row, the rates within 20% of each other and below 3% a month; else None."""
    if not payment:
        return None
    charges = sorted(((_when(tx[0]), tx[8]) for tx in lines if tx[8] and 0 < tx[8] < payment
                      and (_when(tx[0]) or date.min) > since), key=lambda x: x[0] or date.min)
    by_month: Dict[Tuple[int, int], float] = {}
    for when, amount in charges:
        if when is not None:
            by_month[(when.year, when.month)] = by_month.get((when.year, when.month), 0.0) + amount
    months = sorted(by_month)
    rates = []
    for (y1, m1), (y2, m2) in zip(months, months[1:]):
        if (y2 * 12 + m2) - (y1 * 12 + m1) != 1:
            continue
        i1, i2 = by_month[(y1, m1)], by_month[(y2, m2)]
        if i1 > i2 and payment > i1:
            rates.append((i1 - i2) / (payment - i1))
    if len(rates) < 2:
        return None
    rates.sort()
    mid = rates[len(rates) // 2]
    if not 0 < mid < 0.03 or rates[0] < 0.8 * mid or rates[-1] > 1.2 * mid:
        return None
    return mid


def _capital_in_twelve(balance: float, payment: float, rate: float) -> float:
    """The capital the next twelve monthly payments repay at the rate (an amortisation schedule), up to the balance."""
    due = 0.0
    for _ in range(12):
        capital = min(payment - balance * rate, balance)
        if capital <= 0:
            break
        due += capital
        balance -= capital
    return round(due, 2)


def _share_last_year(last_year: Dict[str, float], records: list, opening_of, unallocated: Dict[int, float]):
    """Last year's balance kept by code only (a 'Brought forward: ...' line, or the code's opening with several lenders
    on it) shared out to the lenders by last year's working paper: each lender named there, with no opening of its own,
    takes its balance at last year's end from the same kind of finance, never more than last year's TB holds (the TB
    decides the openings). Returns ({id(account): debit + added to its opening and closing},
    {id(account): (lender as last year's paper names it, amount)}); unallocated is reduced in place."""
    shift: Dict[int, float] = {}
    from_wp: Dict[int, Tuple[str, float]] = {}
    if not last_year:
        return shift, from_wp
    pools = [[t, -opening_of(t)] for t in records if BROUGHT_FORWARD.search(t.raw_account_name or "")
             and -opening_of(t) >= 0.005]                       # owed +
    pools += [[code, -bal] for code, bal in unallocated.items() if -bal >= 0.005]
    if not pools:
        return shift, from_wp
    kind = lambda code: LOAN_KIND.get(code, str(code))
    lenders = [t for t in records if not BROUGHT_FORWARD.search(t.raw_account_name or "")
               and abs(opening_of(t)) < 0.005]
    from backend.app.services.loans.agreements import link
    names = list(last_year)
    pairs = link([(SimpleNamespace(lender=n), None) for n in names],
                 [_loan_key(re.sub(r"^(?:\s*\d{3,5}\s*[-:]?)+\s*", "", t.raw_account_name or "")) for t in lenders])
    for i, j in sorted(pairs.items()):
        t, want = lenders[j], last_year[names[i]]
        # The same code's balance first, then the kind's
        for pool in sorted((p for p in pools if kind(p[0] if isinstance(p[0], int) else p[0].std_code) == kind(t.std_code)),
                           key=lambda p: (p[0] if isinstance(p[0], int) else p[0].std_code) != t.std_code):
            take = round(min(want, pool[1]), 2)
            if take < 0.005:
                continue
            pool[1] = round(pool[1] - take, 2)
            want = round(want - take, 2)
            shift[id(t)] = round(shift.get(id(t), 0.0) - take, 2)
            if isinstance(pool[0], int):
                unallocated[pool[0]] = round(unallocated[pool[0]] + take, 2)
            else:
                shift[id(pool[0])] = round(shift.get(id(pool[0]), 0.0) + take, 2)
            if want < 0.005:
                break
        if id(t) in shift:
            from_wp[id(t)] = (names[i], round(-shift[id(t)], 2))
    for code in [c for c, v in unallocated.items() if abs(v) < 0.005]:
        del unallocated[code]
    return shift, from_wp


def loan_tabs(ctx: Context) -> List[str]:
    codes = LOANS_WITHIN_1_YEAR + LOANS_AFTER_1_YEAR
    in_creditors = [t for t in _records(ctx, CREDITOR_LOAN_CODES)
                    if LOAN_NAME.search(t.raw_account_name or "") and not NOT_A_LOAN.search(t.raw_account_name or "")
                    and (abs(float(t.net_amount or 0)) >= 0.005 or abs(float(t.opening_amount or 0)) >= 0.005)]
    records = [t for t in _records(ctx, codes)] + in_creditors
    per_record_openings = any(t.opening_amount is not None for t in records)

    # Opening balances in the ledger that the TB leaves out (a TB of this year's movement only, with opening
    # balances that did not add up): each loan's balance brought forward still comes from them
    missing: Dict[int, float] = {}
    owed = {a: (v, in_tb) for a, (v, in_tb) in ctx.gl_openings.items()
            if v < -0.005 and GL_LOAN_NAME.search(a) and not NOT_A_LOAN.search(a) and not DEBTOR_NAME.search(a)}
    by_key = {k: a for a in owed for k in account_name_keys(a)}
    for t in records:
        a = next((by_key[k] for k in account_name_keys(t.raw_account_name) if k in by_key), None)
        if a in owed and not float(t.opening_amount or 0.0):
            missing[id(t)] = owed.pop(a)[0]
    tb_openings = [float(t.opening_amount or 0.0) for t in records if abs(float(t.opening_amount or 0.0)) >= 0.005]
    for a, (v, in_tb) in owed.items():
        if not in_tb and any(abs(v - o) < 1.0 for o in tb_openings):
            continue                     # the same balance on a TB loan under this year's name (a renamed account)
        if not in_tb:                    # in the ledger only: no movement this year, so not in the TB at all
            gl_only = SimpleNamespace(raw_account_name=a, std_code=5000 if HP_NAME.search(a) else 5500,
                                      net_amount=0.0, opening_amount=None)
            records.append(gl_only)
            missing[id(gl_only)] = v
    if not _has_balance(ctx, codes) and not in_creditors and not missing:
        return []
    count = Counter(t.std_code for t in records)
    closing_of = lambda t: -(float(t.net_amount or 0.0) + missing.get(id(t), 0.0))     # owed +

    def opening_of(t) -> float:          # debit + (a loan owed is negative)
        if id(t) in missing:
            return missing[id(t)]
        if per_record_openings or t.std_code in CREDITOR_LOAN_CODES:     # 5350 also holds other creditors
            return float(t.opening_amount or 0.0)
        return ctx.opening_by_code.get(str(t.std_code), 0.0) if count[t.std_code] == 1 else 0.0

    # Last year's balances by code not tied to one lender (several lenders on the code, opening by code only)
    unallocated: Dict[int, float] = {}
    if not per_record_openings:
        for c in codes:
            bal = ctx.opening_by_code.get(str(c), 0.0)
            if abs(bal) >= 0.005 and count[c] != 1:
                unallocated[c] = bal

    # Each lender's share of a balance last year's TB keeps by code only, from last year's working paper
    shift, from_wp = _share_last_year(ctx.last_year_loans, records, opening_of, unallocated)
    if shift:
        base_closing, base_opening = closing_of, opening_of
        closing_of = lambda t: base_closing(t) - shift.get(id(t), 0.0)
        opening_of = lambda t: base_opening(t) + shift.get(id(t), 0.0)

    made: List[Tuple[str, list, list]] = []      # (tab, accounts, codes whose journals the tab takes)
    brought_forward: List[object] = []
    after = ["G3.2 - Related parties", "G3.1 - DLA-NL Transactions", "G3- DLA", "G2.3 - Duplicates review",
             "G1 (LEAD)"]
    lead_title = "G4 - Loans & HP"
    active = [t for t in records if abs(float(t.net_amount or 0)) >= 0.005 or abs(opening_of(t)) >= 0.005]
    lines_of = {id(t): _lines_for(ctx, [t.raw_account_name]) for t in active}
    groups = _loan_groups(active, closing_of, lambda t: bool(lines_of[id(t)]))
    # Each agreement on the loans register to its loan, by the lender's name
    from backend.app.services.loans.agreements import link
    linked = {j: i for i, j in link(ctx.agreements, [" ".join(x.raw_account_name for x in g) for g in groups]).items()}
    for gi, g in enumerate(groups):
        if len(g) == 1 and BROUGHT_FORWARD.search(g[0].raw_account_name or ""):
            brought_forward.append(g[0])     # last year's TB balance carried in under the code: on the lead only
            continue
        t = g[0]
        named = [x.raw_account_name for x in g if _loan_key(x.raw_account_name) and not BROUGHT_FORWARD.search(x.raw_account_name)]
        label = " / ".join(dict.fromkeys(named or [x.raw_account_name for x in g]))
        ref = f"G4.{len(made) + 1}"
        ws = _new_sheet(ctx, _sheet_title(ctx.wb, ref, label), after if not made else [made[-1][0]])
        ws["E1"] = ref
        # The firm's code and name first, then the client's own account name, so the two never read as one heading
        own = re.sub(r"^\d{3,5}\s*[-:]\s*", "", t.raw_account_name or "").strip()
        firm = ctx.account_name(t.std_code)
        ws["A4"] = ((f"{t.std_code} {firm}" + (f": client account '{own}'" if own and own.lower() != (firm or "").lower() else ""))
                    if len(g) == 1 else
                    f"{', '.join(str(c) for c in dict.fromkeys(x.std_code for x in g))}: client accounts {label}")[:200]
        ws["A4"].font = TITLE
        # The loan as one T with its lines named, as the screen shows it, from the lender's
        # own accounts in the TB (two lenders may share a code): b/f, the year's lines by name (the GL by account),
        # what of the TB's movement the ledger does not hold, the journals on it by name, the c/d. The journals and the
        # check against B1-ETB need the loan's codes to be its own; on a shared code the journals stay on G4
        own_codes = sorted({x.std_code for x in g})
        sole = all(c not in CREDITOR_LOAN_CODES and count[c] == sum(1 for x in g if x.std_code == c) for c in own_codes)
        lines = sorted((tx for x in g for tx in lines_of[id(x)]), key=lambda tx: (_when(tx[0]) or date.min))
        shared = [from_wp[id(x)] for x in g if id(x) in from_wp]
        opening = round(sum(opening_of(x) for x in g), 2)                 # debit + (a loan owed is negative)
        bf_ref = ((f"this lender's share per last year's working paper ('{shared[0][0]}'): last year's TB keeps it by "
                   f"code")[:120] if shared else "last year's filed TB" if ctx.tb_kind else "opening balance")
        t_rows = [("Opening balance b/f", bf_ref, max(opening, 0.0), max(-opening, 0.0), "bf")]
        # The year's movement per the TB, owed + (a closing TB holds the balance itself: less the b/f)
        moved = "+".join(f"({_ttb_account(x.std_code, x.raw_account_name, 'G')}-{_ttb_account(x.std_code, x.raw_account_name, 'F')})"
                         for x in g) + (f"-({-opening})" if ctx.tb_kind == "closing" else "")
        named = account_lines(ctx, sorted({tx[3] for tx in lines})) if ctx.tb_kind else []
        if named:
            # The named lines' own cells, debit + (the T writes its lines from row 7: the b/f, then these). Copying
            # their formulas in here would pass Excel's 8,192-character limit for a lender with many accounts, and
            # Excel would then repair the file and drop every figure
            first = 7 + len(t_rows)
            t_rows += named
            gl_net = "+".join(f"(D{first + i}-E{first + i})" for i in range(len(named)))
            rest = f"(-({moved}))-({gl_net})"
            t_rows.append(("TB not in the ledger", "TB less the ledger", f"=ROUND(MAX(0,{rest}),2)",
                           f"=ROUND(MAX(0,-({rest})),2)", "tb"))
        else:
            label = f"{_movement_label(ctx)} (new loan and interest less repayments)"
            t_rows.append((label, "TB", f"=MAX(0,-({moved}))", f"=MAX(0,{moved})", "mv"))
        jnl_named = _journals_on(ctx, own_codes) if sole else []
        for no, text in jnl_named:
            net = "+".join(f"SUMIFS('B2-Journals'!$F:$F,'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{c})"
                           f"-SUMIFS('B2-Journals'!$G:$G,'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{c})" for c in own_codes)
            t_rows.append((f"Journal {no}: {text}"[:90], "B2", f"=MAX(0,{net})", f"=MAX(0,-({net}))", "jnl"))
        if not jnl_named:
            t_rows.append(("Adjusting journals" if sole else "Adjusting journals: on G4 (the code holds other loans too)",
                           "B2", f"={_etb(own_codes, 'J')}" if sole else 0, f"={_etb(own_codes, 'K')}" if sole else 0, "jnl"))
        check_etb = sole and not any(id(x) in missing for x in g)
        t = write_t(ctx, ws, t_rows, 6, True, (lambda closing, _term: [(
            "Check: balance c/d v B1-ETB final balance (must be nil)",
            f"=ROUND({closing}-({_etb(own_codes, 'N')}),2)")]) if check_etb else None)
        cf_s = t["cf_s"]                                                  # still owed +
        # The lender's year-end statement (each loan matched to its lender's statement): as typed on
        # the control accounts screen, else a cell to type it; the difference is the interest not charged, or a
        # payment to find (point U-LOAN-004 / 006)
        from backend.app.services.reconciliation.control_accounts import statement_balance
        typed = statement_balance(ctx.statements.get(f"code:{own_codes[0]}")) if sole and len(own_codes) == 1 else None
        r0 = t["end"] + 2
        ws[f"A{r0}"] = "Reconciliation"
        ws[f"A{r0}"].font = BOLD
        ws[f"B{r0 + 1}"] = "Per lender statement at the year end (E: books less statement, nil when agreed)"
        _input(ws[f"D{r0 + 1}"], abs(typed) if typed is not None else None)
        ws[f"E{r0 + 1}"] = f'=IF(D{r0 + 1}="","",ROUND({cf_s}-D{r0 + 1},2))'
        _money(ws[f"E{r0 + 1}"])
        ws[f"E{r0 + 1}"].fill = CHECK_FILL
        s0 = r0 + 3                                                       # the split
        within_cell, after_cell = f"D{s0 + 1}", f"D{s0 + 2}"
        refs = {"bf": t["bf_s"], "cf": cf_s, "books": t["books_s"], "within": within_cell, "after": after_cell}

        payment = _regular_payment(lines, ctx.period_end)
        closing = sum(closing_of(x) for x in g)    # the TB balance is the closing one (openings included)
        on_short_codes = sum(closing_of(x) for x in g
                             if x.std_code in LOANS_WITHIN_1_YEAR or x.std_code in CREDITOR_LOAN_CODES)
        # Interest charged to the loan account in the year (credits no bigger than two payments, not a drawdown):
        # the next twelve payments repay that much less capital
        year_ago = date(ctx.period_end.year - 1, ctx.period_end.month, min(ctx.period_end.day, 28))
        interest = round(sum(tx[8] for tx in lines if payment and tx[8] and 0 < tx[8] <= 2 * payment
                             and (_when(tx[0]) or date.min) > year_ago), 2)
        capital = max(12 * payment - interest, 0.0)
        rate = _monthly_rate(lines, payment, year_ago)
        if rate is not None and closing > 0.005:
            capital = _capital_in_twelve(closing, payment, rate)
        # Several lenders shown together because last year's balance is kept by code: one 'typical payment' says
        # nothing about them, so the split stays as the books keep it until each lender's balance is known (U-LOAN-007)
        together = len(g) > 1 and (any(BROUGHT_FORWARD.search(x.raw_account_name or "") for x in g)
                                   or any(closing_of(x) < -0.005 for x in g))
        suggestion = (round(min(max(on_short_codes, 0.0), max(closing, 0.0)), 2) if together or not payment else
                      round(min(max(closing, 0.0), capital), 2))
        agreement, sched = ctx.agreements[linked[gi]] if gi in linked else (None, None)
        if sched is not None:
            suggestion = sched.within_1_year
        # Never more due within a year than is still owed after the approved journals (a paid-off hire purchase
        # cleared to nil gets no split)
        own_keys = {str(x.std_code) for x in g}       # (own_codes stays the ints the lead's 'taken' list needs)
        moved = sum(float(j.get("credit") or 0) - float(j.get("debit") or 0) for j in ctx.journals
                    if str(j.get("code")) in own_keys)
        owed_after = round(closing + moved, 2)
        suggestion = round(min(suggestion, max(owed_after, 0.0)), 2)
        ws[f"A{s0}"] = "Split at the year end"
        ws[f"A{s0}"].font = BOLD
        ws[f"B{s0 + 1}"] = "Due within 1 year"
        _input(ws[within_cell], suggestion)
        ws[f"B{s0 + 2}"] = "Due after 1 year"
        # Only a balance owed is split: more repaid than owed is not a liability due after a year
        _money(ws[after_cell]).value = f"=IF(({cf_s})<0,0,ROUND(({cf_s})-{within_cell},2))"
        ws[f"B{s0 + 3}"] = (f"From the finance agreement ({agreement.lender}, loans register): the capital due in the next "
                     f"twelve months on the schedule (right). Change the shaded cell only if the agreement has changed."
                     if sched is not None else
                     "Several lenders shown together (last year's balance is kept by code, not per lender): the split "
                     "is as the books keep it. Get each lender's balance at last year's end (statements or last year's "
                     "loan schedule), move it to its lender, then check the split."
                     if together else
                     f"Suggested: the capital in the next 12 payments of £{payment:,.2f}, interest at "
                     f"{rate * 100:.3f}% a month ({rate * 1200:.2f}% a year) on the falling balance: the rate the "
                     f"interest charged to this account each month shows (FRS 102 20.62). Check against the finance "
                     f"agreement and change the shaded cell."
                     if payment and rate is not None else
                     f"Suggested: 12 payments of £{payment:,.2f} (the typical payment in the ledger) less the interest "
                     f"charged to this account in the year (£{interest:,.2f}), capped at the balance: the capital repaid "
                     f"in the next year. Check against the finance agreement and change the shaded cell."
                     if payment and interest else
                     f"Suggested: 12 payments of £{payment:,.2f} (the typical payment in the ledger), capped at the "
                     f"balance. No interest is charged to this account, so the payments are taken as capital: if they "
                     f"include interest, check against the finance agreement and change the shaded cell."
                     if payment else
                     "No regular payment in the ledger: the split follows the code the account is on. Check against "
                     "the agreement and change the shaded cell.")
        if len(g) > 1:
            ws[f"B{s0 + 4}"] = ("Accounts of one loan, shown together: " + "; ".join(
                f"{x.raw_account_name} ({x.std_code})" for x in g))[:250]
            if any(closing_of(x) < -0.005 for x in g):
                ws[f"B{s0 + 5}"] = ("Last year's balance was kept on a code, not per lender: the repayments are on one account "
                             "and the balance brought forward on another. Check the total against the lender statements.")
        elif closing < -0.005:
            ws[f"B{s0 + 4}"] = ("More repaid than owed: not split as a liability. Either last year's balance for this lender is on "
                         "a 'Brought forward' or shared line on the lead (G4), so move it here, or the payments include "
                         "interest or an overpayment: ask the client for the loan statement.")
            ws[f"B{s0 + 4}"].font = BOLD
        if sched is not None:
            ws["F6"] = f"Per the agreement: {agreement.lender} ({agreement.method})"[:80]
            ws["F6"].font = BOLD
            for row, (text, value) in enumerate((
                    ("Balance at the year end (capital)", sched.balance_ye),
                    ("Due within 1 year", sched.within_1_year),
                    ("Due in 1-5 years", sched.one_to_five),
                    ("Due after 5 years", sched.after_five),
                    ("Interest / finance charge for the year", sched.interest_in_year),
                    ("Payments in the year", sched.payments_in_year),
                    ("Future finance charges (HP booked gross)", sched.future_charges)), 8):
                ws.cell(row=row, column=6, value=text)
                _money(ws.cell(row=row, column=8, value=value))
            ws["F15"] = "Books less schedule (balance)"
            ws["F15"].font = BOLD
            _money(ws.cell(row=15, column=8, value=f"=ROUND({cf_s}-H8,2)"), bold=True)
            ws["F16"] = (f"Payment £{sched.payment:,.2f}; {sched.made_ye} of {agreement.payments} paid by the year end; "
                         f"last payment {sched.final_payment:%d/%m/%Y}." if sched.final_payment else "")
            ws["F17"] = ("A difference is usually interest not yet charged to the loan (journal on the Journals tab) "
                         "or a payment or opening balance missing.")
        from_gl = [x for x in g if id(x) in missing]
        if from_gl:
            ws[f"B{s0 + 6}"] = ("Balance b/fwd from the ledger's opening balance (" + "; ".join(
                f"{x.raw_account_name} £{-missing[id(x)]:,.2f}" for x in from_gl) + "): the TB does not hold it, so the "
                "books are short by it. Post last year's balance (journal) after checking it to last year's accounts.")[:300]
            ws[f"B{s0 + 6}"].font = BOLD
        end = _write_lines(ws, s0 + 8, "Ledger lines this year", lines, "Paid (Dr)", "Added / interest (Cr)")
        _monthly_table(ws, end, lines, ctx.period_end, refs["bf"], refs["books"])
        made.append((ws.title, g, own_codes if sole else [], refs))

    if not made and not brought_forward and not unallocated:
        return []
    _loans_lead(ctx, lead_title, made, brought_forward, unallocated, opening_of, after,
                {tab: refs["books"] for tab, g, _, refs in made if all(x.std_code in CREDITOR_LOAN_CODES for x in g)},
                round(-sum(missing.values()), 2))
    unmatched = [a.lender for i, (a, _) in enumerate(ctx.agreements) if i not in linked.values()]
    if unmatched:
        ws = ctx.wb[lead_title]
        r = ws.max_row + 2
        ws.cell(row=r, column=1, value=("On the loans register but not found in the ledger (no account with the "
                                        "lender's name): " + "; ".join(unmatched))[:300]).font = BOLD
        ctx.notes.append(f"Loans (G4): {len(unmatched)} agreement(s) on the loans register not found in the ledger")
    if missing:
        ctx.notes.append(f"Loans (G4): £{-sum(missing.values()):,.2f} of loan balances brought forward are in the "
                         f"ledger but not in the TB: post them")
    ctx.notes.append(f"Loans and HP (G4): check the split due within / after one year for {len(made)} lender(s)")
    return [lead_title] + [m[0] for m in made]


def _loans_lead(ctx: Context, title: str, made, brought_forward, unallocated: Dict[int, float], opening_of, after,
                in_creditors: Optional[Dict[str, str]] = None, not_in_tb: float = 0.0):
    in_creditors = in_creditors or {}
    wb = ctx.wb
    anchor = next((n for n in after if n in wb.sheetnames), None)
    first_tab = made[0][0] if made else None
    index = wb.sheetnames.index(first_tab) if first_tab else (wb.sheetnames.index(anchor) + 1 if anchor else len(wb.sheetnames))
    ws = wb.create_sheet(title, index)
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    ws["H1"] = "G4"
    ws["A4"] = "Loans and hire purchase"
    ws["A4"].font = TITLE
    heads = ["Lender", "Code", "Ref", "b/fwd £", "c/fwd £", "Within 1 year £", "After 1 year £"]
    for c, text in enumerate(heads, 1):
        ws.cell(row=6, column=c, value=text).font = BOLD
    r = 7
    for tab, g, _, refs in made:
        ws.cell(row=r, column=1, value=" / ".join(dict.fromkeys(x.raw_account_name for x in g))[:45])
        ws.cell(row=r, column=2, value=g[0].std_code if len({x.std_code for x in g}) == 1 else
                ", ".join(str(c) for c in dict.fromkeys(x.std_code for x in g)))
        ws.cell(row=r, column=3, value=tab.split(" - ")[0])
        for c, key in ((4, "bf"), (5, "cf"), (6, "within"), (7, "after")):
            _money(ws.cell(row=r, column=c, value=f"={on_tab(tab, refs[key])}"))
        r += 1
    for t in brought_forward:            # last year's balance by code, carried in as its own account
        owed = -opening_of(t)            # less the lenders' shares moved to their tabs (last year's working paper)
        if abs(owed) < 0.005:
            continue
        ws.cell(row=r, column=1, value=t.raw_account_name[:45])
        ws.cell(row=r, column=2, value=t.std_code)
        _money(ws.cell(row=r, column=4, value=round(-opening_of(t), 2)))
        _money(ws.cell(row=r, column=5, value=f"={_ttb_account(t.std_code, t.raw_account_name, 'G')}"
                                               f"-{_ttb_account(t.std_code, t.raw_account_name, 'F')}+D{r}"))
        within = t.std_code in LOANS_WITHIN_1_YEAR
        _money(ws.cell(row=r, column=6, value=f"=E{r}" if within else 0))
        _money(ws.cell(row=r, column=7, value=0 if within else f"=E{r}"))
        ws.cell(row=r, column=8, value="Last year's balance: move it to the lender it belongs to" if abs(owed) >= 0.005 else None)
        r += 1
    for code, bal in unallocated.items():
        ws.cell(row=r, column=1, value=f"Last year's balance on {code} (several lenders)")
        ws.cell(row=r, column=2, value=code)
        _money(ws.cell(row=r, column=4, value=round(-bal, 2)))
        _money(ws.cell(row=r, column=5, value=f"=D{r}"))
        within = code in LOANS_WITHIN_1_YEAR
        _money(ws.cell(row=r, column=6, value=f"=E{r}" if within else 0))
        _money(ws.cell(row=r, column=7, value=0 if within else f"=E{r}"))
        r += 1
    all_codes = LOANS_WITHIN_1_YEAR + LOANS_AFTER_1_YEAR
    # Journals on a loan whose tab holds its code alone are in that tab's c/fwd and split; the rest are added here
    taken = {c for _t, _g, own, _r in made for c in own}
    left = [c for c in all_codes if c not in taken]
    within_left = [c for c in LOANS_WITHIN_1_YEAR if c not in taken]
    after_left = [c for c in LOANS_AFTER_1_YEAR if c not in taken]
    ws.cell(row=r, column=1, value="Adjusting journals (B2)" + (": those not on a lender's tab" if taken else ""))
    _money(ws.cell(row=r, column=5, value=f"=({_etb(left, 'K')})-({_etb(left, 'J')})" if left else 0))
    _money(ws.cell(row=r, column=6, value=f"=({_etb(within_left, 'K')})-({_etb(within_left, 'J')})" if within_left else 0))
    _money(ws.cell(row=r, column=7, value=f"=({_etb(after_left, 'K')})-({_etb(after_left, 'J')})" if after_left else 0))
    last = r
    r += 1
    ws.cell(row=r, column=1, value="Total").font = BOLD
    for c, col in ((4, "D"), (5, "E"), (6, "F"), (7, "G")):
        _money(ws.cell(row=r, column=c, value=f"=SUM({col}7:{col}{last})"), bold=True, total=True)
    total = r
    r += 2
    ws.cell(row=r, column=1, value="In the books (ETB final balance)").font = BOLD
    # Loans kept on other creditors are in the books as due within one year
    extra = "".join(f"+({on_tab(tab, books)})" for tab, books in in_creditors.items())
    _money(ws.cell(row=r, column=5, value=f"=-({_etb(all_codes, 'N')}){extra}"))
    _money(ws.cell(row=r, column=6, value=f"=-({_etb(LOANS_WITHIN_1_YEAR, 'N')}){extra}"))
    _money(ws.cell(row=r, column=7, value=f"=-({_etb(LOANS_AFTER_1_YEAR, 'N')})"))
    books = r
    if abs(not_in_tb) >= 0.005:
        r += 1
        ws.cell(row=r, column=1, value="Loan balances b/fwd in the ledger, not in the TB (journal needed)").font = BOLD
        _money(ws.cell(row=r, column=5, value=not_in_tb), bold=True)
    r += 1
    ws.cell(row=r, column=1, value="Check: total c/fwd less the books (must be nil)")
    _money(ws.cell(row=r, column=5, value=f"=ROUND(E{total}-E{books}"
                                          + (f"-E{books + 1}" if abs(not_in_tb) >= 0.005 else "") + ",2)"))
    r += 1
    ws.cell(row=r, column=1, value="Split above less the books: reclassify by journal if not nil").font = BOLD
    _money(ws.cell(row=r, column=6, value=f"=ROUND(F{total}-F{books},2)"), bold=True)
    _money(ws.cell(row=r, column=7, value=f"=ROUND(G{total}-G{books},2)"), bold=True)
    if in_creditors:
        r += 2
        ws.cell(row=r, column=1, value=(
            f"{', '.join(t.split(' - ')[0] for t in in_creditors)}: loans kept on other creditors (5350): included in "
            f"the books above. Move them to other loans (5110 within / 5510 after one year) if the split is not all "
            f"within one year."))
    ws.column_dimensions["A"].width = 46
    for col in "DEFG":
        ws.column_dimensions[col].width = 16
    # The creditors lead takes the split worked here, not the codes the books keep the loans on
    if "G1 (LEAD)" in ctx.wb.sheetnames:
        g1 = ctx.wb["G1 (LEAD)"]
        for row in range(1, min(g1.max_row, 60) + 1):
            label = str(g1.cell(row=row, column=2).value or "").strip().lower()
            # Within one year as split; after one year the rest of the c/fwd, so the two always add up to the loans
            # total (the split caps an overpaid long-term loan at nil, which would leave the lead short of the books)
            if label == "loans due within 1 year":
                g1.cell(row=row, column=4, value=f"='{title}'!F{total}")
            elif label == "loans due after 1 year":
                g1.cell(row=row, column=4, value=f"='{title}'!E{total}-'{title}'!F{total}")


def _monthly_table(ws, row: int, lines: List[tuple], period_end: date, bf: str = "D8", books: str = "D10") -> None:
    """The loan month by month: opening, paid per bank, paid per the lender's statement (a cell to
    type it), added or interest, closing; from the ledger lines above, the first opening being the b/fwd (D8)."""
    from backend.app.services.sop.common import year_months
    months = year_months(period_end)
    paid: Dict[date, float] = {m: 0.0 for m in months}
    added: Dict[date, float] = {m: 0.0 for m in months}
    other = [0.0, 0.0]
    for tx in lines:
        when = _when(tx[0])
        month = next((m for m in months if when and (when.year, when.month) == (m.year, m.month)), None)
        if month is None:
            other[0] += tx[7] or 0.0
            other[1] += tx[8] or 0.0
        else:
            paid[month] += tx[7] or 0.0
            added[month] += tx[8] or 0.0
    ws.cell(row=row, column=1, value="Month by month").font = BOLD
    heads = ["Month", "Opening", "Paid per bank", "Paid per statement", "Added / interest", "Closing"]
    for c, text in enumerate(heads, 1):
        ws.cell(row=row + 1, column=c, value=text).font = BOLD
    r = row + 1
    rows = [(m, paid[m], added[m]) for m in months] + ([("Other dates", other[0], other[1])] if any(other) else [])
    for label, out, into in rows:
        r += 1
        cell = ws.cell(row=r, column=1, value=label)
        if isinstance(label, date):
            cell.number_format = "mmm-yy"
        _money(ws.cell(row=r, column=2, value=f"={bf}" if r == row + 2 else f"=F{r - 1}"))
        _money(ws.cell(row=r, column=3, value=round(out, 2)))
        _input(ws.cell(row=r, column=4))
        _money(ws.cell(row=r, column=5, value=round(into, 2)))
        _money(ws.cell(row=r, column=6, value=f"=B{r}-C{r}+E{r}"))
    ws.cell(row=r + 1, column=1, value="Closing per books (the T, before the journals) less the last closing: lines not in the ledger tab")
    _money(ws.cell(row=r + 1, column=6, value=f"=ROUND(({books})-F{r},2)"))

