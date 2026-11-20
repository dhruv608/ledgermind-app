"""One bad cell in a client's ledger must not stop the whole upload (a letter 'l'
in an amount, a line with no date)."""
import pandas as pd

from backend.app.services.ingestion.ingestion_service import readable_amounts


def test_text_in_an_amount_reads_as_nil():
    gl = pd.DataFrame({"Parent_Account": ["Wages", "Wages", "Bank"], "Debit": ["l", "1,200.50", None],
                       "Credit": [0, 0, "1200.50"]})
    gl.attrs["opening_balances"] = {"Bank": 10.0}
    out = readable_amounts(gl)
    assert out["Debit"].tolist() == [0.0, 1200.5, 0.0]
    assert out["Credit"].tolist() == [0.0, 0.0, 1200.5]
    assert out.attrs["opening_balances"] == {"Bank": 10.0}
