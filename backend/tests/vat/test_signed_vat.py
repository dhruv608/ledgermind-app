"""The ledger's VAT with the line's sign: Xero signs its VAT column, QuickBooks does not (a sale's VAT shows +)."""

from backend.app.models.database import GLTransaction, signed_vat


def test_quickbooks_sale_vat_becomes_a_credit():
    assert signed_vat(35.0, 0.0, 175.0) == -35.0          # QuickBooks invoice line: credit 175, VAT 35
    assert signed_vat(-35.0, 0.0, 175.0) == -35.0         # Xero: already signed


def test_debits_and_empties_stay():
    assert signed_vat(20.0, 100.0, 0.0) == 20.0           # a purchase
    assert signed_vat(-20.0, 100.0, 0.0) == -20.0          # left as the ledger gives it
    assert signed_vat(None, 0.0, 50.0) == 0.0


def test_the_line_property():
    tx = GLTransaction(raw_account_name="Sales", vat_amount=35.0, debit_amount=0.0, credit_amount=175.0)
    assert tx.signed_vat == -35.0
