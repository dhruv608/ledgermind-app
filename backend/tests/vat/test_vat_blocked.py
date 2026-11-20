"""Input VAT that cannot be claimed: VAT on costs that carry none (V-D06) and on cars
and fuel (V-D07)."""

from backend.app.services.tax.vat_blocked import cars_and_fuel, no_vat_costs, no_vat_group, vat_by_code

NAMES = {3260: "Insurance", 3110: "Rates", 3351: "Bank charges", 3131: "Water rates", 3352: "Card charges",
         5400: "Director's loan", 5300: "VAT", 3215: "Hire and leasing of motor vehicles", 4131: "Motor vehicles - additions",
         3231: "Vehicle fuel costs", 3273: "Postage", 7000: "Other"}
name = lambda c: NAMES.get(c, str(c))


def test_groups():
    assert no_vat_group(3260) and no_vat_group(3110) and no_vat_group(3351) and no_vat_group(3050) is None
    assert no_vat_group(3010) and no_vat_group(5400)
    for left_out in (3131, 3352, 3273, 3215, 3231, 3250, 3002, 3012, 5352):
        assert no_vat_group(left_out) is None, left_out


def test_vat_on_insurance_rates_and_bank_charges_is_listed_with_its_journal():
    rows = [(3260, 300.0, "GL-1"), (3260, 328.49, "GL-2"), (3110, 340.0, "GL-3"), (3351, 3.0, "GL-4"),
            (3131, 30.0, "GL-5"), (3352, 12.0, "GL-6"), (5400, -29.58, "GL-7")]
    p = no_vat_costs(vat_by_code(rows), name)
    assert p.ref == "V-D06" and p.amount == round(628.49 + 340 + 29.58, 2)
    assert "Dr 3260 Insurance (£628.49) / Cr 5300 VAT (£628.49)" in p.journal
    assert "Dr 5300 VAT (£29.58) / Cr 5400 Director's loan (£29.58)" in p.journal
    assert "3351" not in p.journal and "3131" not in p.journal and "3352" not in p.journal


def test_nothing_when_moved_already_or_small():
    by = vat_by_code([(3260, 200.0, "GL-1"), (3110, 4.0, "GL-2")])
    assert no_vat_costs(by, name, lambda c: 200.0 if c == 3260 else 0.0) is None
    assert no_vat_costs(vat_by_code([(7000, 500.0, "GL-1")]), name) is None


def test_cars_question_with_half_lease_and_full_purchase():
    p = cars_and_fuel(vat_by_code([(3215, 1000.0, "GL-1"), (4131, 3900.0, "GL-2"), (3231, 200.0, "GL-3")]), name)
    assert p.ref == "V-D07" and p.amount == 5100.0
    assert "Dr 3215 Hire and leasing of motor vehicles (£500.00) / Cr 5300 VAT (£500.00)" in p.journal
    assert "Dr 4131 Motor vehicles - additions (£3,900.00)" in p.journal
    assert "car or a van" in p.details and "fuel scale charge" in p.details


def test_cars_small_is_nothing():
    assert cars_and_fuel(vat_by_code([(3231, 26.0, "GL-1")]), name) is None
