"""U-FA-020: one fixed asset account holding additions and disposals (or the charge and depreciation on disposals)
split to their own codes (FRS 102 1AD.13; CAA 2001 s61). Figures from a client's 2026 review, made anonymous."""
from datetime import date
from types import SimpleNamespace as N

import backend.app.services.sop.common as sc
from backend.app.services.review import fa_disposals as fd
from backend.app.services.sop.common import GLLine


class Chart:
    def name(self, code, default=""):
        return str(code)


def _run(lines, monkeypatch):
    monkeypatch.setattr(sc, "gl_lines", lambda *a, **k: lines)
    eng = N(id="e", prior_period_end_date=date(2025, 9, 30))
    return fd.disposal_split(eng, [], Chart(), None, [1])


def _l(when, code, account, dr, cr, text):
    return GLLine(when, code, account, dr, cr, text, "")


def test_cars_bought_and_sold_on_one_account_and_their_depreciation(monkeypatch):
    lines = [_l(date(2025, 12, 1), 4132, "Motor Vehicles", 49967.5, 0, "Mercedes CLA BT75 DSV"),
             _l(date(2025, 10, 3), 4132, "Motor Vehicles", 0, 25000, "Disposal of asset FA-0074 on 3 Oct 2025"),
             _l(date(2026, 3, 24), 4132, "Motor Vehicles", 0, 51541.33, "Disposal of asset FA-0095 on 24 Mar 2026"),
             _l(date(2026, 9, 30), 4134, "Motor Vehicles Depreciation", 0, 88203.73, "Depreciation"),
             _l(date(2025, 10, 3), 4134, "Motor Vehicles Depreciation", 19068.25, 0, "Disposal of asset FA-0074"),
             _l(date(2026, 3, 24), 4134, "Motor Vehicles Depreciation", 14495.96, 0, "Disposal of asset FA-0095")]
    findings, journals = _run(lines, monkeypatch)
    got = {(j.debit_code, j.credit_code): j.amount for j in journals}
    assert got == {(4131, 4132): 49967.5, (4135, 4134): 33564.21}
    assert all(f.procedure_ref == "U-FA-020" for f in findings)


def test_a_credit_that_is_not_a_disposal_stays_and_small_or_tidy_accounts_give_nothing(monkeypatch):
    lines = [_l(date(2026, 1, 5), 4151, "Office Equipment", 8587.46, 0, "Laptops"),
             _l(date(2026, 8, 25), 4151, "Office Equipment", 0, 665.83, "Employee repayments - Mobile Phone"),
             _l(date(2026, 8, 25), 4151, "Office Equipment", 0, 665.83, "Disposal of asset FA-0042 on 25 Aug 2026"),
             _l(date(2026, 8, 25), 4154, "Office Equipment Depreciation", 50.0, 0, "Disposal of asset FA-0042"),
             _l(date(2026, 2, 1), 4121, "Plant", 6649.15, 0, "Compressor"),
             _l(date(2025, 9, 30), 4132, "Vans", 0, 9000.0, "Opening balance")]
    _f, journals = _run(lines, monkeypatch)
    assert [(j.debit_code, j.credit_code, j.amount) for j in journals] == [(4151, 4152, 665.83)]


def test_a_journal_and_its_own_reversal_are_no_disposal(monkeypatch):
    lines = [_l(date(2024, 3, 31), 4121, "Plant additions", 0, 1609.64, "Disposal in 2nd year; not moving to costs"),
             _l(date(2024, 5, 31), 4121, "Plant additions", 1609.64, 0, "Clear TB"),
             _l(date(2024, 3, 31), 4124, "Plant depreciation", 322.64, 0, "Disposal in 2nd year"),
             _l(date(2024, 5, 31), 4124, "Plant depreciation", 0, 322.64, "Clear TB")]
    monkeypatch.setattr(sc, "gl_lines", lambda *a, **k: lines)
    eng = N(id="e", prior_period_end_date=date(2024, 1, 31))
    assert fd.disposal_split(eng, [], Chart(), None, [1]) == ([], [])
