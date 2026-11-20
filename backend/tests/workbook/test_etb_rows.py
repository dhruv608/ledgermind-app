"""ETB: one blank row between the P&L and the balance sheet codes, and every reader steps over it."""
import openpyxl

from backend.app.services.workbook.etb_rows import code_rows, data_rows


def test_one_gap_after_pl():
    assert code_rows([0, 3000, 3800, 4120, 4800, 8000]) == [8, 9, 10, 12, 13, 14]
    assert code_rows([4800, 8000]) == [8, 9]          # no P&L: no gap
    assert code_rows([0, 3000]) == [8, 9]             # no balance sheet: no gap
    assert code_rows([]) == []


def test_readers_step_over_the_gap_and_stop_at_the_total():
    ws = openpyxl.Workbook().active
    codes = [0, 3000, 4800, 8000]
    for r, c in zip(code_rows(codes), codes):
        ws.cell(row=r, column=1, value=c)
    last = code_rows(codes)[-1]
    ws.cell(row=last + 2, column=2, value="TOTAL")      # the total row: column A empty
    assert data_rows(ws) == [8, 9, 11, 12]
