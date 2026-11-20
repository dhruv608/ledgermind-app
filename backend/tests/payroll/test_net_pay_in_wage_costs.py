"""Net pay paid from the bank coded to the wage costs, with the payroll's gross already there: each bank payment equal
to a month's net pay is moved to net wages, never more than the costs hold above the report's gross."""
from datetime import date
from types import SimpleNamespace as N

import backend.app.services.review.payroll_journals.common as common
import backend.app.services.review.payroll_journals.net_wages as nw
import backend.app.services.review.payroll_period as period
import backend.app.services.tax.ct_computation as ct

CHART = N(name=lambda c, d="": {5330: "Net wages", 1500: "Direct wages", 3000: "Wages"}.get(c, d))


def _run(monkeypatch, books, runs, lines):
    recs = [N(period_end=date(2024, m, 28), period_start=None, employee_name="A Person", gross_pay=g,
              tax_deducted=g - n, employee_nic=0, pension_employee=0, student_loan=0) for m, g, n in runs]
    monkeypatch.setattr(period, "usable", lambda e, db: (recs, None))
    monkeypatch.setattr(ct, "final_balances", lambda *a: books)
    monkeypatch.setattr(common, "employer_ni_on_wage_codes", lambda tb: 0.0)
    monkeypatch.setattr(common, "_journal_lines", lambda e, c, label, lines, chart, f: (label, lines))
    gl = [(code, N(transaction_date=date(2024, m, d), debit_amount=a, credit_amount=0, source="Spend Money",
                   description="pay")) for code, m, d, a in lines]
    monkeypatch.setattr(nw, "_lines", lambda *a: iter(gl))
    return nw._net_pay_paid_into_costs(N(id="e"), [], CHART, None, [0])


def test_net_pay_paid_into_wages_twice_is_moved(monkeypatch):
    runs = [(7, 7478.26, 5534.60), (8, 7597.90, 5174.15), (9, 7904.76, 5158.32)]
    books = {3000: 22980.92, 1500: 15867.07}
    f, j = _run(monkeypatch, books, runs, [(1500, 7, 31, 5534.60), (1500, 8, 30, 5174.15), (1500, 9, 30, 5158.32)])
    assert f and j[0][1][0] == (5330, 15867.07, 0.0) and j[0][1][1] == (1500, 0.0, 15867.07)


def test_payment_next_month_still_matches_and_odd_amounts_stay(monkeypatch):
    runs = [(7, 7478.26, 5534.60), (8, 7597.90, 5174.15)]
    books = {3000: 15076.16, 1500: 5534.60 + 5174.15 + 900.0}
    f, j = _run(monkeypatch, books, runs, [(1500, 8, 1, 5534.60), (1500, 8, 30, 5174.15), (1500, 8, 15, 900.0)])
    assert j[0][1][0] == (5330, 10708.75, 0.0)


def test_nothing_when_the_costs_are_not_above_the_gross(monkeypatch):
    # net pay paid into wages but the gross never posted: the costs hold only the net (U-PAY-008's case)
    runs = [(7, 7478.26, 5534.60), (8, 7597.90, 5174.15)]
    f, j = _run(monkeypatch, {1500: 10708.75}, runs, [(1500, 7, 31, 5534.60), (1500, 8, 30, 5174.15)])
    assert f == [] and j == []
