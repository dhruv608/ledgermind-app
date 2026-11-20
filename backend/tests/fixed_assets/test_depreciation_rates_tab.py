"""C1-2 Depreciation rates: the rate, its source and a change from last year flagged."""

from types import SimpleNamespace

import openpyxl
from openpyxl.styles import Font

from backend.app.services.workbook import depreciation_rates
from backend.app.services.workbook.depreciation_rates import TAB, add_rates_tab


def test_rates_tab(monkeypatch):
    monkeypatch.setattr(depreciation_rates, "class_rates", lambda e, p, db: (
        {"Plant and machinery": {"method": "REDUCING_BALANCE", "rate": 20}},
        {"Plant and machinery": "the firm default"},
        {"Plant and machinery": {"method": "STRAIGHT_LINE", "rate": 25}}))
    tb = [SimpleNamespace(std_code=4120, net_amount=5000, opening_amount=4000),
          SimpleNamespace(std_code=4150, net_amount=1200, opening_amount=None)]       # computer equipment, no rate
    wb = openpyxl.Workbook()
    wb.active.title = "C1-1-FA detail"
    add_rates_tab(wb, SimpleNamespace(id="x", profile=None), None, tb, Font(bold=True), after="C1-1-FA detail")
    assert wb.sheetnames == ["C1-1-FA detail", TAB]
    rows = {r[0]: r for r in wb[TAB].iter_rows(min_row=8, values_only=True) if r[0]}
    plant = rows["Plant and machinery"]
    assert plant[1:4] == ("Reducing balance", 0.2, "The firm default")
    assert plant[6] == "25% straight line" and plant[7] == "Changed: needs a note"
    computers = [k for k in rows if k != "Plant and machinery"]
    assert len(computers) == 1 and rows[computers[0]][3].startswith("None: set a rate")


def test_no_tab_without_assets():
    wb = openpyxl.Workbook()
    wb.active.title = "C1-1-FA detail"
    add_rates_tab(wb, SimpleNamespace(id="x", profile=None), None, [], Font(bold=True), after="C1-1-FA detail")
    assert wb.sheetnames == ["C1-1-FA detail"]
