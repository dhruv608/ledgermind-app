"""B1-ETB's opening and last year linked to PY-TB by formula, only where PY-TB gives the very figures
the ETB shows."""

from types import SimpleNamespace as L

from openpyxl import Workbook

from backend.app.services.workbook.opening_tabs import link_etb

LINES = [L(code=4400, name="Debtors", amount=1000.0), L(code=0, name="Sales", amount=-5000.0),
         L(code=8000, name="Reserves", amount=4000.0)]
OPENS = {4400: 4400, 0: 8000, 8000: 8000}


def _books(opening_8000=-1000.0):
    wb = Workbook()
    etb = wb.active
    etb.title = "B1-ETB"
    etb["F6"], etb["T6"] = "Opening (last year's filed TB)", "Last year (B1-ETB final)"
    for r, (code, opening, ly) in enumerate(((0, 0.0, -5000.0), (4400, 1000.0, 1000.0), (8000, opening_8000, 4000.0)), 8):
        etb.cell(row=r, column=1, value=code)
        etb.cell(row=r, column=6, value=opening if opening > 0 else None)
        etb.cell(row=r, column=7, value=-opening if opening < 0 else None)
        etb.cell(row=r, column=20, value=ly)
    py = wb.create_sheet("PY-TB - Last year's TB")
    for r, line in enumerate(LINES, 7):
        py.cell(row=r, column=1, value=line.code)
        py.cell(row=r, column=7, value=OPENS[line.code])
    return wb, etb, py


def test_links_when_the_figures_agree():
    wb, etb, py = _books()
    assert link_etb(wb, py, LINES) == 2
    ref = "'PY-TB - Last year''s TB'"
    assert etb["F9"].value == f"=MAX(0,ROUND(SUMIFS({ref}!$E:$E,{ref}!$G:$G,$A9),2))"
    assert etb["G10"].value == f"=MAX(0,-ROUND(SUMIFS({ref}!$E:$E,{ref}!$G:$G,$A10),2))"
    assert etb["T8"].value == f"=ROUND(SUMIFS({ref}!$E:$E,{ref}!$A:$A,$A8),2)"


def test_keeps_the_values_when_they_differ():
    wb, etb, py = _books(opening_8000=-900.0)          # the ETB's opening came from somewhere else
    assert link_etb(wb, py, LINES) == 1                # last year still links, the opening does not
    assert etb["G10"].value == 900.0 and str(etb["T10"].value).startswith("=ROUND(SUMIFS(")
