"""VAT or corporation tax paid to HMRC but posted to the PAYE account (U-PAY-022): read from the bank
narrative, as on the VAT account (V-M08)."""

from backend.app.services.review.paye_check import paye_line_kind


def test_vat_by_its_narrative_and_ndds():
    assert paye_line_kind("HMRC VAT - HMRC NDDS 100000001") == "VAT"
    assert paye_line_kind("HMRC - Hmrc Vat 300000001") == "VAT"
    assert paye_line_kind("HMRC PAYE - HMRC COTAX 1234567890A00101") == "CT"


def test_paye_stays_paye():
    assert paye_line_kind("HMRC VAT - Hmrc Cumbernauld 120PX00000001") == ""     # the PAYE office and its reference
    assert paye_line_kind("HMRC - HMRC PAYE 123PA00000001") == ""
    assert paye_line_kind("HMRC - HMRC NIC") == ""
    assert paye_line_kind("HMRC Shipley - Hmrc Ndds HMRC") == ""                # paid to the PAYE office
    assert paye_line_kind("HMRC VAT") == ""                                   # a contact name only says nothing
    assert paye_line_kind("Move to payment of CT Y_E 31 Mar 2025") == ""       # no narrative
    assert paye_line_kind("HMRC - Hmrc Vat 300000001", "Journal") == ""        # a journal moves amounts, pays nothing
