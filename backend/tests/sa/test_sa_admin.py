"""Admin points (made-up figures): coding out under £3,000, leaving Self Assessment, Making Tax Digital thresholds
(R-ADM-01 to 03, P-MTD-01)."""

from backend.app.sa.admin import points


def calc(balance=0.0, employment=0.0, se=0.0, trade_income=0.0, rents=0.0):
    return {"calculation": {"balance": balance, "cgt": 0, "hicbc": 0},
            "income": {"employment": employment, "pensions": 0, "self_employment": se, "property": 0, "foreign": 0},
            "trade": {"businesses": [{"income": trade_income}] if trade_income else []},
            "property": {"properties": [{"rents": rents}] if rents else []}, "foreign_property": {"properties": []}}


def test_coding_out_and_leaving():
    keys = [p["key"] for p in points(calc(balance=1200, employment=30000, se=4000, trade_income=6000), "2025-26")]
    assert keys == ["coding_out"]
    assert [p["key"] for p in points(calc(balance=-50, employment=30000), "2025-26")] == ["leave_sa"]
    assert points(calc(balance=3500, employment=30000, se=9000, trade_income=12000), "2025-26") == []


def test_making_tax_digital():
    keys = [p["key"] for p in points(calc(balance=5000, se=25000, trade_income=32000), "2025-26")]
    assert keys == ["mtd"]                                         # over £30,000 in 2025-26: from April 2027
    keys = [p["key"] for p in points(calc(balance=9000, se=40000, trade_income=45000, rents=12000), "2025-26")]
    assert keys == ["mtd", "mtd_now"]


def test_no_leaving_with_untaxed_documents():
    assert [p["key"] for p in points(calc(balance=-50, employment=30000), "2025-26", {"LETTING_STATEMENT"})] == []
