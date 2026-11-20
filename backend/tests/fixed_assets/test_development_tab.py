"""D1-P development costs: cost types and the flags' word lists."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.workbook.development_tab import OTHER, PERSON, PERSONAL, _type


def test_cost_types_as_his_example():
    assert _type("Your Structural Engineer - design") == "Professional (architect, planning)"
    assert _type("Build Yard Builders Merchants") == "Materials and tool hire"
    assert _type("Fluid Funding - Commercial arrangement fee") == "Finance and arrangement fees"
    assert _type("R Home Improvements Ltd") == "Contractors"
    assert _type("Simply Business site insurance") == "Site insurance"
    assert _type("Stamp duty land tax") == "SDLT and legal"
    assert _type("Wickes - WICKES 123") == "Materials and tool hire"
    assert _type("Postage") == OTHER


def test_flags():
    assert PERSONAL.search("Regency Hampers - Regency")
    assert PERSON.match("Andrei Stancu")
    assert not PERSON.match("BUILD YARD")
