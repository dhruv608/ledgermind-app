"""U-PAY-024: an HMRC PAYE payment coded to a wage cost or CT moves to PAYE when PAYE owed can take it, else a question."""
from datetime import date
from types import SimpleNamespace as NS

from backend.app.services.review.payroll_journals import hmrc_elsewhere as he


class Chart:
    def name(self, code):
        return f"name {code}"


def _run(monkeypatch, paye_balance, lines):
    monkeypatch.setattr(he, "_lines", lambda *a: iter(lines))
    tb = [NS(std_code=5320, net_amount=paye_balance)]
    eng = NS(id="e1")
    return he.hmrc_paye_elsewhere(eng, tb, Chart(), None, [1], [])


def _line(code, amount, text):
    return code, NS(debit_amount=amount, credit_amount=0, description=text, reference="",
                    transaction_date=date(2025, 5, 22))


def test_moved_when_paye_owed_covers_it(monkeypatch):
    points, journals = _run(monkeypatch, -758.20, [_line(3010, 478.86, "HMRC PAYE - 120PL01987215")])
    assert [(j.debit_code, j.credit_code, j.amount) for j in journals] == [(5320, 3010, 478.86)]
    assert points[0].procedure_ref == "U-PAY-024"


def test_question_when_books_only_expense_hmrc(monkeypatch):
    points, journals = _run(monkeypatch, 0.0, [_line(3001, 849.80, "HMRC NIC Cumbernauld")])
    assert journals == [] and "employer's NI cost" in points[0].finding_details


def test_other_hmrc_and_other_codes_left(monkeypatch):
    points, journals = _run(monkeypatch, -5000.0, [_line(3010, 300.0, "HMRC VAT"), _line(3260, 400.0, "HMRC PAYE")])
    assert points == [] and journals == []
