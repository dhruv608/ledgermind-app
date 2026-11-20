"""H1.2 capital allowances: one row per pool from the computation, a check tied to H1."""
from types import SimpleNamespace as NS

import openpyxl

from backend.app.services.workbook.ca_tab import CA_TAB, ca_tab


def _ctx():
    wb = openpyxl.Workbook()
    wb.active.title = "H"
    h1 = wb.create_sheet("H1-Taxation")
    h1["B20"] = "Less: capital allowances"
    h1["D20"] = -18352.39
    return NS(wb=wb)


POOLS = [{"pool": "Annual investment allowance / first-year allowance", "bf": 0.0, "additions": 18011.3,
          "aia_fya": 18011.3, "disposals": 0.0, "balancing_charge": 0.0, "balancing_allowance": 0.0, "wda": 0.0,
          "cf": 0.0, "note": ""},
         {"pool": "Special rate pool", "bf": 0.0, "additions": 5684.79, "aia_fya": 0.0, "disposals": 0.0,
          "balancing_charge": 0.0, "balancing_allowance": 0.0, "wda": 341.09, "cf": 5343.7, "note": "WDA 6.00%"}]


def test_pools_and_check_against_h1():
    ctx = _ctx()
    ca_tab(ctx, NS(pools=POOLS), "H1-Taxation")
    ws = ctx.wb[CA_TAB]
    assert ctx.wb.sheetnames == ["H", "H1-Taxation", CA_TAB]
    assert ws["A7"].value.startswith("Annual investment") and ws["D7"].value == 18011.3 and ws["H8"].value == 341.09
    assert ws["I11"].value == "=ROUND(D9+H9+'H1-Taxation'!D20,2)"


def test_no_pools_no_tab():
    ctx = _ctx()
    ca_tab(ctx, NS(pools=[]), "H1-Taxation")
    assert CA_TAB not in ctx.wb.sheetnames
