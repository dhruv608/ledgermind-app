"""A steady monthly charge entered twice in one month (the bill and the direct debit both as costs)."""
from datetime import date
from types import SimpleNamespace as NS

import backend.app.services.sop.common as common
from backend.app.services.sop import duplicates as dup


class _DB:
    def query(self, *_a):
        return self

    def filter(self, *_a):
        return [NS(std_code=3290)]


def _run(monkeypatch, lines):
    rows = [NS(transaction_date=d, debit_amount=a, raw_account_name="Internet & Telephone", source=s, description=n)
            for d, a, s, n in lines]
    monkeypatch.setattr(common, "ledger_rows", lambda eid, db: rows)
    monkeypatch.setattr(common, "code_matcher", lambda codes: (lambda name: 3290))
    monkeypatch.setattr(dup, "ChartLookup", None, raising=False)
    import backend.app.services.mapping.chart_lookup as cl
    monkeypatch.setattr(cl.ChartLookup, "gl_account_codes", staticmethod(lambda tb: {}))
    return dup.twice_in_a_month("e", [], _DB())


def test_bill_and_direct_debit_in_one_month(monkeypatch):
    lines = [(date(2025, m, 15), 51.17, "Spend Money", "Daisy Communications - DD") for m in range(4, 11)]
    lines.append((date(2025, 9, 4), 51.17, "Payable Invoice", "Daisy - ."))
    got = _run(monkeypatch, lines)
    assert len(got) == 1 and got[0].amount == 51.17 and got[0].months == [(date(2025, 9, 4), date(2025, 9, 15))]


def test_fortnightly_or_changing_amounts_are_not_judged(monkeypatch):
    fortnightly = [(date(2025, m, d), 30.0, "Spend Money", "Cleaner - x") for m in range(4, 10) for d in (1, 15)]
    assert _run(monkeypatch, fortnightly) == []
    few = [(date(2025, m, 15), 12.49, "Spend Money", "Adobe - x") for m in (4, 5, 6)] + \
          [(date(2025, 6, 2), 12.49, "Payable Invoice", "Adobe - y")]
    assert _run(monkeypatch, few) == []          # only three months: no steady charge to judge by


def test_two_direct_payments_or_varying_amounts_are_not_judged(monkeypatch):
    two_direct = [(date(2025, m, 15), 9.99, "Spend Money", "Apple - x") for m in range(4, 11)]
    two_direct.append((date(2025, 9, 20), 9.99, "Spend Money", "Apple - y"))
    assert _run(monkeypatch, two_direct) == []          # no bill: an app bought twice, not a bill paid again
    shop = [(date(2025, m, 15), 6.00, "Spend Money", "Sainsburys - x") for m in range(4, 11)]
    shop += [(date(2025, m, 3), 4.80 + m, "Spend Money", "Sainsburys - x") for m in range(4, 11)]
    shop.append((date(2025, 9, 4), 6.00, "Payable Invoice", "Sainsburys - z"))
    assert _run(monkeypatch, shop) == []                # the supplier's charges vary: no steady monthly amount
