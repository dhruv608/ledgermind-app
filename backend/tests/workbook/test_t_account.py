"""Control accounts as a T beside the lead."""
from types import SimpleNamespace as NS

from openpyxl import Workbook

from backend.app.services.workbook.balance_tabs.leads import t_account


def test_t_account_sits_beside_the_lead_and_balances_by_formula():
    ws = Workbook().active
    start = t_account(NS(tb_kind="closing"), ws, [5320], 8, 4, nl="G7.1 - NL Analysis")
    assert start == 6
    assert [ws.cell(row=7, column=c).value for c in (6, 7, 8)] == ["T-account", "Debit £", "Credit £"]
    labels = [ws.cell(row=r, column=6).value for r in range(8, 16)]
    assert labels[:5] == ["Balance b/fwd", "Opening adjustment", "Movement per GL (G7.1)", "TB not in the ledger",
                          "Adjusting journals (B2)"]
    assert labels[5:7] == ["Balance c/fwd", "Total"]
    assert "'G7.1 - NL Analysis'!$H:$H" in ws["G10"].value and "'G7.1 - NL Analysis'!$I:$I" in ws["H10"].value
    assert ws["H13"].value == "=MAX(0,SUM(G8:G12)-SUM(H8:H12))"        # a debit balance carried on the credit side
    assert ws["F15"].value.startswith("Check: T-account c/fwd")


def test_t_account_moves_right_when_the_place_is_taken():
    ws = Workbook().active
    ws["F9"] = "something"
    assert t_account(NS(tb_kind=""), ws, [1100], 8, 4) == 10


def test_checks_tab_reads_the_lead_check_and_the_t_check_apart():
    from backend.app.services.workbook.checks_tab import find_checks
    wb = Workbook()
    ws = wb.active
    ws.title = "G7-PAYE liabilities"
    ws["B13"], ws["E13"] = "Check: books v TB (must be nil)", "=ROUND(E11-E12,2)"
    t_account(NS(tb_kind="closing"), ws, [5320], 8, 5, nl="G7.1 - NL Analysis")      # T at G:I, rows 7-15
    got = {(cell, label[:16]) for _t, cell, label, _k in find_checks(wb)}
    assert got == {("E13", "Check: books v T"), ("I15", "Check: T-account")}


def test_tab_chip_counts_the_lead_check_and_the_t_check_only():
    from backend.app.services.workbook.look.figures import check_refs
    ws = Workbook().active
    ws["B13"], ws["E13"] = "Check: books v TB (must be nil)", "=ROUND(E11-E12,2)"
    t_account(NS(tb_kind="closing"), ws, [5320], 8, 5, nl="G7.1 - NL Analysis")
    assert check_refs(ws) == ["E13", "I15"]
