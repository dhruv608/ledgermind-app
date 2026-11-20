"""Last year's final working paper's ETB read, and C13 (last year's TB v that paper) on the Data check."""
import io
import os
from types import SimpleNamespace as N

import openpyxl

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.ingestion.last_year_adjustments import etb_final
from backend.app.services.setup.extraction_checks import tb_v_final_wp


def _paper():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "B1-ETB"
    ws.append(["Example Ltd"])
    ws.append(["Year Ended 31 March 2025"])
    ws.append([])
    ws.append(["Exrended Trial Balance"])
    ws.append([])
    ws.append([" NC", "Nominal Name", None, None, None, "Opening Trial Balance", None, "QB TTB", None, "Journals", None,
               "Final Trial Balance", None, "Final balance"])
    ws.append([None] * 5 + ["Debit", "Credit"] * 4)
    for code, name, final in [(0, "Sales", -5000.0), (3000, "Wages", 2000.0), (4120, "P&M cost", 800.0),
                              (4121, "P&M additions", 200.0), (4123, "P&M dep b/f", -100.0), (4124, "P&M charge", -50.0),
                              (4800, "Bank", 1650.0), (5400, "DLA", -500.0), (8000, "Reserves", 1000.0)]:
        ws.append([code, name] + [None] * 11 + [final])
    buf = io.BytesIO()
    wb.save(buf)
    return openpyxl.load_workbook(io.BytesIO(buf.getvalue()), read_only=True, data_only=True)


class _Chart:
    def is_pl(self, code):
        return code < 4000


def test_etb_final_read():
    year_end, final = etb_final(_paper())
    assert year_end.isoformat() == "2025-03-31"
    assert final["4800"] == 1650.0 and final["0"] == -5000.0 and abs(sum(final.values())) < 0.01


def test_c13_groups_fixed_assets_and_flags_real_differences():
    _y, final = etb_final(_paper())
    # Last year's TB: additions in cost, the charge in depreciation b/f (the same class totals); the DLA differs
    lines = [N(code=4120, amount=1000.0), N(code=4123, amount=-150.0), N(code=4800, amount=1650.0),
             N(code=5400, amount=-21500.0), N(code=8000, amount=19000.0)]
    assert tb_v_final_wp(lines, final, _Chart()) == [("5400", -21500.0, -500.0)]


def test_c13_reclass_not_flagged():
    final = {"4811": 1000.0, "4814": 0.0}
    lines = [N(code=4811, amount=0.0), N(code=4814, amount=1000.0)]
    assert tb_v_final_wp(lines, final, _Chart()) == []
