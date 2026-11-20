"""Open invoices / bills on the aged list cleared by payments in next year's ledger (oldest first)."""
import os
from datetime import date
from types import SimpleNamespace as N

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.review.paid_after import note_for, paid_after, paid_total


def _line(when, code, desc, debit=0.0, credit=0.0):
    return N(when=when, code=code, description=desc, reference="", debit=debit, credit=credit)


def test_bills_matched_by_name():
    items = [N(contact="Storage Solution Ltd", amount=298.24, when=date(2025, 3, 1)),
             N(contact="GES Limited", amount=222.18, when=date(2025, 3, 2)),
             N(contact="Faire", amount=250.28, when=date(2025, 3, 3))]
    lines = [_line(date(2025, 4, 3), 5200, "Storage Solution", debit=298.24),
             _line(date(2025, 4, 9), 5200, "GES LIMITED - payment", debit=100.00),        # part of the bill
             _line(date(2025, 4, 9), 4400, "Faire payout", credit=250.28)]                 # debtors side: not a bill
    m = paid_after(items, lines, owed=True)
    assert m == {0: (date(2025, 4, 3), 298.24), 1: (None, 100.0)}
    assert paid_total(items, m) == (770.70, 398.24)
    assert note_for(m.get(0), True) == "Paid 03/04/2025" and note_for(m.get(1), True) == "Part paid £100.00"
    assert note_for(None, True).startswith("Not paid")


def test_customer_pays_in_parts_oldest_first():
    # A customer paying in several smaller sums: they clear the oldest invoice first, then the next
    items = [N(contact="Fenix International", amount=1963.60, when=date(2025, 1, 31)),
             N(contact="Fenix International", amount=764.93, when=date(2024, 11, 30))]
    lines = [_line(date(2025, 2, 10), 4400, "Fenix International", credit=500.00),
             _line(date(2025, 2, 13), 4400, "FENIX INTERNATIONAOF INV 7020", credit=651.57),
             _line(date(2025, 2, 19), 4400, "Fenix International", credit=2000.00),
             _line(date(2025, 2, 20), 4400, "Someone Else", credit=764.93)]
    m = paid_after(items, lines, owed=False)
    assert m == {1: (date(2025, 2, 13), 764.93), 0: (date(2025, 2, 19), 1963.60)}


def test_customer_receipts():
    items = [N(contact="In-Residence Designer", amount=559.28, when=None)]
    lines = [_line(date(2025, 5, 2), 4400, "IN-RESIDENCE DESIGNER LTD", credit=559.28)]
    assert paid_after(items, lines, owed=False) == {0: (date(2025, 5, 2), 559.28)}
