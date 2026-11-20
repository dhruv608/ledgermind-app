"""A credit card in debit at the year end, found per card account (U-BNK-005), and the query for the payroll report
per employee when the directors' pay cannot be split from the staff wages (PY-11). Figures from a client's 2026
review, made anonymous."""
from types import SimpleNamespace as N

from backend.app.services.queries.payroll_rules import director_split_query
from backend.app.services.review.universal_checks import cards_in_debit

A = lambda name, code, opening, net: N(raw_account_name=name, std_code=code, opening_amount=opening, net_amount=net)


def test_card_in_debit_with_no_opening_points_to_last_years_creditor_line():
    tb = [A("1210 - Natwest Business Credit Card", 5354, 0.0, 18059.17),
          A("2302 - Insurance finance agreement", 5350, -70159.4, -106547.09),
          A("821 - Payroll - CIS Liability", 5351, 0.0, 1509.6)]          # 5351 holds CIS here: not a card
    found = cards_in_debit(tb)
    assert len(found) == 1 and found[0].query == "U-BNK-005" and found[0].severity == "MEDIUM"
    assert found[0].amount == 18059.17 and "£70,159.40 on 5350" in found[0].details


def test_card_in_debit_with_its_opening_is_low_and_a_card_owed_is_nothing():
    found = cards_in_debit([A("Capital on Tap Credit Card", 5352, -4113.72, 1670.09)])
    assert found[0].severity == "LOW" and "brought forward" not in found[0].details
    assert cards_in_debit([A("Amex", 5352, -500.0, -900.0)]) == []


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a):
        return self

    def distinct(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class _DB:
    def __init__(self, split=None, names=()):
        self.split, self.names = split, list(names)

    def query(self, what):
        name = getattr(what, "__name__", "") or str(what)
        if "PayrollDirectorPay" in name:
            return _Q([self.split] if self.split else [])
        if "employee_name" in name:
            return _Q([(n,) for n in self.names])
        return _Q([(1,)] if self.names else [])


def _eng():
    return N(id="e", profile=N(directors='["Paul Cook", "Matthew Mountford"]'))


def test_asks_for_the_per_employee_report_when_directors_pay_cannot_be_split():
    balances = {3000: 308312.9, 3010: 37236.09, 3001: 31870.91}
    q = director_split_query(_DB(), _eng(), balances)
    assert q[0]["ref"] == "PY-11" and q[0]["amount"] == 308312.9
    assert "no payroll report has been sent" in q[0]["detail"] and "Paul Cook" in q[0]["detail"]


def test_not_asked_when_split_or_known():
    balances = {3000: 308312.9}
    assert director_split_query(_DB(), _eng(), {**balances, 3011: 13631.66}) == []          # books split it
    assert director_split_query(_DB(split=N(gross_pay=36088.76)), _eng(), balances) == []    # payroll director line
    assert director_split_query(_DB(names=["Paul Cook", "A Worker"]), _eng(), balances) == []   # names a director
    assert director_split_query(_DB(), N(id="e", profile=N(directors="[]")), balances) == []
    assert director_split_query(_DB(), _eng(), {3000: 400.0}) == []


def test_not_asked_when_a_report_exists_and_the_directors_salary_is_already_split():
    balances = {3000: 105627.0, 3010: 42000.0}
    assert director_split_query(_DB(names=["", "All employees"]), _eng(), balances) == []
    # The same report with everything in staff wages: asked
    q = director_split_query(_DB(names=["", "All employees"]), _eng(), {3000: 105627.0})
    assert q and "does not say which pay is the directors'" in q[0]["detail"]
