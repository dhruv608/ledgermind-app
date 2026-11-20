"""V-A04: the same supplier coded more than one VAT way on the same account."""
from datetime import date

from backend.app.services.tax.vat_codes import describe, supplier_mixes, vat_rate

SOFT = "3241 - Computer Software Costs"


def line(desc, code, net=10.0, account=SOFT, d=date(2025, 3, 1)):
    return (account, desc, d, net, code)


def test_one_odd_line_from_a_supplier_is_listed():
    lines = [line("Supplier A - Monthly plan", "20% (VAT on Expenses)") for _ in range(5)]
    lines.append(line("Supplier A - Monthly plan", "No VAT", 12.0, d=date(2025, 6, 1)))
    mixes = supplier_mixes(lines)
    assert len(mixes) == 1 and mixes[0].usual == "20% (VAT on Expenses)" and mixes[0].usual_lines == 5
    assert [o.code for o in mixes[0].odd] == ["No VAT"] and mixes[0].rate_differs
    title, details, amount, severity = describe(mixes)
    assert "1 supplier(s)" in title and amount == 12.0 and severity == "LOW"
    assert "01/06/2025 £12.00 'No VAT'" in details and "Supplier A coded at different VAT rates" in details


def test_different_suppliers_on_one_account_are_not_a_mix():
    # A UK plan at 20% and an overseas one reverse charged: the VAT follows the supply (VATA 1994 s8)
    lines = [line("Supplier A - plan", "20.0% S") for _ in range(4)] + [line("Supplier B - plan", "20.0% RC SG")
                                                                        for _ in range(4)]
    assert supplier_mixes(lines) == []


def test_too_few_lines_or_no_usual_code_is_not_judged():
    assert supplier_mixes([line("Supplier A", "20.0% S"), line("Supplier A", "No VAT")]) == []
    tie = [line("Supplier A", "20.0% S"), line("Supplier A", "20.0% S"), line("Supplier A", "No VAT"),
           line("Supplier A", "No VAT")]
    assert supplier_mixes(tie) == []


def test_uncoded_lines_and_missing_dates_are_left_alone():
    lines = [line("Supplier A", "Exempt") for _ in range(3)] + [line("Supplier A", ""), line("Supplier A", "No VAT", d=None)]
    mixes = supplier_mixes(lines)
    assert len(mixes) == 1 and not mixes[0].rate_differs       # two names for nil VAT
    assert "no date" in describe(mixes)[1]


def test_rates_read_from_code_names():
    assert vat_rate("20% (VAT on Expenses)") == 20.0
    assert vat_rate("5.0% R") == 5.0
    assert vat_rate("No VAT") == 0.0 and vat_rate("Exempt") == 0.0
    assert vat_rate("RC SG") is None


def test_a_placeholder_is_not_a_supplier():
    lines = [line("No Name - card", "20% (VAT on Expenses)") for _ in range(5)] + [line("No Name - card", "No VAT")]
    assert supplier_mixes(lines) == []

