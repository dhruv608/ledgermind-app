"""PY-10: staff paid above the auto-enrolment trigger (£10,000 a year, £833 a month) with no workplace pension at all
(Pensions Act 2008; DWP AE thresholds 2026/27); directors left out."""
import json
from datetime import date
from types import SimpleNamespace as N

from backend.app.services.queries.payroll_rules import auto_enrolment_query


def _row(name, month, gross, pension=0.0):
    return N(employee_name=name, period_start=None, period_end=date(2025, month, 28), tax_month_label=f"M{month}",
             gross_pay=gross, pension_employer=pension, pension_employee=0.0, tax_deducted=0.0, employee_nic=0.0,
             employer_nic=50.0, student_loan=0.0, net_pay=gross, statutory_pay_recovered=0.0, total_hmrc_due=0.0)


def _queries(_monkeypatch, rows):
    eng = N(profile=N(directors=json.dumps(["Anna Maria Lewis"])))
    return auto_enrolment_query(eng, rows)


def test_staff_above_the_trigger_with_no_pension_is_a_query(monkeypatch):
    rows = [_row("Tom Baker", m, 1500.0) for m in range(1, 13)] + [_row("Sue Carr", m, 1500.0, 45.0) for m in range(1, 13)]
    out = _queries(monkeypatch, rows)
    assert len(out) == 1 and "Tom Baker" in out[0]["detail"] and "Sue Carr" not in out[0]["detail"]


def test_directors_and_low_pay_are_left_out(monkeypatch):
    rows = [_row("Anna Lewis", m, 1047.5) for m in range(1, 13)] + [_row("Ben Odd", m, 500.0) for m in range(1, 13)]
    assert _queries(monkeypatch, rows) == []
