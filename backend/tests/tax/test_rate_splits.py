"""U-LOAN-003 / U-LOAN-009 from the rate the ledger's monthly interest shows (FRS 102 20.62, s4). Figures from a
client's 2026 review, made anonymous: a van lease and a car HP."""
from datetime import date
from types import SimpleNamespace as N

import backend.app.services.sop.common as sc
from backend.app.services.review.loans_review import rate_splits
from backend.app.services.sop.common import GLLine


class Chart:
    def name(self, code, default=""):
        return str(code)


def _lease(code, account, payment, interest, start):
    lines = [GLLine(date(2025, 10, 1), code, account, 0, start, "Lease liability at the start", "")]
    for i, amount in enumerate(interest):
        m = 10 + i
        y, m = (2025, m) if m <= 12 else (2026, m - 12)
        lines.append(GLLine(date(y, m, 14), code, account, payment, 0, "Lessor - monthly rental", ""))
        lines.append(GLLine(date(y, m, 28), code, account, 0, amount, "Interest on lease", ""))
    return lines


VAN = [182.45, 180.58, 178.70, 176.82, 174.92, 173.01, 171.10, 169.17, 167.23, 165.28, 163.33, 161.36]
CAR = [214.41, 210.5, 206.57, 202.62, 198.65, 194.65, 190.63, 186.59, 182.53]


def _run(lines, tb, monkeypatch):
    monkeypatch.setattr(sc, "gl_lines", lambda *a, **k: lines)
    eng = N(id="e", period_end_date=date(2026, 9, 30), prior_period_end_date=date(2025, 9, 30))
    return rate_splits(eng, tb, Chart(), None, [1])


def test_lease_on_other_creditors_after_one_year_gets_its_within_one_year_part(monkeypatch):
    lines = _lease(5750, "ROU 2 - HT74 LCJ", 545.02, VAN, 35406.69)
    tb = [N(raw_account_name="ROU 2 - HT74 LCJ", std_code=5750, net_amount=-30930.40)]
    findings, journals = _run(lines, tb, monkeypatch)
    assert journals == [] and findings[0].procedure_ref == "U-LOAN-009"
    assert abs(findings[0].quantified_amount - 4758.49) < 1.0


def test_hp_pair_reclassified_when_every_loan_on_it_has_a_rate(monkeypatch):
    lines = _lease(5001, "HP 2 - BT75 DSV", 916.82, CAR, 38525.0)
    tb = [N(raw_account_name="HP 2 - BT75 DSV", std_code=5001, net_amount=-32070.77)]
    findings, journals = _run(lines, tb, monkeypatch)
    assert findings[0].procedure_ref == "U-LOAN-003"
    j = journals[0]
    assert (j.debit_code, j.credit_code) == (5001, 5000) and abs(j.amount - 9136.76) < 1.0


def test_nothing_posted_when_any_loan_on_the_pair_has_no_rate(monkeypatch):
    lines = _lease(5001, "HP 2 - BT75 DSV", 916.82, CAR, 38525.0)
    tb = [N(raw_account_name="HP 2 - BT75 DSV", std_code=5001, net_amount=-32070.77),
          N(raw_account_name="Brought forward: Hire purchase less than 1 year", std_code=5000, net_amount=-53114.71)]
    assert _run(lines, tb, monkeypatch) == ([], [])
