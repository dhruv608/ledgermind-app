"""Last year's TB in the firm's codes but the preparer's own wording ('CT', 'Creditors': the firm's 'Opening BS (use
this)' sheets) is read by its codes; a TB in another system's own numbers is not."""
import pandas as pd

from backend.app.services.review.last_year_read import firm_coded_lines

CHART = {4150: "Computer equipment - cost", 4153: "Computer equipment - depreciation b/fwd", 4420: "Other debtors",
         4800: "Bank current account", 5100: "Bank loans", 5200: "Trade creditors", 5300: "VAT",
         5310: "Corporation tax", 8000: "Balance b/fwd", 400: "Advertising", 200: "Something else"}


def _tb(rows):
    return pd.DataFrame([["Code", "Account", "Debit", "Credit"]] + rows)


def test_firm_codes_with_the_preparers_own_names_are_read():
    df = _tb([[4150, "Computer kit", 4129, None], [4153, "Comp dep b/fd", None, 114.68],
              [4420, "Sundry", 15759.14, None], [4800, "Virgin Money_075", 4894.37, None],
              [5100, "Loan", None, 6000], [5300, "VAT Control", None, 3000], [5310, "CT", None, 1600],
              [8000, "Reserves", None, 14067.83]])
    lines = firm_coded_lines(df, CHART)
    assert lines is not None and len(lines) == 8 and abs(sum(l.amount for l in lines)) < 0.01


def test_another_systems_numbers_are_not_taken_for_firm_codes():
    df = _tb([[200, "Sales", None, 5000], [310, "Cost of goods", 2000, None], [610, "Accounts receivable", 1500, None],
              [877, "Tracking transfers", 1500, None]])
    assert firm_coded_lines(df, CHART) is None
