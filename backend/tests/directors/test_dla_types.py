"""Each type on its own DLA line; money introduced apart from expenses paid personally."""
from backend.app.services.workbook.context import DLA_DRAWINGS, DLA_EXPENSES, DLA_INTRODUCED, dla_type


def _row(source, debit, credit, description="x"):
    return ("01/01/2025", "5400", "", "Directors loan", source, description, "", debit, credit)


def test_types():
    assert dla_type(_row("Expense", 0, 50)) == DLA_EXPENSES
    assert dla_type(_row("Bill", 0, 50)) == DLA_EXPENSES
    assert dla_type(_row("Deposit", 0, 50)) == DLA_INTRODUCED
    assert dla_type(_row("Transfer", 0, 50)) == DLA_INTRODUCED
    assert dla_type(_row("Transfer", 50, 0)) == DLA_DRAWINGS
    assert dla_type(_row("Expenses", 0, 50)) == DLA_INTRODUCED     # whole word only
    assert dla_type(_row("Journal", 0, 50, "Dividend declared")) == "Dividends credited"
