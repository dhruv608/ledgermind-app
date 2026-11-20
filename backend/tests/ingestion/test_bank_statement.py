"""Statement lines against ledger lines: matched, unmatched, unrecorded."""

from datetime import date

from backend.app.services.reconciliation.bank_statement import match_lines


def line(i, d, amount):
    return {"id": i, "date": d, "description": i, "amount": amount}


def test_match_nearest_date_once_each():
    stmt = [line("s1", date(2025, 4, 3), -50.0), line("s2", date(2025, 4, 10), -50.0), line("s3", date(2025, 4, 12), -12.5)]
    ledger = [line("g1", date(2025, 4, 9), -50.0), line("g2", date(2025, 4, 1), -50.0), line("g3", date(2025, 4, 5), 100.0)]
    matched, unmatched, unrecorded = match_lines(stmt, ledger)
    pairs = {m["statement"]["id"]: m["ledger"]["id"] for m in matched}
    assert pairs == {"s1": "g2", "s2": "g1"}
    assert [u["id"] for u in unrecorded] == ["s3"]          # the bank charge not in the books
    assert [u["id"] for u in unmatched] == ["g3"]           # in the books, not on the statement


def test_too_far_apart_is_not_a_match():
    matched, unmatched, unrecorded = match_lines([line("s", date(2025, 4, 1), 10.0)], [line("g", date(2025, 4, 20), 10.0)])
    assert not matched and len(unmatched) == 1 and len(unrecorded) == 1
