"""HMRC's tax calculation read (made-up figures): last year's sets this year's payments on account; another year is not
used (R-EX-01, R-FAM-03; TMA s59A)."""

from backend.app.sa.extract import sa302 as S


def test_payments_on_account_from_last_year():
    f = S.clean({"tax_year": "2024-25", "income_tax": "4,772.40", "class4": 837.72, "tax_deducted": 1351, "due": 4259.12})
    assert S.checks(f, "2025-26") == ("READ", [])
    assert S.poa_from_last_year(f) == 2129.56                 # (4,772.40 + 837.72 - 1,351) / 2
    assert S.poa_from_last_year(S.clean({"income_tax": 900, "tax_deducted": 0})) == 0.0          # under £1,000
    assert S.poa_from_last_year(S.clean({"income_tax": 10000, "tax_deducted": 8500})) == 0.0     # 80% at source


def test_another_year_is_not_used():
    assert S.checks(S.clean({"tax_year": "2022-23", "due": 5}), "2025-26")[0] == "OTHER_YEAR"
