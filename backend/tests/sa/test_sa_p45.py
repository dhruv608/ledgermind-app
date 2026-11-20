"""P45s and final payslips read (made-up figures): this employment's pay only, the tax year from the leaving date,
termination payments split, payrolled benefits noted (R-SA102-01, -06, -07)."""

from backend.app.sa.extract import p45 as F


def test_a_p45_this_employment_only():
    f = F.clean({"kind": "P45", "employee": "Sam Leaver", "employer": "A Ltd", "paye_ref": "120 AB123",
                 "leaving_date": "2025-09-30", "pay_this": "14,200.00", "tax_this": "1,650.40",
                 "pay_total": 20000, "tax_total": 2500, "pay_previous": 5800, "tax_previous": 849.6})
    assert (f["tax_year"], f["pay_this"], f["paye_ref"]) == ("2025-26", 14200.0, "120/AB123")
    assert F.checks(f, "2025-26", None, "Sam Leaver") == ("READ", [])


def test_a_final_payslip_with_compensation():
    # Taxable pay to date, tax to date, compensation under £30,000 exempt
    f = F.clean({"kind": "PAYSLIP", "final": True, "employee": "Pat Payslip", "pay_date": "2026-01-31",
                 "pay_this": 25310.05, "tax_this": 3384.60, "compensation": 6000})
    status, notes = F.checks(f, "2025-26", None, "Pat Payslip")
    assert status == "CHECK" and f["exempt_compensation"] == 6000 and "exempt" in notes[0]
    big = F.clean({"kind": "P45", "leaving_date": "2025-12-01", "pay_this": 50000, "tax_this": 9000, "compensation": 45000})
    assert any("£15,000.00 over it is taxable" in n for n in F.checks(big, "2025-26", None)[1])


def test_not_the_final_payslip_and_payrolled_benefits():
    f = F.clean({"kind": "PAYSLIP", "final": False, "pay_date": "2025-06-30", "pay_this": 6000, "tax_this": 700,
                 "payrolled_benefits": ["Car *"]})
    status, notes = F.checks(f, "2025-26", None)
    assert status == "CHECK" and any("final payslip" in n for n in notes) and any("R-SA102-07" in n for n in notes)
    other = F.clean({"kind": "P45", "leaving_date": "2024-11-30", "pay_this": 100, "tax_this": 0})
    assert F.checks(other, "2025-26", None)[0] == "OTHER_YEAR"


def test_a_payslip_takes_the_year_to_date():
    f = F.clean({"kind": "PAYSLIP", "final": True, "pay_date": "2025-11-28", "pay_this": 8689.69, "tax_this": 1528.20,
                 "taxable_pay_period": 8689.69, "tax_period": 1528.20, "taxable_pay_to_date": "25,310.05", "tax_to_date": 3384.60})
    assert (f["pay_this"], f["tax_this"]) == (25310.05, 3384.6)


def test_marriage_allowance_suffixes():
    from backend.app.sa.extract import p60
    assert p60.code_parts("1131N")["suffix"] == "N" and p60.code_parts("1383M")["suffix"] == "M"
    assert p60.code_parts("1391L M1")["suffix"] == "L"        # M1 is the month 1 basis, not Marriage Allowance
    pts = p60.code_points([{"employer": "A Council", "tax_code": "1131N"}], None, 6500)
    assert any("cut by the transfer" in p["text"] for p in pts)


def test_limits_come_from_the_rates_table():
    from backend.app.sa.extract import pension
    assert F.exempt_limit("2025-26") == 30000.0 and pension.annual_allowance("2024-25") == 60000.0


def test_the_tax_years_last_payslip_is_the_years_pay():
    # Month 12, paid 31 March, pay to date twelve months of pay (made-up figures): the year's pay, not held
    f = F.clean({"kind": "PAYSLIP", "employer": "Firm A Ltd", "pay_date": "2025-03-31", "taxable_pay_to_date": 12570,
                 "tax_to_date": 1299, "taxable_pay_period": 1047.5})
    assert f["final"] and f["year_end"] and F.checks(f, "2024-25", None)[0] == "READ"
    # Paid in January: the year is not over
    f = F.clean({"kind": "PAYSLIP", "employer": "Firm A Ltd", "pay_date": "2025-01-31", "taxable_pay_to_date": 10475,
                 "tax_to_date": 1080, "taxable_pay_period": 1047.5})
    assert not f["final"] and F.checks(f, "2024-25", None)[0] == "CHECK"
    # March but only a few months to date (a job started in the year, monthly): left to check
    f = F.clean({"kind": "PAYSLIP", "employer": "Firm A Ltd", "pay_date": "2025-03-10", "taxable_pay_to_date": 3000,
                 "tax_to_date": 100, "taxable_pay_period": 1000})
    assert not f["final"]


def test_compensation_asks_for_the_settlement_split():
    """C14: post-employment notice pay is taxed in full before the £30,000 (ITEPA s402A-E)."""
    f = F.clean({"kind": "P45", "leaving_date": "2025-12-01", "pay_this": 20000, "tax_this": 3000, "compensation": 12000})
    assert any("C14" in n and "settlement agreement" in n for n in F.checks(f, "2025-26", None)[1])
