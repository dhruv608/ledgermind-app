"""Director's loan repaid after the year end from next year's ledger (s458, s464ZA 30 day rule)."""
import os
from datetime import date
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.tax.dla_repaid import nine_months_after, repaid_after

END = date(2025, 3, 31)


def _l(when, debit=0.0, credit=0.0, desc="", code=5400, account="Directors loan account"):
    return N(when=when, code=code, description=desc, reference="", debit=debit, credit=credit, account=account)


def test_nine_months():
    assert nine_months_after(date(2025, 3, 31)) == date(2025, 12, 31)
    assert nine_months_after(date(2024, 5, 31)) == date(2025, 2, 28)
    assert nine_months_after(date(2025, 1, 31)) == date(2025, 10, 31)


def test_repayments_counted_within_nine_months():
    lines = [_l(date(2025, 4, 1), credit=9000, desc="Opening balance"),        # not a repayment
             _l(date(2025, 5, 10), credit=2000, desc="Director repayment"),
             _l(date(2025, 9, 30), credit=1500, desc="Dividend credited"),
             _l(date(2026, 1, 15), credit=4000),                                # after nine months
             _l(date(2025, 6, 1), credit=700, code=5200)]                       # not the director's loan
    r = repaid_after(END, lines)
    assert (r.repaid, r.left_out, r.lines) == (3500.0, 0.0, 2)
    assert "s458" in r.note


def test_thirty_day_rule_leaves_out_relent():
    lines = [_l(date(2025, 4, 20), credit=10000, desc="Repaid"),
             _l(date(2025, 5, 5), debit=8000, desc="Drawn again"),
             _l(date(2025, 8, 1), credit=1000)]
    r = repaid_after(END, lines)
    assert (r.repaid, r.left_out) == (3000.0, 8000.0)
    assert "s464ZA" in r.note


def test_small_relending_not_matched():
    lines = [_l(date(2025, 4, 20), credit=10000), _l(date(2025, 5, 5), debit=3000)]
    assert repaid_after(END, lines).repaid == 10000.0


def test_pay_credited_is_not_matched():
    # Pay credited to the loan is taxed on the director: the 30 day rule does not apply to it (s464ZA(6))
    lines = [_l(date(2025, 4, 30), credit=10280, desc="Sarah Garrett"),
             _l(date(2025, 4, 30), debit=10280, desc="Sarah Garrett", code=3010, account="Directors' remuneration"),
             _l(date(2025, 5, 5), debit=6000, desc="Drawn")]
    r = repaid_after(END, lines)
    assert (r.repaid, r.left_out) == (10280.0, 0.0)
