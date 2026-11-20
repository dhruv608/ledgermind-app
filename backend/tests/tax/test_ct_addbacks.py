"""CT add-backs: a loan's early repayment charge is not a fine (BIM42515, CTA 2009 s1303),
capital legal costs added back (s53), gifts added back (s1298), charitable donations relieved only when paid (CTA 2010
s189)."""
from datetime import date
from types import SimpleNamespace as N

from backend.app.services.tax.ct_computation import CAPITAL_LEGAL, FINE_LINE, GIFT_LINE, NOT_A_CLIENT_GIFT, NOT_A_FINE, \
    compute

PL = "Profit and Loss"
CHART = {100: N(std_name="Sales", category="Sales", financial_class=PL),
         3302: N(std_name="Legal fees", category="General admin", financial_class=PL),
         3360: N(std_name="Charitable donations", category="General admin", financial_class=PL)}


def run(balances, **kw):
    return compute(date(2024, 4, 1), date(2025, 3, 31), {100: -100000.0, **balances}, CHART, {}, {}, **kw)


def amount(c, start):
    return round(sum(l.amount for l in c.lines if l.label.startswith(start)), 2)


def test_a_loan_penalty_is_not_a_fine():
    line = "Funding Circle early repayment penalty"
    assert FINE_LINE.search(line) and NOT_A_FINE.search(line)
    assert not NOT_A_FINE.search("Parking fine PCN Camden")


def test_capital_legal_costs_and_gifts_added_back():
    assert CAPITAL_LEGAL.search("Smith Solicitors - conveyancing 12 High St")
    assert not CAPITAL_LEGAL.search("Solicitors - employment contract advice")
    assert GIFT_LINE.search("Christmas hampers for clients") and not NOT_A_CLIENT_GIFT.search("Christmas hampers for clients")
    assert NOT_A_CLIENT_GIFT.search("Staff Christmas gifts")
    c = run({3302: 2000.0}, capital_legal=1500.0, gifts=300.0)
    assert amount(c, "Add: legal costs of a capital nature") == 1500.0
    assert amount(c, "Add: gifts") == 300.0


def test_donations_relieved_only_when_paid():
    paid = run({3360: 1000.0}, donations_paid=400.0)
    assert amount(paid, "Less: qualifying charitable donations") == -400.0
    assert any("not paid in the period" in n for n in paid.notes)
    ledger_unknown = run({3360: 1000.0})
    assert amount(ledger_unknown, "Less: qualifying charitable donations") == -1000.0


def test_partial_writing_down_allowance_claim():
    full = compute(date(2024, 4, 1), date(2025, 3, 31), {100: -100000.0}, CHART, {"main_pool_bf": 10000}, {})
    part = compute(date(2024, 4, 1), date(2025, 3, 31), {100: -100000.0}, CHART,
                   {"main_pool_bf": 10000, "main_wda_claim": 500}, {})
    assert full.main_pool_cf == 8200.0                     # 18% claimed in full
    assert part.main_pool_cf == 9500.0                     # 500 claimed, the rest stays in the pool (CAA 2001 s56(5))
    assert any("s56(5)" in n for n in part.notes)
