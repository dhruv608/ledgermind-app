"""The QA gate reads quoted tab names with an apostrophe ('Directors'' salaries'), Excel's own quoting, and still
finds a formula pointing at a tab that does not exist."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import openpyxl

from backend.app.services.workbook.qa import run_pre_release_qa_check


def test_apostrophe_in_a_tab_name_is_not_a_missing_sheet():
    wb = openpyxl.Workbook()
    wb.active.title = "A"
    wb.create_sheet("K7 - Directors' salaries")
    wb["A"]["A1"] = "=SUM('K7 - Directors'' salaries'!H8:H9)"
    wb["A"]["A2"] = "='Missing tab'!A1"
    missing = [i for i in run_pre_release_qa_check(wb, []) if "missing sheet" in i]
    assert missing == ["1 broken formula(s) in A: missing sheet 'Missing tab'"]
