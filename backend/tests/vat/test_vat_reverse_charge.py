"""Reverse charge VAT codes as Xero and QuickBooks name them: the customer accounts for the VAT in Box 1 and Box 4
(VATA 1994 s8, s55A); the supplier's side of the construction reverse charge ('0.0% RC') is not one."""

from backend.app.services.tax.vat_review import reverse_charge_code


def test_reverse_charge_codes():
    for code in ("Reverse Charge Expenses (20%)", "20.0% RC SG", "20.0% RC CIS", "RC", "rc"):
        assert reverse_charge_code(code), code


def test_not_reverse_charge():
    for code in ("0.0% RC", "0% RC", "20.0% S", "Exempt", "No VAT", "Circular", "", None):
        assert not reverse_charge_code(code), code
