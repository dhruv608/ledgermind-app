"""Last year's tax written-down value (the pools carried forward, CAA 2001 s59) read from last year's working paper,
and used for deferred tax when no pools are entered (never nil while last year's paper has a value)."""
import json
from types import SimpleNamespace as N

from openpyxl import Workbook

from backend.app.services.ingestion.last_year_adjustments import tax_carried_forward
from backend.app.services.workbook.ct600 import last_year_wdv


def _paper(tab, label, value):
    wb = Workbook()
    wb.active.title = "Notes & Queries"
    ws = wb.create_sheet(tab)
    ws.append(["Client: X"])
    ws.append(["NBV as per Accounts", None, 427426.24])
    ws.append([label, None, value])
    return wb


def test_reads_the_tax_wdv_from_a_deferred_tax_working():
    assert tax_carried_forward(_paper("Deferred Tax", "WDV as per Tax Comp", 294473))["wdv_cf"] == 294473.0
    assert tax_carried_forward(_paper("I1-1-Deferred Tax calc", "WDV of qualifying assets", 1234.5))["wdv_cf"] == 1234.5
    assert "wdv_cf" not in tax_carried_forward(_paper("Deferred Tax", "WDV as per Tax Comp", 0))
    assert "wdv_cf" not in tax_carried_forward(_paper("Debtors", "WDV as per Tax Comp", 5000))   # not a tax tab


def test_last_year_wdv_from_the_stored_paper():
    eng = N(profile=N(tax_inputs=json.dumps({"_last_year_wp": {"wdv_cf": 294473.0}})))
    assert last_year_wdv(eng) == 294473.0
    assert last_year_wdv(N(profile=N(tax_inputs="{}"))) is None
