"""Amortisation and impairment of intangibles in the CT computation (CTA 2009 Part 8): goodwill added
back with a query, other intangibles added back until confirmed unless the firm allows them, the reviewer's confirmed
amount allowed; 'Amortisation (Depreciation)' 3500 is not counted as depreciation too."""
from datetime import date
from types import SimpleNamespace as N

from backend.app.services.tax.ct_computation import compute

PL, BS = "Profit and Loss", "Balance Sheet"
CHART = {
    100: N(std_name="Sales", category="Sales", financial_class=PL),
    3400: N(std_name="Depreciation - plant", category="Depreciation", financial_class=PL),
    3500: N(std_name="Amortisation (Depreciation)", category="Depreciation", financial_class=PL),
    2850: N(std_name="Amortisation (Distribution costs)", category="Distribution costs", financial_class=PL),
    3551: N(std_name="Impairment loss - Intangible assets", category="Depreciation", financial_class=PL),
    4000: N(std_name="Goodwill cost", category="Intangible assets", financial_class=BS),
    4005: N(std_name="Goodwill - amortisation charge in year", category="Intangible assets", financial_class=BS),
    4010: N(std_name="Other intangible cost", category="Intangible assets", financial_class=BS),
    4014: N(std_name="Other intangible - amortisation charge in year", category="Intangible assets", financial_class=BS),
}


def run(balances, **inputs):
    c = compute(date(2024, 5, 1), date(2025, 4, 30), {100: -100000.0, **balances}, CHART, inputs, {})
    added = sum(l.amount for l in c.lines if l.label.startswith("Add: amortisation"))
    depreciation = sum(l.amount for l in c.lines if l.label == "Add: depreciation")
    return c, round(added, 2), round(depreciation, 2)


def test_goodwill_added_back_with_a_query_and_not_counted_as_depreciation():
    # Goodwill held, £264 on 3500, plus £827 plant depreciation
    c, added, dep = run({3500: 264.0, 3400: 827.0, 4000: 19050.0, 4005: -264.0})
    assert added == 264.0 and dep == 827.0
    assert any("Goodwill amortisation" in n and "related" in n for n in c.notes)


def test_goodwill_split_unknown_is_treated_as_goodwill():
    c, added, _ = run({3500: 500.0, 4000: 5000.0})
    assert added == 500.0
    assert any("Goodwill amortisation" in n for n in c.notes)


def test_other_intangibles_added_back_until_confirmed_by_default():
    c, added, _ = run({2850: 300.0, 4010: 3000.0})
    assert added == 300.0
    assert any("until confirmed" in n for n in c.notes)


def test_firm_allows_other_intangibles_but_goodwill_still_added_back():
    c, added, _ = run({3500: 400.0, 4005: -100.0, 4014: -300.0, 4000: 1.0, 4010: 1.0}, intangibles_policy="ALLOW")
    assert added == 100.0
    assert any("allowed with the accounts" in n for n in c.notes)


def test_confirmed_amount_is_allowed():
    c, added, _ = run({3500: 264.0, 3551: 100.0, 4000: 19050.0, 4005: -264.0}, amortisation_allowed=64.0)
    assert added == 300.0
    assert any("£64.00 allowed as confirmed" in n for n in c.notes)


def test_no_intangibles_no_line():
    c, added, _ = run({3400: 827.0})
    assert added == 0.0 and not any("ntangible" in n for n in c.notes)


def test_goodwill_amount_kept_for_the_query():
    c, _, _ = run({3500: 264.0, 4000: 19050.0, 4005: -264.0})
    assert c.goodwill_added_back == 264.0
    c, _, _ = run({3500: 264.0, 4000: 19050.0, 4005: -264.0}, amortisation_allowed=264.0)
    assert c.goodwill_added_back == 0.0
