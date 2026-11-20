"""The newer QuickBooks GL layout keeps the VAT code and amount. Made-up lines."""
import pandas as pd

from backend.app.services.ingestion.ingestion_service import IngestionService


def test_vat_columns_kept():
    rows = [["General Ledger", None, None, None, None, None, None, None],
            ["Transaction date", "Transaction type", "No.", "Name", "Description", "Distribution account", "Amount",
             "VAT amount"],
            ["Sales", None, None, None, None, None, None, None],
            ["01/05/2025", "Invoice", "101", "Customer A", "Design work", "Sales", "-1000.00", "-200.00"],
            ["Total for Sales", None, None, None, None, None, None, None]]
    raw = pd.DataFrame(rows)
    raw[8] = [None, "VAT code", None, "20.0% S", None]
    raw.iloc[1, 8] = "VAT code"
    out = IngestionService._clean_universal_gl(raw, "QUICKBOOKS")
    line = out.iloc[0]
    assert line["Credit"] == 1000.0 and line["VAT"] == -200.0 and line["VAT Code"] == "20.0% S"


def test_no_vat_columns_no_vat():
    rows = [["Transaction date", "Transaction type", "No.", "Name", "Description", "Distribution account", "Amount"],
            ["Rent", None, None, None, None, None, None],
            ["01/05/2025", "Expense", "", "Landlord", "May", "Rent", "500"]]
    out = IngestionService._clean_universal_gl(pd.DataFrame(rows), "QUICKBOOKS")
    assert out.iloc[0]["VAT"] is None and out.iloc[0]["VAT Code"] is None
