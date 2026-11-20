"""Mortgage interest certificates and dividend vouchers read (made-up figures): the tax year, the owner, ISA
dividends left out (R-SA105-05, R-SAV-04, R-SAV-05)."""

from backend.app.sa.extract import dividend as D, mortgage as M


def test_mortgage_interest_for_the_year():
    f = M.clean({"lender": "A Bank", "borrowers": ["Rob Landlord"], "property_address": "56 Elm Street",
                 "period_from": "2025-04-06", "period_to": "2026-04-05", "interest": "3,987.00"})
    assert M.checks(f, "2025-26", "Rob Landlord") == ("READ", []) and f["interest"] == 3987.0
    g = M.clean({"period_from": "2025-01-01", "period_to": "2025-12-31", "interest": 1200})
    status, notes = M.checks(g, "2025-26")
    assert status == "CHECK" and "6 April to 5 April" in notes[0]
    # A calendar-year statement: the tax year's days of it (6 April to 31 December 2025: 270 of 365 days; R16)
    assert g["interest_year"] == round(1200 * 270 / 365, 2) and "R16" in notes[0]
    assert M.checks(M.clean({"period_from": "2023-04-06", "period_to": "2024-04-05", "interest": 5}), "2025-26")[0] == "OTHER_YEAR"


def test_dividends_in_the_year_and_isa():
    f = D.clean({"shareholder": "Dee Investor", "dividends": [
        {"company": "Big plc", "pay_date": "2025-09-15", "amount": "120.40"},
        {"company": "Big plc", "pay_date": "2025-03-15", "amount": 110}]})
    status, notes = D.checks(f, "2025-26", "Dee Investor")
    assert [d["amount"] for d in f["dividends"]] == [120.4] and "outside 2025-26" in notes[0]
    g = D.clean({"isa": True, "dividends": [{"company": "Fund", "pay_date": "2025-06-01", "amount": 50}]})
    assert any("ISA" in n for n in D.checks(g, "2025-26")[1])
    h = D.clean({"shareholder": "Alex Other", "dividends": [{"company": "X", "pay_date": "2025-06-01", "amount": 5}]})
    assert D.checks(h, "2025-26", "Dee Investor")[0] == "CHECK" and h["other_person"]
