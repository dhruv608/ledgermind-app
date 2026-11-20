"""The client's own income and expenses sheet in their own layout (made-up rows): the business's rows only, use of home
and mileage left to the accountant (R-SA103-12, -13), the firm's own workings never read as one."""

from backend.app.sa.extract import client_sheet, own_sheet
from backend.app.sa.extract.classify import classify


def test_only_the_business_rows():
    f = own_sheet.clean({"is_business_sheet": True, "rows": [
        {"date": "2025-10-03", "detail": "Evaluation fee", "party": "A Charity", "kind": "INCOME", "amount": "7,175.00"},
        {"date": "2025-04-30", "detail": "Interest", "kind": "NOT_BUSINESS", "amount": 0.57},
        {"date": "2025-05-01", "detail": "Pension", "kind": "NOT_BUSINESS", "amount": 188.76},
        {"date": None, "detail": "Phone (40% use)", "kind": "EXPENSE", "amount": 62.88},
        {"date": None, "detail": "Heating, flat rate", "kind": "EXPENSE", "amount": 312, "use_of_home": True},
        {"date": None, "detail": "Car 247 miles", "kind": "EXPENSE", "amount": 111.15, "miles": 247, "mileage": True}]})
    assert f["is_business_sheet"] and len(f["rows"]) == 4
    out = client_sheet.lines(f["rows"], "2025-04-06", "2026-04-05")
    assert sum(i["amount"] for i in out["items"] if i["heading"] == "TURNOVER") == 7175.0
    assert sum(i["disallowed"] for i in out["items"]) == 423.15          # use of home and mileage wait for a decision
    assert {w for w, _, _ in out["decisions"]} == {"use of home", "mileage"}


def test_no_business_rows_is_not_a_business_sheet():
    assert not own_sheet.clean({"is_business_sheet": True, "rows": [{"kind": "NOT_BUSINESS", "amount": 10}]})["is_business_sheet"]


def test_which_sheets_are_read_this_way():
    sheet = "[Income FY2025-26] Date Type Description Debit/Credit [Expenses FY2025-26] Date Item Amount"
    assert classify(sheet, "Client FY2025-2026.xlsx") == "CLIENT_ACCOUNTS"
    assert classify(sheet, "Our working/2024-25.xlsx") != "CLIENT_ACCOUNTS"          # the firm's own workings
    assert classify(sheet + " rent received from the letting agent", "House.xlsx") == "LETTING_STATEMENT"


def test_sheet_decisions_are_listed_once():
    from backend.app.sa.extract import client_sheet
    rows = [{"on": "2025-06-01", "detail": "Mileage to site", "party": "", "income": 0.0, "expense": 0.0, "miles": 120.0},
            {"on": None, "detail": "Heating, flat rate", "party": "", "income": 0.0, "expense": 312.0, "miles": 0.0, "decide": "use of home"}]
    out = client_sheet.lines(rows, "2025-04-06", "2026-04-05")
    assert out["miles"] == 120.0 and [w for w, _, _ in out["decisions"]] == ["use of home"]
