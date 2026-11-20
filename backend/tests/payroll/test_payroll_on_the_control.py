"""Pay the report shows and the wage costs do not is not posted again when it is already in the books on the wrong code
(postings touching net wages and the wage codes are looked at first)."""
from types import SimpleNamespace as N

from backend.app.services.review.payroll_journals.missing import _pay_on_the_control

CHART = N(name=lambda c, d="": {5330: "Net wages", 5320: "PAYE"}.get(c, d))


def _t(name, code, net):
    return N(raw_account_name=name, std_code=code, net_amount=net)


def test_a_wage_cost_coded_to_net_wages_holds_the_journal():
    tb = [_t("7003 - Payroll - Admin Wages", 5330, 300443.66), _t("2220 - Net Wages", 5330, 0.0)]
    f = _pay_on_the_control(N(id="e"), tb, {5330: 300443.66}, 162447.54, 1461669.58, 1299222.04, CHART)
    assert f is not None and f.procedure_ref == "U-PAY-008" and "Admin Wages" in f.finding_details


def test_net_wages_overdrawn_alone_is_missing_payroll_not_a_hold():
    # net pay paid from the bank with the payroll journal never posted: the journal is still proposed
    assert _pay_on_the_control(N(id="e"), [_t("2220 - Net Wages", 5330, 7999.90)], {5330: 7999.90},
                               5510.14, 33803.94, 28293.80, CHART) is None


def test_genuinely_missing_pay_is_left_to_be_posted():
    tb = [_t("2220 - Net Wages", 5330, -1200.0), _t("2210 - PAYE and NI owed", 5320, -3000.0)]
    assert _pay_on_the_control(N(id="e"), tb, {5330: -1200.0}, 8000.0, 40000.0, 32000.0, CHART) is None
    assert _pay_on_the_control(N(id="e"), tb, {5330: 400.0}, 8000.0, 40000.0, 32000.0, CHART) is None   # small debit
