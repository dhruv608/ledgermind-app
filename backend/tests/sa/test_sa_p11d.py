"""P11D benefits read (made-up figures): boxes, payrolled benefits left out, another year or person (R-SA102-03, -07)."""

from backend.app.sa.extract import p11d as B


def test_benefits_under_their_boxes_and_payrolled_left_out():
    f = B.clean({"employee": "Sam Staff", "employer": "A Ltd", "tax_year": "2025-26", "benefits": [
        {"kind": "CAR", "description": "Company car", "amount": "4,320.00"},
        {"kind": "MEDICAL", "description": "Health cover", "amount": 640, "payrolled": True},
        {"kind": "weird", "description": "Gym", "amount": 300}]})
    assert [(b["kind"], b["amount"]) for b in f["benefits"]] == [("CAR", 4320.0), ("MEDICAL", 640.0), ("OTHER", 300.0)]
    status, notes = B.checks(f, "2025-26", None, "Sam Staff")
    assert status == "CHECK" and "R-SA102-07" in notes[0] and B.BOXES["CAR"] == "9"


def test_another_year_or_person():
    assert B.checks(B.clean({"tax_year": "2024-25", "benefits": [{"kind": "CAR", "amount": 5}]}), "2025-26")[0] == "OTHER_YEAR"
    g = B.clean({"employee": "Alex Other", "benefits": [{"kind": "CAR", "amount": 5}]})
    assert B.checks(g, "2025-26", None, "Sam Staff")[0] == "CHECK" and g["other_person"]


def test_not_a_p11d_and_a_list_price():
    f = B.clean({"is_p11d": False, "benefits": [{"kind": "CAR", "amount": 68495}]})
    assert B.checks(f, "2025-26")[0] == "FILED" and f["benefits"] == []
    g = B.clean({"employee": "Sam Staff", "benefits": [{"kind": "CAR", "amount": 68495}]})
    assert any("list price" in n for n in B.checks(g, "2025-26", None, "Sam Staff")[1])
