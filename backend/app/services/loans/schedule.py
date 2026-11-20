"""Loan and hire purchase schedule from the finance agreement (the firm's loans and HP schedule template, Loans register
columns Q-AO). One agreement in, the year-end figures out: balance at the year end (capital), due within
1 year / 1-5 years / after 5 years, interest for the year, payments and capital repaid, future finance charges.

Methods: Actuarial (interest on the reducing balance; loans and most HP under FRS 102), Rule of 78 (sum of digits;
older HP) and Flat (equal interest each payment). The agreement gives ONE of the interest rate, the regular payment or
the total finance charge (the first one given is used, in that order), as on the template.

Checked against the template's examples: BBL £50,000 at 2.5% over 60 payments -> payment £887.37, balance at
31/03/2026 £2,651.05; a car HP (Rule of 78) and a term loan (payment given).
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

ACTUARIAL, RULE_OF_78, FLAT = 1, 2, 3


@dataclass
class Agreement:
    lender: str
    kind: str = ""                       # Loan / HP / BBL / Lease ...
    drawdown: Optional[date] = None      # agreement / drawdown date
    first_payment: Optional[date] = None
    amount: float = 0.0                  # amount financed (cash price or loan)
    deposit: float = 0.0                 # deposit / part-exchange
    payments: int = 0                    # term: number of payments
    per_year: int = 12
    rate: Optional[float] = None         # interest rate a year (0.025 = 2.5%)
    charge: Optional[float] = None       # total finance charge
    payment: Optional[float] = None      # regular payment
    balloon: float = 0.0
    method: str = "Actuarial"
    books_balance: Optional[float] = None
    books_interest: Optional[float] = None


@dataclass
class Schedule:
    principal: float
    payment: float
    rate: float                          # per payment period
    charge: float
    method: int
    made_ye: int
    made_prior_ye: int
    balance_prior_ye: float
    balance_ye: float
    balance_1y: float
    balance_5y: float
    within_1_year: float
    one_to_five: float
    after_five: float
    new_borrowing: float
    payments_in_year: float
    interest_in_year: float
    capital_repaid: float
    future_charges: float
    final_payment: Optional[date]
    books_less_balance: Optional[float]
    books_less_interest: Optional[float]
    check: str


def _method_no(text: str) -> int:
    t = (text or "").strip().lower()
    return RULE_OF_78 if t.startswith("rule") or "78" in t else FLAT if t.startswith("flat") else ACTUARIAL


def _pmt(r: float, n: int, principal: float, balloon: float) -> float:
    """-PMT(r, n, principal, -balloon): the regular payment."""
    if abs(r) < 1e-12:
        return (principal - balloon) / n
    g = (1 + r) ** n
    return (principal * g - balloon) * r / (g - 1)


def _rate(n: int, payment: float, principal: float, balloon: float) -> float:
    """RATE(n, -payment, principal, -balloon): the rate per period that the payment implies."""
    if payment * n + balloon - principal <= 0.005:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(200):                 # the payment rises with the rate: bisection
        mid = (lo + hi) / 2
        if _pmt(mid, n, principal, balloon) > payment:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    days = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(d.day, days[month - 1]))


def schedule(a: Agreement, year_end: date, prior_year_end: date) -> Schedule:
    n, per_year = int(a.payments), int(a.per_year or 12)
    q = float(a.amount or 0) - float(a.deposit or 0)                     # principal financed
    m = float(a.balloon or 0)
    if a.payment:
        pay = float(a.payment)
    elif a.rate is not None:
        pay = _pmt(float(a.rate) / per_year, n, q, m)
    else:
        pay = (q + float(a.charge or 0) - m) / n
    r = float(a.rate) / per_year if a.rate is not None else _rate(n, pay, q, m)
    charge = float(a.charge) if a.charge is not None else pay * n + m - q
    method = _method_no(a.method)

    def made(on: date) -> int:
        if a.first_payment is None or on < a.first_payment:
            return 0
        return min(n, int(_months_between(a.first_payment, on) / (12 / per_year)) + 1)

    def balance(j: int, drawn: bool) -> float:
        if not drawn or j >= n:
            return 0.0
        if method == ACTUARIAL:
            if abs(r) < 1e-12:
                return q - pay * j
            g = (1 + r) ** j
            return q * g - pay * (g - 1) / r
        share = j * (2 * n - j + 1) / (n * (n + 1)) if method == RULE_OF_78 else j / n
        return q - (pay * j - charge * share)

    def interest_to(j: int, drawn: bool) -> float:
        if not drawn:
            return 0.0
        return charge if j >= n else pay * j - (q - balance(j, True))

    drawn_ye = a.drawdown is None or a.drawdown <= year_end
    drawn_pye = a.drawdown is None or a.drawdown <= prior_year_end
    v, w = made(year_end), made(prior_year_end)
    x, y = min(n, v + per_year), min(n, v + 5 * per_year)
    bal_pye, bal_ye = balance(w, drawn_pye), balance(v, drawn_ye)
    bal_1y, bal_5y = balance(x, drawn_ye), balance(y, drawn_ye)
    payments_in_year = pay * (v - w) + (m if v >= n > w else 0.0)
    interest = interest_to(v, drawn_ye) - interest_to(w, drawn_pye)
    new = q if a.drawdown is not None and prior_year_end < a.drawdown <= year_end else 0.0
    future = (charge - interest_to(v, True)) if drawn_ye else 0.0
    less_bal = round(float(a.books_balance) - bal_ye, 2) if a.books_balance is not None else None
    less_int = round(float(a.books_interest) - interest, 2) if a.books_interest is not None else None
    rolls = abs(bal_pye + new - (payments_in_year - interest) - bal_ye) <= 0.05
    check = ("Roll-forward error" if not rolls else
             "Books differ" if less_bal is not None and abs(less_bal) > 1 else "OK")
    return Schedule(
        principal=round(q, 2), payment=round(pay, 2), rate=r, charge=round(charge, 2), method=method,
        made_ye=v, made_prior_ye=w, balance_prior_ye=round(bal_pye, 2), balance_ye=round(bal_ye, 2),
        balance_1y=round(bal_1y, 2), balance_5y=round(bal_5y, 2), within_1_year=round(bal_ye - bal_1y, 2),
        one_to_five=round(bal_1y - bal_5y, 2), after_five=round(bal_5y, 2), new_borrowing=round(new, 2),
        payments_in_year=round(payments_in_year, 2), interest_in_year=round(interest, 2),
        capital_repaid=round(payments_in_year - interest, 2), future_charges=round(future, 2),
        final_payment=_add_months(a.first_payment, (n - 1) * 12 // per_year) if a.first_payment else None,
        books_less_balance=less_bal, books_less_interest=less_int, check=check)
