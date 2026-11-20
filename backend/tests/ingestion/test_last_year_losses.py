"""Last year's H1 losses carried forward read from last year's final working paper (H1). Made-up WP."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import openpyxl

from backend.app.services.ingestion.last_year_adjustments import tax_carried_forward


def _wb(rows, title="H1-Taxation"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    return wb


def test_losses_carried_forward_found():
    wb = _wb([["Profit for current year", -12000], ["Less: Losses b/fwd", -20594], ["Losses C/fwd", -82857]])
    assert tax_carried_forward(wb) == {"losses_cf": 82857.0}


def test_total_losses_first_figure():
    wb = _wb([["Total Losses c/f", -2653, -2483, -170]])
    assert tax_carried_forward(wb) == {"losses_cf": 2653.0}


def test_brought_forward_alone_is_not_carried_forward():
    wb = _wb([["Less: Losses b/fwd", -13812], ["Taxable profit", 5000]])
    assert tax_carried_forward(wb) == {}


def test_no_h1_tab():
    assert tax_carried_forward(_wb([["Losses c/f", -100]], title="K1")) == {}
