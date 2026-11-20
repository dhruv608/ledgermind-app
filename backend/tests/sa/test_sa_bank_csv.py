"""A bank's own CSV export read by code (made-up lines): the header found under the account lines, money in and out
from two columns or one signed amount, each day's lines put in order when the bank prints them newest first."""

from backend.app.sa.extract import bank_csv
from backend.app.sa.extract.classify import classify


def test_paid_in_and_out_columns_under_the_account_lines():
    data = ('"Account Name:","Joint Saver Account ****12345"\n"Account Balance:","£1,000.00"\n\n'
            '"Date","Transaction type","Description","Paid out","Paid in","Balance"\n'
            '"15 Jul 2024","Card","CAFE","£3.05","","£996.95"\n'
            '"16 Jul 2024","Transfer","FROM A FRIEND","","£50.00","£1,046.95"\n').encode("cp1252")
    r = bank_csv.read(data, "Statement Download.csv")
    assert r["account_last4"] == "2345" and r["account_name"] == "Joint Saver Account"
    assert r["lines"] == [("2024-07-15", "CAFE", 0.0, 3.05, 996.95), ("2024-07-16", "FROM A FRIEND", 50.0, 0.0, 1046.95)]


def test_a_signed_amount_and_each_day_newest_first():
    data = (b"Date,Type,Description,Value,Balance,Account Name,Account Number\n"
            b"02-Apr-24,D/D,INSURER,-27.68,524.65,Current,111111-22223331\n"
            b"02-Apr-24,D/D,MORTGAGE,-1501.78,552.33,Current,111111-22223331\n"
            b"02-Apr-24,BAC,EMPLOYER,2054.11,2054.11,Current,111111-22223331\n"
            b"03-Apr-24,D/D,PHONE,-20.00,484.65,Current,111111-22223331\n"
            b"03-Apr-24,D/D,WATER,-20.00,504.65,Current,111111-22223331\n")
    r = bank_csv.read(data, "Current.csv")
    assert r["account_last4"] == "3331"
    assert [l[1] for l in r["lines"]] == ["EMPLOYER", "MORTGAGE", "INSURER", "WATER", "PHONE"]        # the day turned round: it chains


def test_not_a_bank_export():
    assert not bank_csv.looks_like("Date,Type,Title,Info,Currency,Amount,Fees & Taxes,Net,Tax Details\n")
    assert bank_csv.looks_like("Transaction Date,Transaction Type,Sort Code,Account Number,Transaction Description,"
                               "Debit Amount,Credit Amount,Balance\n")


def test_file_names_are_read_by_whole_words():
    assert classify("", "Current Account transactions.csv") == "BANK_STATEMENT"  # 'current' is not rent
    assert classify("", "Rent statement May.pdf") == "LETTING_STATEMENT"
    assert classify("", "Visa statement.pdf") == "BANK_STATEMENT"                # 'visa' is not an ISA


def test_a_clients_own_rent_sheet_is_read_as_a_rent_statement():
    # Rent month by month with fees: read with no agent, so it waits for the accountant to confirm it
    sheet = "[Sheet1] Rent 900 Rent 900 Rent 900 Fees 90 Fees 90 Boiler plan 20 Income per person"
    assert classify(sheet, "House 2526.xlsx") == "LETTING_STATEMENT"
    trade = "[INCOME] INVOICE NUMBER DATE CUSTOMER JOB Rent 1 Rent 2 Rent 3 Repairs Sales"
    assert classify(trade, "Income 24-25.xlsx") != "LETTING_STATEMENT"


def test_an_online_banking_download_is_a_bank_statement():
    text = "Transactions-01 SHOP NAME Business Current Your transactions Date Description Type Paid in (£) Paid out (£)"
    assert classify(text, "TXN_31032026_NatWest.pdf") == "BANK_STATEMENT"


def test_a_scans_file_name_names_its_kind():
    # Used when the reader cannot tell what a scan is (a letter in French, a scanned 'P60.pdf')
    assert classify("", "Letter from french authorities.pdf") == "FOREIGN_TAX"
    assert classify("", "P60 Whitbread April 2025.JPG") == "P60"
