"""Pay accrued at the year end and the 9-month rule (CTA 2009 s1288), anonymous figures; no database writes."""

from datetime import date
from types import SimpleNamespace as N

from backend.app.services.review import accrual_journals as A


class Q(list):
    def filter(self, *a):
        return self


def test_accrued_bonus_asks_whether_paid_within_nine_months():
    eng = N(id="e", period_end_date=date(2025, 3, 31))
    db = N(query=lambda m: Q([N(kind="ACCRUAL", period="THIS_YEAR", cost_code=3004, amount=5000, description="Staff bonus")]))
    tb = [N(std_code=5360, raw_account_name="Accrued holiday pay", net_amount=-800.0),
          N(std_code=3000, raw_account_name="Wages", net_amount=40000.0)]
    [p] = A.unpaid_remuneration(eng, tb, db)
    assert p.procedure_ref == "U-ACC-007" and p.quantified_amount == 5800
    assert "31/12/2025" in p.finding_title and "s1288" in p.finding_details


def test_nothing_accrued_no_point():
    eng = N(id="e", period_end_date=date(2025, 3, 31))
    assert A.unpaid_remuneration(eng, [N(std_code=5360, raw_account_name="Accruals", net_amount=-900.0)],
                                 N(query=lambda m: Q([]))) == []
