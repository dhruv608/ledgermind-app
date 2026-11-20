"""The employment status screen (made-up lines): one customer over 80%, a fixed monthly fee, the same payer an
employer (R-SA103-10)."""

from backend.app.sa.status import payer, signals


def test_one_customer_and_a_fixed_fee():
    lines = [(f"2025-{m:02d}-28", "FASTER PAYMENTS RECEIPT REF.INV FROM ACME CONSULTING LTD", 3000.0) for m in range(4, 13)]
    lines.append(("2025-09-01", "FROM SMALL JOB CO", 200.0))
    found = signals(lines, employers=[])
    assert any("from one payer (acme consulting)" in f for f in found) and any("9 months" in f for f in found)


def test_the_payer_is_also_the_employer():
    found = signals([("2025-06-01", "BGC ACME HOTELS", 400.0)], ["Acme Hotels Limited"], trading_allowance=True)
    assert any("also employs" in f and "trading allowance" in f for f in found)
    assert payer("FASTER PAYMENTS RECEIPT REF.12 FROM ACME HOTELS LTD") == "acme hotels"


def test_a_spread_of_customers_raises_nothing():
    lines = [("2025-05-01", f"FROM {name} CO", 1000.0) for name in ("ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT")]
    assert signals(lines, []) == []


def test_the_payer_is_after_from():
    assert payer("FASTER PAYMENTS RECEIPT REF.JOB COMPENSATION FROM A CUSTOMER") == "customer"
    assert payer("Invoice payment from AAMS AAMS") == "aams"


def test_a_day_rate_own_money_and_card_machines():
    from backend.app.sa.status import signals
    week = [(f"2025-11-{d:02d}", "BRANDON HOTEL, DAY RATE", 650.0) for d in (3, 10, 17, 24)] + \
           [(f"2025-12-{d:02d}", "BRANDON HOTEL, DAY RATE", 650.0) for d in (1, 8)] + [("2025-12-20", "OTHER CO LTD", 6000.0)]
    assert any("6 times: a fixed daily or weekly fee" in s for s in signals(week, []))
    own = [(f"2025-{m:02d}-01", "PAT TESTER", 50.0) for m in range(4, 13)] + [("2025-06-01", "SUMUP PAYMENTS", 9000.0)]
    assert signals(own, [], person="Pat Tester") == []
    assert signals([("2025-06-01", "RENT RECEIVED", 9000.0)], []) == []
