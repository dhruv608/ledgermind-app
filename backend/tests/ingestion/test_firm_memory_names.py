"""The firm's coding memory: the client's own account names from a working paper's TTB tab, and names that differ
only by a bank number count as one."""
from openpyxl import Workbook

from backend.app.services.mapping.firm_examples import from_working_papers, name_key


def test_bank_numbers_do_not_split_a_name():
    assert name_key("Bank Account (6212)") == name_key("Bank Account (8793)") == "bank account"
    assert name_key("4800 - Barclays 20345678") == name_key("Barclays")
    assert name_key("Bank & Cash") == name_key("bank and cash") and name_key("Debtors") == name_key("Debtor")


def test_reads_the_clients_own_names_from_the_ttb_tab(tmp_path):
    wb = Workbook()
    wb.active.title = "ETB"
    wb.active.append(["Code", "Accounts Name"])
    wb.active.append([3000, "Wages and salaries"])                 # the chart's name: not what the client calls it
    ws = wb.create_sheet("TTB")
    ws.append(["Client: X"])
    ws.append(["TC Code", "Name", "Debit", "Credit"])
    for code, name in ((4800, "Bank Account (6212)"), (3000, "Payroll - gross"), (5200, "Accounts payable"),
                       (4420, "Undeposited Funds"), (3290, "Phone & broadband"), (0, "Sales")):
        ws.append([code, name, 1, None])
    path = tmp_path / "wp.xlsx"
    wb.save(path)
    got = dict((n, c) for n, c in from_working_papers(str(path)))
    assert got["Undeposited Funds"] == 4420 and got["Payroll - gross"] == 3000 and "Wages and salaries" not in got
