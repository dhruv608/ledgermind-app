"""An account named as wages that the payroll does not hold (the payroll's gross is already in the other pay accounts):
pay to people outside the payroll, moved to subcontractors with a client query."""
from datetime import date
from types import SimpleNamespace as N

import backend.app.services.review.payroll_journals.not_on_payroll as nop
import backend.app.services.review.payroll_period as period

CHART = N(name=lambda c, d="": {1440: "Subcontractors", 1500: "Direct wages", 3020: "Subcontractors",
                                 3000: "Wages", 3010: "Directors' salaries"}.get(c, d))


def _run(monkeypatch, tb, payroll, earlier=(), lines=()):
    recs = [N(period_end=date(2025, m, 28), period_start=None, employee_name=who, gross_pay=g)
            for m in range(1, 13) for who, g in payroll]
    monkeypatch.setattr(period, "usable", lambda e, db: (recs, None))
    monkeypatch.setattr(nop, "_lines", lambda *a: iter(lines))
    tbr = [N(std_code=c, raw_account_name=n, net_amount=a) for n, c, a in tb]
    return nop.pay_not_on_payroll(N(id="e"), tbr, CHART, None, [0], list(earlier))


def test_direct_wages_beside_a_directors_only_payroll_move_to_subcontractors(monkeypatch):
    f, j = _run(monkeypatch, [("Direct Wages", 1500, 73511.59), ("Directors' Remuneration", 3010, 33140.0)],
                [("Jo Bloggs", 1381.0), ("Lee Parker", 1380.67)])
    assert f and f[0].procedure_ref == "U-PAY-025" and "Query to the client" in f[0].finding_details
    assert (j[0].debit_code, j[0].credit_code, j[0].amount) == (1440, 1500, 73511.59)


def test_casual_wages_in_employee_costs_go_to_3020(monkeypatch):
    f, j = _run(monkeypatch, [("Casual Wages", 3000, 16915.19), ("Wages", 3000, 19675.0),
                              ("Directors' remuneration", 3010, 12570.0)], [("A Person", 32245.0 / 12)])
    assert (j[0].debit_code, j[0].credit_code, j[0].amount) == (3020, 3000, 16915.19)


def test_wages_the_payroll_needs_stay(monkeypatch):
    # direct wages and directors together make the payroll's gross: both on the payroll
    f, j = _run(monkeypatch, [("Direct Wages", 1500, 25615.44), ("Directors' Remuneration", 3010, 12570.0)],
                [("A Person", 38185.44 / 12)])
    assert f == [] and j == []


def test_net_pay_already_moved_off_the_account_stays(monkeypatch):
    moved = N(lines=[], amount=48658.88, debit_code=5330, credit_code=1500)
    f, j = _run(monkeypatch, [("Direct Wages", 1500, 48658.88), ("Salaries", 3000, 70594.18)],
                [("A Person", 70594.18 / 12)], earlier=[moved])
    assert f == [] and j == []


def test_lines_naming_a_payroll_employee_stay(monkeypatch):
    lines = [(1500, N(debit_amount=5000.0, description="Lee Parker May wage"))]
    f, j = _run(monkeypatch, [("Direct Wages", 1500, 20000.0), ("Directors' Remuneration", 3010, 12000.0)],
                [("Lee Parker", 1000.0)], lines=lines)
    assert f == [] and j == []
