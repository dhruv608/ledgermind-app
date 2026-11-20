"""'Unanalysed - query' on C1-1: last year's TB b/fwd not in the asset register."""

from datetime import date
from types import SimpleNamespace

import openpyxl

from backend.app.services.workbook.checks_tab import find_checks
from backend.app.services.workbook.fixed_assets import ASSET_TOP, _asset_lines


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_a):
        return self

    def all(self):
        return self.rows


def _sheet(assets):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "C1-1-FA detail"
    db = SimpleNamespace(query=lambda _m: _Query(assets))
    _asset_lines(ws, db, SimpleNamespace(id="x"), None)
    return wb, ws


def _label_rows(ws):
    return {ws.cell(row=r, column=2).value: r for r in range(ASSET_TOP, ws.max_row + 1)
            if isinstance(ws.cell(row=r, column=2).value, str)}


def test_no_register_brings_forward_everything_as_unanalysed():
    wb, ws = _sheet([])
    rows = _label_rows(ws)
    label = "Unanalysed - query: cost and depreciation b/fwd with no asset register (must be nil)"
    assert ws.cell(row=rows[label], column=4).value == "=ROUND(D38,2)"
    assert ws.cell(row=rows[label], column=8).value == "=ROUND(H38,2)"
    assert len([c for c in find_checks(wb) if c[2].startswith(label)]) == 2      # cost and depreciation


def test_register_difference_to_the_class_lines():
    asset = SimpleNamespace(category="Computer equipment", description="Laptop", acquisition_date=date(2023, 5, 1),
                            cost_bwd=1200, additions=0, disposals=0, depr_bwd=400, depr_disposals=0,
                            depr_rate_method="25% RBM", depr_charge=200)
    wb, ws = _sheet([asset])
    rows = _label_rows(ws)
    total = rows["Total per register"]
    label = "Unanalysed - query: last year's TB b/fwd not in the register (must be nil)"
    assert ws.cell(row=rows[label], column=4).value == f"=ROUND(D38-D{total},2)"
    assert ws.cell(row=rows[label], column=8).value == f"=ROUND(H38-H{total},2)"
    statuses = [c[3] for c in find_checks(wb) if c[2].startswith(label)]
    assert statuses == ["AMBER", "AMBER"]
