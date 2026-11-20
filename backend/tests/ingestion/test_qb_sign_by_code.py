"""QuickBooks GL sign: an account the TB cannot confirm takes its side from the firm code in its name."""
import pandas as pd

from backend.app.services.ingestion.ledger_files.openings import CODE_IN_NAME, OpeningBalances


def test_code_in_name():
    assert CODE_IN_NAME.match("5310 Corporation tax").group(1) == "5310"
    assert not CODE_IN_NAME.match("2024/25 rent")
    assert not CODE_IN_NAME.match("Sales")


def test_unconfirmed_account_signed_by_its_code(monkeypatch):
    monkeypatch.setattr(OpeningBalances, "_chart_sides", staticmethod(
        lambda accounts: {a: ("Credit" if a.startswith("5310") else "Debit") for a in accounts}))
    gl = pd.DataFrame([
        {"Parent_Account": "5310 Corporation tax", "Debit": 900.0, "Credit": 0.0},     # natural sign: went up
        {"Parent_Account": "3010 Directors salaries", "Debit": 1200.0, "Credit": 0.0},
    ])
    tb = pd.DataFrame([{"raw_account_name": "Something else", "net": 0.0}])
    out = OpeningBalances._orient_quickbooks_gl(gl, tb)
    tax = out[out["Parent_Account"] == "5310 Corporation tax"].iloc[0]
    pay = out[out["Parent_Account"] == "3010 Directors salaries"].iloc[0]
    assert (tax["Debit"], tax["Credit"]) == (0.0, 900.0)        # a liability's increase is a credit
    assert (pay["Debit"], pay["Credit"]) == (1200.0, 0.0)       # a cost stays a debit


def test_movement_tb_orients_accounts_with_an_opening(monkeypatch):
    """A TB of the year's movements (a TTB): an account with a GL opening balance is judged on its movement, so a
    liability that went up is a credit (VAT, CT, PAYE and creditors are not reversed)."""
    monkeypatch.setattr(OpeningBalances, "_chart_sides", staticmethod(lambda accounts: {}))
    gl = pd.DataFrame([{"Parent_Account": "VAT", "Debit": 3508.32, "Credit": 0.0},            # QuickBooks: went up
                       {"Parent_Account": "Corporation tax payable", "Debit": 0.0, "Credit": 15305.72}])   # went down
    gl.attrs["opening_balances"] = {"VAT": 5430.22, "Corporation tax payable": 14699.20}
    tb = pd.DataFrame([{"raw_account_name": "VAT", "net": -3508.32},                          # TTB: movements
                       {"raw_account_name": "Corporation tax payable", "net": 15305.72}])
    out = OpeningBalances._orient_quickbooks_gl(gl, tb)
    vat = out[out["Parent_Account"] == "VAT"].iloc[0]
    ct = out[out["Parent_Account"] == "Corporation tax payable"].iloc[0]
    assert (vat["Debit"], vat["Credit"]) == (0.0, 3508.32)
    assert (ct["Debit"], ct["Credit"]) == (15305.72, 0.0)
    assert out.attrs["opening_balances"] == {"VAT": -5430.22, "Corporation tax payable": -14699.20}
