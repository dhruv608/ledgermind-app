"""The employment allowance already taken in the payroll: nil employer NI from April on wages, then NI again (e.g. April
to August nil on about £20k a month). No journal then."""
from datetime import date
from types import SimpleNamespace as NS

import backend.app.services.review.payroll_period as pp
from backend.app.services.review.payroll_journals.allowance import _used_up_in_payroll


def _rows(nis):
    return [NS(period_end=date(2025 if m < 11 else 2024, m, 28), gross_pay=20000.0, employer_nic=ni)
            for m, ni in nis]


def test_nil_from_april_then_ni(monkeypatch):
    rows = _rows([(12, 1112.79), (1, 1165.77), (3, 1495.93), (4, 0.0), (5, 0.0), (8, 0.0), (9, 1668.07), (10, 2101.3)])
    monkeypatch.setattr(pp, "usable", lambda e, db: (rows, False))
    assert _used_up_in_payroll(NS(id="x"), None)


def test_ni_every_month_is_not_used_up(monkeypatch):
    rows = _rows([(4, 900.0), (5, 900.0), (6, 900.0)])
    monkeypatch.setattr(pp, "usable", lambda e, db: (rows, False))
    assert not _used_up_in_payroll(NS(id="x"), None)
