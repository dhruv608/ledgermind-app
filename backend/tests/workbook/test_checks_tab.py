"""A0 - Checks: labelled check rows listed red or amber, the cover's draft line by formula."""
import openpyxl

from backend.app.services.workbook.checks_tab import SHEET, add_checks_tab, find_checks


def _wb():
    wb = openpyxl.Workbook()
    wb.active.title = "A"
    g4 = wb.create_sheet("G4 - Loans & HP")
    g4["B13"], g4["E13"] = "Check: total c/fwd less the books (must be nil)", "=E10-E11"
    e2 = wb.create_sheet("E2-Trade Debtors")
    e2["B29"], e2["C29"] = "Unexplained difference (must be nil)", "=C20-SUM(C24:C28)"
    e2["B12"], e2["D12"] = "TB per software (check)", "=SUM(X:X)"          # a balance line, not a check
    return wb


def test_checks_found_and_classed():
    got = {(t, c, k) for t, c, _, k in find_checks(_wb())}
    assert got == {("G4 - Loans & HP", "E13", "RED"), ("E2-Trade Debtors", "C29", "AMBER")}


def test_tab_and_cover_formula():
    wb = _wb()
    assert add_checks_tab(wb, "2 journals not yet approved") == 2
    ws = wb[SHEET]
    assert wb.sheetnames[1] == SHEET and ws["D6"].value.startswith("=IF(ISNUMBER(") and \
        "ROUND(" in ws["D6"].value and '"not entered"' in ws["E6"].value and "RED" in ws["E6"].value + ws["E7"].value
    b9 = wb["A"]["B9"].value
    assert b9.startswith("=IF('A0 - Checks'!B3>0") and "2 journals not yet approved" in b9
    b10 = wb["A"]["B10"].value                     # the amber ones named on the cover, not a draft
    assert b10.startswith("=IF('A0 - Checks'!B4>0") and "amber check(s)" in b10 and "DRAFT" not in b10


def test_every_check_on_an_etb_row_and_k_tab_label_in_f():
    wb = openpyxl.Workbook()
    wb.active.title = "A"
    etb = wb.create_sheet("B1-ETB")
    for col, head in (("F", "Opening"), ("H", "Movement per GL"), ("L", "Final Trial Balance")):
        etb[f"{col}6"] = head
    etb["B34"] = "Check (must be 0)"
    etb["F34"], etb["H34"], etb["L34"] = "=F33-G33", "=H33-I33", "=L33-M33"
    k = wb.create_sheet("K1")
    k["F20"], k["H20"] = "Difference: ledger v TB (must be nil)", "=H18-H19"
    got = {(t, c): label for t, c, label, _ in find_checks(wb)}
    assert set(got) == {("B1-ETB", "F34"), ("B1-ETB", "H34"), ("B1-ETB", "L34"), ("K1", "H20")}
    assert got[("B1-ETB", "L34")].endswith("Final Trial Balance")


def test_sub_ledger_differences_are_amber():
    wb = openpyxl.Workbook()
    wb.active.title = "A"
    f3 = wb.create_sheet("F3.1 - Barclays")
    f3["B20"], f3["D20"] = "Difference: books less statement (must be nil)", '=IF(D17="","x",ROUND(D12-D17,2))'
    g9 = wb.create_sheet("G9 - VAT")
    g9["B40"], g9["D40"] = "Unidentified difference: ledger v VAT returns (must be nil)", "=ROUND(D38-D36,2)"
    assert {k for *_x, k in find_checks(wb)} == {"AMBER"}


def test_etb_opening_on_another_code_is_amber():
    from openpyxl import Workbook
    from backend.app.services.workbook.core_tabs import OPENING_CHECK
    wb = Workbook()
    ws = wb.active
    ws.title = "B1-ETB"
    ws["B60"], ws["Y60"] = OPENING_CHECK, "=ROUND(SUMPRODUCT(ABS(O8:O50-P8:P50)),2)"
    assert [(c, k) for _t, c, _l, k in find_checks(wb)] == [("Y60", "AMBER")]
