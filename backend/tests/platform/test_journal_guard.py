"""The same journal is never posted twice. Made-up journals."""
from types import SimpleNamespace as J

from backend.app.services.review.journal_guard import once_each, signature


def j(desc, dr, cr, amount, lines=None):
    return J(description=desc, debit_code=dr, credit_code=cr, amount=amount, lines=lines or [])


def test_same_codes_amount_and_narrative_is_one_journal():
    a = j("Opening on another code: back to last year's code", 4807, 4800, 2593.36)
    b = j("Opening  on another code: back to last year's CODE", 4807, 4800, 2593.36)     # spacing and case only
    c = j("Opening on another code: back to last year's code", 4807, 4800, 2593.35)      # another amount
    keep, twins = once_each([a, b, c])
    assert keep == [a, c] and twins == [b] and signature(a) == signature(b)


def test_multi_line_journals_compare_their_lines():
    L = lambda code, dr, cr: J(account_code=code, debit=dr, credit=cr)
    a = j("Payroll per report", None, None, 0, [L(3000, 100, 0), L(5330, 0, 80), L(5320, 0, 20)])
    b = j("Payroll per report", None, None, 0, [L(5320, 0, 20), L(3000, 100, 0), L(5330, 0, 80)])  # same, other order
    d = j("Payroll per report", None, None, 0, [L(3000, 100, 0), L(5330, 0, 70), L(5320, 0, 30)])
    keep, twins = once_each([a, b, d])
    assert keep == [a, d] and twins == [b]


def test_final_balances_count_an_approved_twin_once():
    from backend.app.services.tax.ct_computation import final_balances

    class _Q:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self):
            return self

        def all(self):
            return self.rows

    a = j("Use of home as last year", 3100, 5400, 312.0)
    b = j("Use of home as last year", 3100, 5400, 312.0)           # approved twice before the guard
    db = J(execute=lambda *_a, **_k: _Q([a, b]))
    tb = [J(std_code=3100, net_amount=1000.0)]
    got = final_balances("e1", tb, db)
    assert got[3100] == 1312.0 and got[5400] == -312.0
