"""Upload: this year's TB titled as the year's movements ('TTB Movement') is shown as a TTB, not a closing TB."""
import io

import openpyxl

from backend.app.api.endpoints.upload import _movement_tb


def _tb(title: str) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([title])
    ws.append(["Test Co"])
    ws.append(["Code", "Account", "Debit", "Credit"])
    ws.append([4800, "Bank", 100, 0])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_movement_column_heading_is_not_a_title():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Trial Balance"])
    ws.append(["Account", "Opening", "Movement", "Closing"])
    out = io.BytesIO()
    wb.save(out)
    found = [{"filename": "TB.xlsx", "role": "TB", "how": "content"}]
    _movement_tb(found, [("TB.xlsx", out.getvalue())])
    assert found[0]["how"] == "content"


def test_ttb_title_shown_as_movements():
    files = [("TB.xlsx", _tb("TTB Movement")), ("Closing.xlsx", _tb("Trial Balance")), ("GL.xlsx", _tb("Movement"))]
    found = [{"filename": "TB.xlsx", "role": "TB", "how": "content"},
             {"filename": "Closing.xlsx", "role": "TB", "how": "content"},
             {"filename": "GL.xlsx", "role": "GL", "how": "content"}]
    _movement_tb(found, files)
    assert [f["how"] for f in found] == ["the year's movements, a TTB", "content", "content"]
