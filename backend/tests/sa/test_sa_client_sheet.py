"""The client's own income and expenses sheet (the firm's template, made-up rows): rows in the period, headings,
commuting and study disallowed pending a decision (R-SA103-12; BIM37605)."""

import io

from openpyxl import Workbook

from backend.app.sa.extract import client_sheet as C
from backend.app.sa.extract.classify import classify


def sheet():
    wb = Workbook()
    ws = wb.active
    ws.append(["Profit and Loss"])
    ws.append(["Date of Income/Expense", "Income/Expense", "Detail of income / Expense", "Client / Supplier",
               "Total Income", "Total Expense", "Mileage"])
    ws.append(["2025-05-10", "Income", "Invoice paid", "A Client", 1200, None, 40])
    ws.append(["2024-12-01", "Income", "Invoice paid", "A Client", 500, None, None])      # before the period
    ws.append(["2025-06-01", "Expense", "Train to client", "Trainline", None, 35.5, None])
    ws.append(["2025-07-01", "Expense", "Commute to work", "Fuel", None, 60, None])
    ws.append(["2025-08-01", "Expense", "Hotel for MSc study", "EasyHotel", None, 90, None])
    ws.append(["Total", None, None, None, 1700, 185.5, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_rows_in_the_period_under_headings():
    out = C.lines(C.read(sheet())["rows"], "2025-04-06", "2026-04-05")
    got = [(i["heading"], i["amount"], i["disallowed"]) for i in out["items"]]
    assert got == [("TURNOVER", 1200.0, 0.0), ("TRAVEL", 35.5, 0.0), ("TRAVEL", 60.0, 60.0), ("TRAVEL", 90.0, 90.0)]
    assert out["outside"] == 1 and [d[0] for d in out["decisions"]] == ["commuting", "study"] and out["miles"] == 40


def test_sorted_as_client_accounts():
    text = "[Sheet] Date of Income/Expense | Income/Expense | Total Income | Total Expense"
    assert classify(text, "Profit and Loss (Client).xlsx") == "CLIENT_ACCOUNTS"
    assert classify(text, "Working papers 2025-26.xlsx") == "WORKING_PAPER"


def test_two_versions_of_the_sheet_count_once():
    rows = C.read(sheet())["rows"]
    taken, kept = set(), []
    for version in (rows, rows):                  # the same rows sent twice, as income.sync_client_sheets sees them
        for r in version:
            key = (r.get("on"), r.get("income"), r.get("expense"), (r.get("detail") or "").lower())
            if key not in taken:
                taken.add(key)
                kept.append(r)
    assert len(kept) == len(rows)


def test_an_income_row_with_no_figure_and_a_note_column_is_kept():
    # Made-up names: 'Date of Income / Expense' is the date column; the note sits in a column with no heading
    import io
    import openpyxl
    from backend.app.sa.extract import client_sheet
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, "Date of Income / Expense", "Income / Expenditure", "Detail of Income / Expenditure", "Client / Supplier",
               "Total Income", "Total Expense", "Hours", None, None])
    ws.append([None, None, "Income", None, None, None, None, None, None, "invoice split with my sister, A Test"])
    ws.append([None, "2025-11-05", "Expenditure", "Software licence", "A Supplier", None, 22.99])
    buf = io.BytesIO()
    wb.save(buf)
    rows = client_sheet.read(buf.getvalue())["rows"]
    assert rows[0]["no_amount"] and "split with my sister" in rows[0]["detail"]
    assert rows[1]["expense"] == 22.99 and rows[1]["detail"] == "Software licence"
