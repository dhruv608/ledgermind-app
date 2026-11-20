"""Pensions, State Pension, benefits and contributions read (made-up figures): the weekly State Pension made a year,
relief at source v net pay, the annual allowance, another year and another person, and the same payer as a P60
(R-SAV-06, R-SAV-07, R-SP-02)."""

from backend.app.sa.extract import pension as P
from backend.app.sa.extract.classify import classify


def test_state_pension_weekly_rate_made_a_year():
    f = P.clean({"person": "Pat Pensioner", "items": [
        {"kind": "STATE_PENSION", "payer": "DWP", "name": "New State Pension", "weekly_amount": "230.25", "rate_from": "2025-04-07"}]})
    status, notes = P.checks(f, "2025-26", "Pat Pensioner")
    assert f["items"][0]["amount"] == 11973.0 and status == "CHECK" and "R-SP-02" in notes[0]


def test_a_pension_with_tax_and_a_contribution():
    f = P.clean({"period_from": "2025-04-06", "period_to": "2026-04-05", "items": [
        {"kind": "PENSION", "payer": "Example Pension Plan", "year_amount": 20205.81, "tax_deducted": 2100},
        {"kind": "CONTRIBUTION", "payer": "A SIPP", "year_amount": 2400, "contribution_basis": "RELIEF_AT_SOURCE"}]})
    assert P.checks(f, "2025-26") == ("READ", [])
    g = P.clean({"items": [{"kind": "CONTRIBUTION", "payer": "Work scheme", "year_amount": 50000, "contribution_basis": "NET_PAY",
                            "employer_amount": 15000}]})
    status, notes = P.checks(g, "2025-26")
    assert status == "CHECK" and any("R-SAV-07" in n and "net pay" in n for n in notes) and any("annual allowance" in n for n in notes)


def test_another_year_or_person_and_the_same_payer():
    f = P.clean({"period_from": "2024-04-06", "period_to": "2025-04-05", "items": [{"kind": "PENSION", "year_amount": 10}]})
    assert P.checks(f, "2025-26")[0] == "OTHER_YEAR"
    g = P.clean({"person": "Alex Other", "items": [{"kind": "PENSION", "year_amount": 10}]})
    assert P.checks(g, "2025-26", "Pat Pensioner")[0] == "CHECK" and g["other_person"]
    assert P.same_payer("Cummins Uk plan", "Cummins UK Pension Plan Premier Pensions Management")
    assert not P.same_payer("Standard Life", "Cummins UK Pension Plan")


def test_a_dwp_letter_is_sorted_as_one():
    assert classify("Department for Work and Pensions. Your State Pension from 7 April 2025", "letter.pdf") == "DWP_LETTER"
    assert classify("Carer's Allowance: how much you will get", "scan.pdf") == "DWP_LETTER"


def test_taxable_benefits_from_bank_credits():
    pages = [{"lines": [["2025-05-02", "BANK GIRO CREDIT REF NR926857C DWP CA", 330.0, None, 500.0],
                        ["2025-06-02", "DWP PIP 0000123", 400.0, None, 900.0],
                        ["2025-07-01", "BANK GIRO CREDIT REF NR926857C DWP CA", 411.3, None, 1311.3],
                        ["2025-03-30", "DWP CA", 81.9, None, 100.0]]}]
    assert P.bank_benefits(pages, "2025-04-06", "2026-04-05") == {"Carer's Allowance": 741.3}


def test_a_contribution_is_kept_net():
    f = P.clean({"items": [{"kind": "CONTRIBUTION", "year_amount": 8990, "net_amount": 7192, "gross_amount": 8990,
                            "contribution_basis": "RELIEF_AT_SOURCE"}]})
    assert f["items"][0]["year_amount"] == 7192.0
    g = P.clean({"items": [{"kind": "CONTRIBUTION", "gross_amount": 1250, "contribution_basis": "RELIEF_AT_SOURCE"}]})
    assert g["items"][0]["year_amount"] == 1000.0


