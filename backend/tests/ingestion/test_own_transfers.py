"""Transfers between the client's own accounts paired; the one-sided ones listed."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.workbook.balance_tabs.transfers import own_transfers


def _tx(when, code, desc, debit=0.0, credit=0.0):
    return (when, code, "Bank", f"Bank {code}", "Transfer", desc, "", debit, credit)


def test_pairs_and_one_sided():
    rows = [_tx("12/09/2024", "4800", "TRANSFER TO Fixed Fee Account 309870", credit=20000),
            _tx("13/09/2024", "4801", "TRANSFER FROM Current account", debit=20000),
            _tx("01/10/2024", "4800", "TFR to savings", credit=500),
            _tx("02/10/2024", "4800", "Transfer to J Smith", credit=300),        # a payment to a person, not own
            _tx("05/10/2024", "5200", "TFR", credit=50)]                         # not a bank code
    pairs, total, alone, returned = own_transfers(rows)
    assert pairs == 1 and total == 20000.0 and returned == 0
    assert [a[3] for a in alone] == [-500.0]


def test_out_and_back_to_the_same_account():
    rows = [_tx("12/09/2024", "4800", "TRANSFER TO Fixed Fee Account", credit=20000),
            _tx("17/09/2024", "4800", "TRANSFER FROM Fixed Fee Account", debit=20000)]
    assert own_transfers(rows) == (0, 0.0, [], 1)
