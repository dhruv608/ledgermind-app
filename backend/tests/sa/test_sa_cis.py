"""CIS payment and deduction statements read (made-up figures): the sums, the rate, the tax month (R-SA103-10)."""

from backend.app.sa.extract import cis as C
from backend.app.sa.extract.classify import classify


def test_a_statement_that_adds_up():
    f = C.clean({"contractor": "A Build Ltd", "subcontractor": "Jo Trades", "month_end": "2025-05-05",
                 "gross": "2,400.00", "materials": 400, "rate": "20%", "deducted": 400, "payable": 2000})
    assert C.checks(f, "2025-26", "Jo Trades") == ("READ", [])


def test_wrong_sums_rate_or_year():
    f = C.clean({"month_end": "2025-06-05", "gross": 1000, "materials": 0, "rate": 20, "deducted": 150, "payable": 850})
    assert any("not 20% of" in n for n in C.checks(f, "2025-26")[1])
    g = C.clean({"month_end": "2025-06-05", "gross": 1000, "rate": 25, "deducted": 250})
    assert any("not a CIS rate" in n for n in C.checks(g, "2025-26")[1])
    assert C.checks(C.clean({"month_end": "2025-04-05", "gross": 10, "deducted": 2}), "2025-26")[0] == "OTHER_YEAR"


def test_sorted_as_a_cis_statement():
    assert classify("Construction Industry Scheme Payment and deduction statement", "scan.pdf") == "CIS_STATEMENT"
    assert classify("", "Jo - CIS300 for May.pdf") == "CIS_STATEMENT"
