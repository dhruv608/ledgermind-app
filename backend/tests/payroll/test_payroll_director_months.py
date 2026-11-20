"""Directors' pay month by month from the payroll file: directors' and staff pay apart per month,
split only by the payroll, not the gross only."""
from datetime import date

from backend.app.services.ingestion.payroll_directors import read


def test_director_column_by_month():
    rows = [["Client Ltd"], ["Payroll Summary"],
            ["Account", "Months", "Director wages", "Employee wages", "Tax", "EE Ni", "ER Ni", "Net wages"],
            ["30/04/2024", "", "1000", "10582.44", "912.2", "511.23", "1041.95", "9854.64"],
            ["31/05/2024", "", "1000", "10673.96", "930.6", "518.56", "1054.58", "9855.03"],
            ["30/06/2024", "", "0", "10827.85", "932.6", "530.86", "1075.83", "9979.46"],
            ["", "", "2000", "32084.25"]]
    found = read(rows)
    assert found.gross == 2000 and found.how == "director column"
    assert found.months == {date(2024, 4, 30): 1000.0, date(2024, 5, 31): 1000.0}


def test_director_blocks_by_month():
    rows = [["Director - Jane Smith"], ["Month", "Gross", "ER NI"],
            ["Apr-24", "800", "0"], ["May-24", "900", "0"], ["Total", "1700", "0"]]
    found = read(rows)
    assert found.gross == 1700 and found.months == {date(2024, 4, 30): 800.0, date(2024, 5, 31): 900.0}


def test_total_line_keeps_months_only_when_they_agree():
    rows = [["Director Salary", "5000"],
            ["Director - Jane Smith"], ["Month", "Gross"], ["Apr-24", "800"], ["Total", "800"]]
    found = read(rows)
    assert found.gross == 5000 and found.months == {}       # 800 by month is not the 5,000 the file gives
