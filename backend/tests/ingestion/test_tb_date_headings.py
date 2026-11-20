"""TaxCalc's comparative TB: codes under 'Account', names under 'Account Description', balances under date headings
(Excel date numbers 45688 / 45322), found with no Debit / Credit columns."""
from backend.app.services.ingestion.column_layouts import guess, missing

ROWS = [["Trial Balance", None, None, None, None, None, None],
        ["Account", "Account Description", 45688, None, 45322, None, "Variance"],
        [1, "Rent received", -57856.11, None, -10019.94, None, 47836.17],
        [2, "Consultancy", -11870.91, None, None, None, 11870.91],
        [3010, "Directors' salaries", None, None, None, None, None],
        [3015, "Directors' fees", None, None, 11000, None, -11000]]


def test_comparative_taxcalc_tb_is_read():
    header, mapping = guess("TB", ROWS)
    assert header == 1
    assert mapping["code"] == 0 and mapping["name"] == 1
    assert mapping["balance"] == 2                 # 31/01/2025, the later of the two dates
    assert missing("TB", mapping) == []


def test_a_plain_tb_is_untouched():
    rows = [["Account", "Debit", "Credit"], ["Sales", None, 100.0], ["Bank", 100.0, None]]
    _h, mapping = guess("TB", rows)
    assert mapping == {"name": 0, "debit": 1, "credit": 2}
