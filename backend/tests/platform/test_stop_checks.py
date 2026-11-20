"""Stop rules as labelled checks: reserves b/f to PY-TB and the CT control to the ETB are
red; balances on the wrong side and the tax charge v the computation are amber."""
from openpyxl import Workbook

from backend.app.services.workbook.checks_tab import find_checks
from backend.app.services.workbook.stop_checks import add_stop_checks


def test_checks_and_their_colour():
    wb = Workbook()
    wb.active.title = "B1-ETB"
    py = wb.create_sheet("PY-TB - Last year's TB")
    py["G6"] = "Opens on (B1-ETB)"
    wb.create_sheet("J2 - Reserves")["B8"] = "Profit & (Loss) brought forward"
    h1 = wb.create_sheet("H1-Taxation")
    h1["B14"], h1["D14"] = "Balance C/Fwd.", "=E16-SUM(D7:D13)"
    h1["B40"] = "Difference: accounts less computation"
    h1["G40"] = "=G38-G30"
    for t in ("E1 (LEAD)", "G1 (LEAD)", "F1 (LEAD)"):
        wb.create_sheet(t)["B6"] = "lead"
    add_stop_checks(wb)
    found = {(t, kind) for t, _c, label, kind in find_checks(wb)}
    assert ("J2 - Reserves", "RED") in found and ("H1-Taxation", "RED") in found
    assert ("H1-Taxation", "AMBER") in found
    assert {("E1 (LEAD)", "AMBER"), ("G1 (LEAD)", "AMBER"), ("F1 (LEAD)", "AMBER")} <= found
    assert h1["D17"].value.startswith("=ROUND(D14+SUMIF(")
