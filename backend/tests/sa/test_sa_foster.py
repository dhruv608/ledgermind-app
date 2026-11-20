"""Qualifying care relief (made-up figures): the limit, exempt, over the limit with each
method, no placements a client query, the letter checked (R-SP-01; HS236 2026)."""

from backend.app.sa import foster as F


def test_the_limit_and_exempt_receipts():
    two = [{"band": "ELEVEN_PLUS", "weeks": 52}, {"band": "ELEVEN_PLUS", "weeks": 52}]
    assert F.limit("2025-26", two) == 71170.0                       # 19,690 + 2 x 52 x 495
    r = F.work_out("2025-26", 53289.73, two)
    assert r["exempt"] and r["profit"] == 0.0
    assert F.limit("2025-26", [{"band": "UNDER_11", "weeks": 10}], carers=2) == 9845 + 4150


def test_over_the_limit_needs_a_method():
    one = [{"band": "UNDER_11", "weeks": 52}]                       # limit 19,690 + 21,580 = 41,270
    r = F.work_out("2025-26", 50000, one)
    assert r["profit"] == 8730.0 and r["issues"][0]["key"] == "method" and r["issues"][0]["block"]
    assert F.work_out("2025-26", 50000, one, method="ACTUAL", actual_costs=45000)["profit"] == 5000.0
    assert F.work_out("2025-26", 50000, one, method="SIMPLIFIED")["issues"] == []


def test_no_placements_is_a_client_query_and_the_letter():
    r = F.work_out("2025-26", 20000, [])
    assert r["limit"] is None and r["issues"][0]["kind"] == "CLIENT"
    f = F.clean({"carer": "Dee Carer", "period_from": "2025-04-01", "period_to": "2026-03-31", "receipts": "53,289.73"})
    status, notes = F.checks(f, "2025-26", "Dee Carer")
    # A council's year to 31 March is the tax year for the trade (ITTOIA s7B): no note
    assert f["receipts"] == 53289.73 and status == "READ" and notes == []
    odd = F.clean({"carer": "Dee Carer", "period_from": "2025-07-01", "period_to": "2026-06-30", "receipts": 100})
    assert any("not the tax year" in n for n in F.checks(odd, "2025-26", "Dee Carer")[1])
