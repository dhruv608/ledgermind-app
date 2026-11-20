"""GL tab -> TTB by client account: each ledger line names its TB account; the TTB sums the
ledger per account by formula beside the client's TB, with the difference as a red check."""

from types import SimpleNamespace

from openpyxl import Workbook

from backend.app.services.workbook.checks_tab import find_checks
from backend.app.services.workbook.ledger_chain import add_ledger_chain, tb_account_matcher
from backend.app.services.workbook.context import GL_TAB

ACCOUNTS = [("4800", "4800 - Bank Account"), ("0", "0 - Sales"), ("0", "0 - Empire"),
            ("1440", "1440 - Empire"), ("1440", "1440 - Sub-Contractors")]


def test_matcher_prefix_parent_and_shared_names():
    match = tb_account_matcher(ACCOUNTS)
    assert match("Bank Account", "4800") == "4800 - Bank Account"           # the TB's '4800 - ' prefix
    assert match("Sales:Empire", "0") == "0 - Empire"                        # a name on two codes: the line's code
    assert match("Sub-Contractors:Empire", "1440") == "1440 - Empire"
    assert match("Sales:Zenith", "0") == "0 - Sales"                         # a sub-account with no TB account
    assert match("Rent", "3100") is None


def _ctx(kind):
    wb = Workbook()
    wb.active.title = "TTB"
    gl = wb.create_sheet(GL_TAB)
    for c, h in enumerate(["Account Code", "Account Name", "Date", "Source", "Description", "Reference", "Debit",
                           "Credit", "Net Amount", "Account type"], 1):
        gl.cell(row=6, column=c, value=h)
    rows = [("01/05/2025", "4800", "", "Bank Account", "", "", "", 500.0, 0.0),
            ("01/05/2025", "0", "", "Sales", "", "", "", 0.0, 500.0)]
    for r, tx in enumerate(rows, 7):
        gl.cell(row=r, column=1, value=int(tx[1]))
        gl.cell(row=r, column=2, value=tx[3])
        gl.cell(row=r, column=7, value=tx[7] or None)
        gl.cell(row=r, column=8, value=tx[8] or None)
        gl.cell(row=r, column=9, value=f"=+(G{r}-H{r})")
    accounts = [("4800", "4800 - Bank Account", 1500.0, 0.0), ("0", "0 - Sales", 0.0, 500.0)]
    return SimpleNamespace(wb=wb, tb_kind=kind, tx_rows=rows, tb_account_list=accounts,
                           account_name=lambda c: {4800: "Bank current account", 0: "Sales"}[c])


def test_movement_tb_compares_every_account():
    ctx = _ctx("movement")
    add_ledger_chain(ctx)
    gl, ttb = ctx.wb[GL_TAB], ctx.wb["TTB"]
    assert gl["K6"].value == "TB account" and gl["K7"].value == "4800 - Bank Account" and gl["K8"].value == "0 - Sales"
    assert ttb["I7"].value == "Bank current account"
    assert ttb["J7"].value.startswith(f"=SUMIFS('{GL_TAB}'!$I$7:$I$8,'{GL_TAB}'!$K$7:$K$8,$B7")
    assert ttb["K7"].value == "=ROUND(H7-J7,2)" and ttb["K8"].value == "=ROUND(H8-J8,2)"
    assert ttb["K11"].value == "=ROUND(SUMPRODUCT(ABS(K7:K8)),2)"
    assert [(t, c, kind) for t, c, _l, kind in find_checks(ctx.wb)] == [("TTB", "K11", "RED")]


def test_closing_tb_compares_the_pl_only():
    ctx = _ctx("closing")
    add_ledger_chain(ctx)
    ttb = ctx.wb["TTB"]
    assert ttb["K7"].value is None                       # the bank's TB holds its opening: checked on B1-ETB
    assert ttb["K8"].value == "=ROUND(H8-J8,2)"
    assert ttb["K6"].value == "P&L: TB less GL (must be nil)"


def test_no_ledger_no_columns():
    ctx = _ctx("")
    add_ledger_chain(ctx)
    assert ctx.wb["TTB"]["J7"].value is None and ctx.wb[GL_TAB]["K6"].value is None


def _etb(ctx, codes):
    ws = ctx.wb.create_sheet("B1-ETB")
    for r, c in enumerate(codes, 8):
        ws.cell(row=r, column=1, value=c)
        ws.cell(row=r, column=8, value="=GL formula")
    return ws


def test_ledger_only_row_gross_and_etb_from_ttb():
    """GL > TTB > ETB: a ledger account with no TB line gets a TTB row of its own, the TTB shows the
    ledger's gross debits and credits, and B1-ETB takes the net per code from the TTB."""
    ctx = _ctx("movement")
    ctx.tx_rows.append(("02/05/2025", "3100", "", "Rent", "", "", "", 75.0, 0.0))
    etb = _etb(ctx, [0, 3100, 4800])
    add_ledger_chain(ctx)
    gl, ttb = ctx.wb[GL_TAB], ctx.wb["TTB"]
    assert gl["K9"].value == "Rent"
    assert (ttb["A9"].value, ttb["B9"].value, ttb["C9"].value) == (3100, "Rent", "In the GL only (no TB line)")
    assert ttb["L6"].value == "Debits per GL" and ttb["L7"].value.startswith(f"=SUMIFS('{GL_TAB}'!$G$7:$G$9,")
    assert ttb["M7"].value.startswith(f"=SUMIFS('{GL_TAB}'!$H$7:$H$9,")
    assert ttb["B10"].value == "TOTAL" and ttb["F10"].value == "=SUM(F7:F9)"
    assert etb["H9"].value == "=MAX(0,ROUND(SUMIFS(TTB!$J:$J,TTB!$A:$A,$A9),2))"
    assert etb["I9"].value == "=MAX(0,-ROUND(SUMIFS(TTB!$J:$J,TTB!$A:$A,$A9),2))"


def test_etb_keeps_gl_where_ttb_code_differs():
    """A ledger line with no code that belongs to a TB account: the TTB has it on the account's code, the ledger by
    code does not, so that code keeps the ledger's figure (the ETB's final balance never moves)."""
    ctx = _ctx("movement")
    ctx.tx_rows.append(("02/05/2025", None, "", "Bank Account", "", "", "", 10.0, 0.0))
    etb = _etb(ctx, [0, 4800])
    add_ledger_chain(ctx)
    assert etb["H8"].value.startswith("=MAX(0,")          # Sales: agrees
    assert etb["H9"].value == "=GL formula" and etb["H9"].comment is not None
