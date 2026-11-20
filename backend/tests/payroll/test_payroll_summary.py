"""The Payroll summary: month by month from the payroll reports, employees and directors apart."""

from datetime import date
from types import SimpleNamespace as N

from backend.app.services.papers.payroll_summary import payroll_summary


def rec(name, end, gross, tax, ee, er, net, due=0.0):
    return N(employee_name=name, period_end=end, tax_month_label="Month", gross_pay=gross, tax_deducted=tax,
             employee_nic=ee, employer_nic=er, student_loan=0, statutory_pay_recovered=0, net_pay=net,
             pension_employee=0, pension_employer=0, total_hmrc_due=due)


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _):
        return N(scalars=lambda: self.rows)


def test_split_and_allowance():
    rows = [rec("Jane Smith", date(2025, 4, 30), 3000, 300, 100, 200, 2600, due=400),
            rec("Oliver Chance", date(2025, 4, 30), 1000, 0, 0, 100, 1000, due=0.01)]
    eng = N(id="e", profile=N(directors='["Oliver John Chance"]'))
    out = payroll_summary(eng, FakeDb(rows))
    keys = [t["key"] for t in out["tables"]]
    assert keys == ["total", "employees", "directors"]
    total = out["tables"][0]["months"][0]
    assert total["gross"] == 4000 and total["liability"] == 700
    assert total["allowance"] == round(700 - 400.01, 2)          # liability less what the report says is due
    assert out["tables"][2]["total"]["gross"] == 1000
