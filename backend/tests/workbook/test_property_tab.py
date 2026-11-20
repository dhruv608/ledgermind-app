"""P1 property tab (industry schedules): cost types and the payer of a receipt."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.workbook.property_tab import OTHER, _cost_type, _payer


def test_cost_types():
    assert _cost_type("The Mortgage Lender") == "Mortgage interest"
    assert _cost_type("Rent guarantee insurance") == "Insurance"
    assert _cost_type("Letting agent fees") == "Agent fees"
    assert _cost_type("Council tax") == "Utilities and council tax"
    assert _cost_type("Stationery") == OTHER


def test_payer_from_bank_text():
    assert "BENSON" in _payer("Benson - Bensons Estate Agents").upper()
