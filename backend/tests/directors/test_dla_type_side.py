"""DLA line types: what is credited to the director only on a credit line; a debit naming salary is a payment out
(members' 'Salary' payments are not 'Net salary credited')."""
from backend.app.services.workbook.context import DLA_DRAWINGS, dla_type


def tx(desc, dr, cr, source="Spend Money"):
    return ("02/06/2025", "5400", "", "Capital Account", source, desc, "", dr, cr)


def test_salary_paid_out_is_drawings():
    assert dla_type(tx("Salary - AIDAN KETTLE", 4000.0, 0.0)) == DLA_DRAWINGS


def test_salary_credited_stays():
    assert dla_type(tx("Net salary May", 0.0, 1500.0, "Manual Journal")) == "Net salary credited"
    assert dla_type(tx("Dividend declared", 0.0, 5000.0, "Manual Journal")) == "Dividends credited"


def test_interest_either_side():
    assert dla_type(tx("Interest charged", 50.0, 0.0, "Manual Journal")) == "Interest"
