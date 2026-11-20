"""Credits written with a minus sign are credits: a trial balance under a two-line heading ('Journals' over 'Debit |
Credit') whose credit figures are negative (Sales 0 | -49,501.79): Sales is a credit and the TB balances."""
import pandas as pd


def _clean(rows):
    from backend.app.services.ingestion.ingestion_service import IngestionService
    return IngestionService._clean_xero_tb(pd.DataFrame(rows))


def test_two_line_heading_negative_credits():
    df = _clean([["Code", "Accounts Name", "Journals", None, "Closing", "Balance Sheet"],
                 [None, None, "Debit", "Credit", "Balance", "Debit"],
                 [0, "Sales", 0, -49501.79, -49501.79, None],
                 [1100, "Purchases", 17852.47, 0, 17852.47, None],
                 [4800, "Bank", 49501.79, -17852.47, 31649.32, 31649.32]])
    net = dict(zip(df["raw_account_name"], df["net"]))
    assert net["0 - Sales"] == -49501.79 and net["1100 - Purchases"] == 17852.47
    assert round(df["net"].sum(), 2) == 0.0


def test_extended_tb_reads_the_final_pair():
    # 'Opening balances | Journals | Final Trial Balance', each Debit / Credit: the final pair is the year end
    df = _clean([["Code", "Nominal Name", "Opening balances", None, "Journals", None, "Final Trial Balance", None],
                 [None, None, "Debit £", "Credit £", "Debit £", "Credit £", "Debit £", "Credit £"],
                 [0, "Sale", None, None, 0, 29606.75, 0, 29606.75],
                 [3100, "Rent", None, None, 10800, 0, 10800, 0],
                 [4800, "Bank", 2028.36, None, 29606.75, 31818.28, 0, 183.17],
                 [5100, "Loan", 4136.52, None, 6374.27, 0, 10510.79, 0],
                 [5200, "Trade Creditors", None, 4832.69, 0, 0, 0, 4832.69],
                 [8000, "Surplus", None, 1332.19, 0, 0, 0, 1332.19],
                 [3050, "Welfare", None, None, 14644.01, 0, 14644.01, 0]])
    net = dict(zip(df["raw_account_name"], df["net"]))
    assert net["0 - Sale"] == -29606.75 and net["4800 - Bank"] == -183.17 and net["5100 - Loan"] == 10510.79
    assert round(df["net"].sum(), 2) == 0.0


def test_credit_column_all_negative():
    df = _clean([["Account", "Debit", "Credit"], ["Sales", 0, -1000.0], ["Bank", 1000.0, 0], ["Loan", 0, -50.0],
                 ["Costs", 50.0, 0]])
    net = dict(zip(df["raw_account_name"], df["net"]))
    assert net["Sales"] == -1000.0 and net["Loan"] == -50.0 and round(df["net"].sum(), 2) == 0.0


def test_usual_credit_column_unchanged():
    df = _clean([["Account", "Debit", "Credit"], ["Sales", 0, 1000.0], ["Bank", 1000.0, 0], ["Refund", 0, -20.0],
                 ["Costs", 0, 0]])
    net = dict(zip(df["raw_account_name"], df["net"]))
    assert net["Sales"] == -1000.0 and net["Refund"] == 20.0
