"""U-LOAN-008: a loan or HP paid off in the year with its two accounts left cancelling (FRS 102 s11, s20). Figures
from two clients' reviews, made anonymous."""
from types import SimpleNamespace as N

from backend.app.services.review.loan_statements import _settled_hp


class Chart:
    def name(self, code, default=""):
        return str(code)


T = lambda code, opening: N(std_code=code, opening_amount=opening)


def _run(opening, after):
    import backend.app.services.review.payroll_journals as pj
    got = {}
    real = pj._journal_lines

    def fake(engagement, counter, description, lines, chart, point):
        got["lines"] = lines
        return description
    pj._journal_lines = fake
    try:
        findings, journals = _settled_hp(N(id="e"), [T(c, v) for c, v in opening.items()], after, Chart(), [1])
    finally:
        pj._journal_lines = real
    return findings, journals, got.get("lines")


def test_mortgage_paid_off_with_its_balance_and_repayments_on_two_codes():
    findings, journals, lines = _run({5100: -20982.72, 5500: -71307.69}, {5100: -20982.72, 5500: 20982.72})
    assert findings[0].finding_title.startswith("Bank loan paid off")
    assert sorted(lines) == sorted([(5100, 20982.72, 0.0), (5500, 0.0, 20982.72)])


def test_loan_still_owed_is_left_alone():
    # Most of the loan still owed, one code in debit: not paid off, so nothing is cleared
    findings, journals, _ = _run({5100: -2560.0, 5500: -3000.0}, {5100: -2560.0, 5500: 146.61})
    assert findings == [] and journals == []
