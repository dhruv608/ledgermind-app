"""VAT returns for a VAT-registered sole trader (made-up figures): the boxes read, a company's return kept out, the part
of a quarter inside the year, a missing start date taken as a quarter (R-SA103-16)."""

from backend.app.sa.extract import vat_return as V
from backend.app.sa.extract.classify import classify


def test_boxes_and_a_company_return():
    f = V.clean({"trader": "Pat's Stamps", "period_from": "2025-06-01", "period_to": "2025-08-31", "scheme": "margin",
                 "box1": "1,767.15", "box4": 2012.44, "box6": 50316.82})
    status, notes = V.checks(f, "2025-26", "Pat Test")
    assert status == "CHECK" and f["box1"] == 1767.15 and "margin scheme" in notes[0]
    co = V.clean({"trader": "Test Sleep Ltd", "period_from": "2024-09-01", "period_to": "2024-11-30", "box1": 47839.73})
    assert V.checks(co, "2024-25", "Pat Test")[0] == "CHECK" and co["other_person"]


def test_part_of_a_quarter_and_an_assumed_start():
    q = {"period_from": "2026-03-01", "period_to": "2026-05-31"}
    assert round(V.overlap(q, "2025-04-06", "2026-04-05"), 3) == round(36 / 92, 3)
    f = V.clean({"period_to": "2026-03-31", "box1": 2038.43, "box6": 47858.92})
    status, notes = V.checks(f, "2025-26", "Pat Test")
    assert f["period_from"] == "2026-01-01" and "quarter is assumed" in notes[0]


def test_a_vat_working_is_not_the_working_paper():
    text = "Box 1 841.52 Sales in period Box 2 0 Box 3 841.52 Box 4 1943.07 Box 5 -1101.54 Box 6 40496.78 Box 7 9715.33"
    assert classify(text, "VAT PE Nov 2025 - TAA workings.xlsx") == "VAT_RETURN"
    assert classify("", "Client VAT Return Q1.pdf") == "VAT_RETURN"
