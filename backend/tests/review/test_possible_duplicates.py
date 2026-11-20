"""Possible duplicates: same contact and amount within a week, one with no number."""

from datetime import date

from backend.app.services.sop.duplicates import LedgerDocument, find_duplicates


def _bill(day, number, amount=250.0, contact="Supplier A Ltd"):
    return LedgerDocument("supplier", "document", date(2025, 5, day), contact, number, amount, "Bill")


def _possible(docs):
    return [(f.contact, f.amount, f.detail) for f in find_duplicates(docs, {}, date(2025, 12, 31)) if f.check == "possible"]


def test_same_amount_within_a_week_one_without_a_number():
    found = _possible([_bill(1, "INV-1"), _bill(4, "")])
    assert len(found) == 1 and "01/05/2025" in found[0][2] and "04/05/2025" in found[0][2]
    assert len(_possible([_bill(1, ""), _bill(2, "")])) == 1


def test_not_raised():
    assert _possible([_bill(1, "INV-1"), _bill(4, "INV-7")]) == []                  # two numbers: separate bills
    assert _possible([_bill(1, ""), _bill(8, "")]) == []                            # weekly bill, 7 days apart
    assert _possible([_bill(1, ""), _bill(3, "", amount=251.0)]) == []              # different amount
    assert _possible([_bill(1, ""), _bill(3, "", contact="Supplier B")]) == []
    assert _possible([_bill(1, "", amount=99.0), _bill(3, "", amount=99.0)]) == []  # under £100
    flags = find_duplicates([_bill(1, "INV-1"), _bill(3, "INV-1")], {}, date(2025, 12, 31))
    assert [f.check for f in flags] == ["duplicate"]                               # same number: test 1, not both
