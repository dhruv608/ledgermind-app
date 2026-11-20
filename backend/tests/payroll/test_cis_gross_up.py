"""IND-CON-04: CIS suffered per the contractors' statements above the books -> sales grossed up (Dr 4421 / Cr sales)."""
import os
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import backend.app.services.cis.hmrc as hmrc
from backend.app.services.cis.gross_up import gross_up, sales_code


class Chart:
    def name(self, code, default=""):
        return f"Account {code}"


def _screen(statements, books):
    return lambda e, db, s: {"on": True, "months": [
        {"tax_month": "2025-04-06", "books": {"suffered": b}, "hmrc": ({"suffered_statements": st} if st is not None else {})}
        for st, b in zip(statements, books)]}


TB = [N(std_code=0, net_amount=-80000.0), N(std_code=10, net_amount=-5000.0), N(std_code=3000, net_amount=100.0)]
ENG = N(id="e1")


def test_statements_above_books_gross_up(monkeypatch):
    monkeypatch.setattr(hmrc, "hmrc_screen", _screen([400.0, 600.0], [400.0, 0.0]))
    points, journals = gross_up(ENG, TB, None, {}, Chart(), [1])
    assert len(journals) == 1 and journals[0].amount == 600.0
    assert journals[0].debit_code == 4421 and journals[0].credit_code == 0
    assert points[0].procedure_ref == "IND-CON-04"


def test_nothing_without_statements_or_gap(monkeypatch):
    monkeypatch.setattr(hmrc, "hmrc_screen", _screen([None, None], [400.0, 0.0]))
    assert gross_up(ENG, TB, None, {}, Chart(), [1]) == ([], [])
    monkeypatch.setattr(hmrc, "hmrc_screen", _screen([400.0], [400.0]))
    assert gross_up(ENG, TB, None, {}, Chart(), [1]) == ([], [])


def test_sales_code_is_the_biggest_sales():
    assert sales_code(TB, Chart()) == 0