def test_a_payer_with_a_digit_in_its_name_is_one_payer():
    assert P.same_payer("Payer4X Pension Scheme (GSL)", "PAYER4X PENSION SCHEME")
    assert P.same_payer("Cummins UK Pension Plan", "Cummins Uk plan")
    assert not P.same_payer("Aviva 2024", "Scottish Widows 2024")      # a year alone is not the payer's name


def test_a_dwp_letter_for_next_years_rate_is_not_this_years():
    item = {"kind": "STATE_PENSION", "payer": "DWP", "name": "New State Pension", "year_amount": None, "weekly_amount": 230.25,
            "rate_from": "2025-04-12", "tax_deducted": 0.0, "basis": None}
    assert P.checks({"items": [dict(item)], "period_from": None, "period_to": None}, "2024-25")[0] == "OTHER_YEAR"
    this_year = dict(item, weekly_amount=221.20, rate_from="2024-04-13")
    assert P.checks({"items": [this_year], "period_from": None, "period_to": None}, "2024-25")[0] == "CHECK"   # weekly x 52: to check


def test_the_prompts_own_words_are_not_a_name():
    from backend.app.sa.extract import pension, sa302
    assert pension.clean({"person": "the person's full name as printed or null", "items": []})["person"] is None
    assert sa302.clean({"name": "the person's name", "tax_year": "2024-25"})["name"] is None
    assert sa302.clean({"name": "Pat Example"})["name"] == "Pat Example"


def test_lump_sums_only_the_taxable_part_counts():
    """O13-O16 (PN4-PN7): tax-free cash is not income; the provider's split decides the taxable part;
    no split is a point, not a guess; emergency tax and the money purchase annual allowance are raised."""
    f = P.clean({"period_from": "2025-04-06", "period_to": "2026-04-05", "items": [
        {"kind": "LUMP_SUM", "payer": "Example Pensions", "lump_type": "UFPLS", "year_amount": 20000,
         "tax_free_amount": 5000, "tax_deducted": 5500},
        {"kind": "LUMP_SUM", "payer": "Example Pensions", "lump_type": "PCLS", "year_amount": 30000},
        {"kind": "LUMP_SUM", "payer": "Other Pensions", "lump_type": "SMALL_POT", "year_amount": 8000}]})
    status, notes = P.checks(f, "2025-26")
    ufpls, pcls, pot = f["items"]
    assert (ufpls["amount"], pcls["amount"], pot["amount"]) == (15000, 0.0, None) and status == "CHECK"
    assert any("O15" in n and "P55" in n for n in notes) and any("O16" in n and "10,000" in n for n in notes)
    assert any("O14" in n for n in notes) and any("O13" in n and "Other Pensions" in n for n in notes)
    # A small pot does not start the money purchase annual allowance; drawdown income is all taxable
    g = P.clean({"items": [{"kind": "LUMP_SUM", "payer": "X", "lump_type": "SMALL_POT", "year_amount": 8000, "taxable_amount": 6000,
                            "tax_deducted": 1200},
                           {"kind": "LUMP_SUM", "payer": "Y", "lump_type": "DRAWDOWN", "year_amount": 4000, "tax_deducted": 800}]})
    status, notes = P.checks(g, "2025-26")
    assert [i["amount"] for i in g["items"]] == [6000, 4000]
    assert not any("X:" in n and "O16" in n for n in notes) and any("Y:" in n and "O16" in n for n in notes)


def test_annual_allowance_on_the_total_input():
    """L4/C18: the person's gross contributions and the employer's together against £60,000."""
    f = P.clean({"items": [{"kind": "CONTRIBUTION", "payer": "A SIPP", "net_amount": 40000, "contribution_basis": "RELIEF_AT_SOURCE"}]})
    assert not any("annual allowance" in n for n in P.checks(f, "2025-26")[1])           # £50,000 gross: under
    g = P.clean({"items": [{"kind": "CONTRIBUTION", "payer": "A SIPP", "net_amount": 40000, "contribution_basis": "RELIEF_AT_SOURCE",
                            "employer_amount": 12000}]})
    notes = P.checks(g, "2025-26")[1]
    assert any("62,000.00" in n and "C18" in n for n in notes)
