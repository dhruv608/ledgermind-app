"""A QuickBooks ledger line keeps its Name and Split as their own fields (the description keeps 'Name - Memo')."""
import pandas as pd

from backend.app.api.endpoints.upload import _party_of
from backend.app.services.ingestion.ledger_files.cleaning import LedgerCleaning


def test_classic_reader_keeps_name_and_split():
    headers = ["", "Date", "Transaction type", "No.", "Name", "Memo/Description", "Split", "Amount", "Balance"]
    rows = [headers,
            ["Insurance", None, None, None, None, None, None, None, None],
            ["", "01/06/2024", "Bill", "INV-1", "Insurer Ltd", "Policy", "Accounts Payable", 120.0, 120.0],
            ["", "02/06/2024", "Expense", "", None, "Card fee", None, 5.0, 125.0]]
    out = LedgerCleaning._clean_quickbooks_classic_gl(pd.DataFrame(rows), 0, headers)
    first, second = out.iloc[0], out.iloc[1]
    assert (first["Name"], first["Split"], first["Description"]) == ("Insurer Ltd", "Accounts Payable",
                                                                     "Insurer Ltd - Policy")
    assert pd.isna(second["Name"]) and pd.isna(second["Split"])


def test_party_of():
    assert _party_of({"Name": "Insurer Ltd", "Split": "Accounts Payable"}) == ("Insurer Ltd", "Accounts Payable")
    assert _party_of({"Name": " ", "Split": float("nan")}) is None
    assert _party_of({}) is None
