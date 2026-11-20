"""Last year's WP in the firm's older templates: the ETB on an 'ETB' or 'Trial Balance' tab
with a group row 'Opening Balance | TTB | Journals | Final | P&L', the final as one signed 'Balance' column, codes per
director ('5400/1'), a 'Codes' heading, and the year end written many ways."""
import io
from datetime import date

import openpyxl

from backend.app.services.ingestion.last_year_adjustments import _year_end, etb_final


def _paper(tab="ETB", code_head="Code", group_final="Final", year_cell=("Year end:", "31.12.2023")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = tab
    ws["A1"], ws["B1"] = "Client", "Test Co"
    ws["A2"], ws["B2"] = year_cell
    ws["A4"] = "Extended Trial Balance"
    for col, text in ((3, "Opening Balance"), (5, "TTB"), (7, "Journals"), (9, group_final), (10, "P&L"),
                      (12, "Balance sheet")):
        ws.cell(row=5, column=col + 1, value=text)
    for col, text in enumerate([code_head, "Accounts Name", None, "Dr", "Cr", "Dr", "Cr", "Dr", "Cr", "Balance"], 1):
        if text:
            ws.cell(row=6, column=col, value=text)
    for r, (code, name, final) in enumerate([(0, "Sales", -1000.0), (3000, "Wages", 600.0), ("5400/1", "Mr A", -150.0),
                                            ("5400/2", "Mrs B", -50.0), (4800, "Bank", 600.0)], 7):
        ws.cell(row=r, column=1, value=code)
        ws.cell(row=r, column=2, value=name)
        ws.cell(row=r, column=10, value=final)
    out = io.BytesIO()
    wb.save(out)
    return openpyxl.load_workbook(io.BytesIO(out.getvalue()), data_only=True)


def test_older_etb_final_balance_column():
    end, finals = etb_final(_paper())
    assert end == date(2023, 12, 31)
    assert finals == {"0": -1000.0, "3000": 600.0, "5400": -200.0, "4800": 600.0}


def test_trial_balance_tab_codes_heading_and_balance_group():
    end, finals = etb_final(_paper(tab="Trail Balance", code_head="Codes", group_final="Balance",
                                   year_cell=("Period : 20.06.2024 to 30.11.2025", None)))
    assert end == date(2025, 11, 30) and finals["5400"] == -200.0


def test_an_etb_that_does_not_balance_is_not_used():
    wb = _paper()
    wb["ETB"]["J8"] = 700.0           # wages 700: the finals do not add up to nil
    assert etb_final(wb) is None


def test_year_end_forms():
    assert _year_end([["Client"], ["Year End- 31 March 2026"]]) == date(2026, 3, 31)
    assert _year_end([["Client:", "X"], ["Year end:", "02 Oct 2024 to 31 Oct 2025"]]) == date(2025, 10, 31)
    assert _year_end([["Client : X"], ["Y.E. : 30.06.2026"]]) == date(2026, 6, 30)
    assert _year_end([["X Ltd"], ["31.03.2025"]]) == date(2025, 3, 31)
    assert _year_end([["Yellow paper"], ["no date here"]]) is None


def test_register_tab_year_end_forms():
    """The older paper's FAR tab: 'Y.E : 30.11.2025' or a date cell then a link on row 2 (its NBV columns say only
    '2025 | 2024'), so last year's register is known as last year's and rolled forward."""
    assert _year_end([["Client : X"], ["Y.E : 30.11.2025"], [], ["", "", "", "Trial Balance"]]) == date(2025, 11, 30)
    assert _year_end([["C&A studies"], ["2026-02-28 00:00:00", "", "Trial Balance"]]) == date(2026, 2, 28)
