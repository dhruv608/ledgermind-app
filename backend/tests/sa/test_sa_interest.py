"""Savings interest read from statements (made-up figures): ISA and joint tags, the tax-year check, the owner check and
interest credited on a bank statement (R-SAV-01 to 03)."""

from backend.app.sa.extract import interest as I


def test_accounts_tagged_isa_and_joint():
    f = I.clean({"provider": "A Building Society", "period_from": "2025-04-06", "period_to": "2026-04-05",
                 "holders": ["Mr Sam Saver", "Mrs Jo Saver"],
                 "accounts": [{"account_last4": "12345678", "account_name": "Cash ISA", "isa": False, "joint": False, "interest_gross": "120.50"},
                              {"account_last4": "9999", "account_name": "Easy Saver", "joint": True, "interest_gross": 80, "tax_deducted": None},
                              {"account_name": "Closed bond", "interest_gross": None}]})
    assert [(a["account_last4"], a["isa"], a["joint"], a["interest_gross"]) for a in f["accounts"]] == [
        ("5678", True, False, 120.5), ("9999", False, True, 80.0)]      # 'Cash ISA' in the name is an ISA
    assert I.checks(f, "2025-26", "Sam Saver") == ("READ", [])


def test_another_year_and_another_person():
    f = I.clean({"period_from": "2024-04-06", "period_to": "2025-04-05", "accounts": [{"account_name": "Saver", "interest_gross": 10}]})
    assert I.checks(f, "2025-26")[0] == "OTHER_YEAR"
    g = I.clean({"holders": ["Alex Other"], "accounts": [{"account_name": "Saver", "interest_gross": 10}]})
    assert I.checks(g, "2025-26", "Sam Saver")[0] == "CHECK" and g["other_person"]
    h = I.clean({"period_from": "2025-01-01", "period_to": "2025-12-31", "accounts": [{"account_name": "Saver", "interest_gross": 10}]})
    status, notes = I.checks(h, "2025-26")
    assert status == "CHECK" and "R-SAV-02" in notes[0]                 # a calendar-year statement


def test_two_readers_must_agree():
    first = I.clean({"accounts": [{"account_name": "Saver", "interest_gross": 555.70}]})
    status, notes = I.checks(first, "2025-26", second={"accounts": [{"account_name": "Saver", "interest_gross": 55.57}]})
    assert status == "CHECK" and "disagree" in notes[0]


def test_interest_credited_on_a_bank_statement():
    pages = [{"lines": [["2025-07-20", "Interest Added", 555.70, None, 11388.0],
                        ["2025-07-20", "Transfer to 18N80564", None, 11388.0, 0.0],
                        ["2025-08-01", "Overdraft interest charged", 3.10, None, 10.0],
                        ["2025-03-31", "Interest", 12.0, None, 100.0]]}]              # before the tax year
    assert I.from_statement(pages, "2025-04-06", "2026-04-05") == (555.7, 1)


def test_the_office_notes_are_not_a_statement():
    from backend.app.sa.extract.classify import classify
    assert classify("Interest paid on the Santander account", "Client/Notes.docx") == "OTHER"
    assert classify("Interest paid to you this year", "Interest certificate.pdf") == "INTEREST_STATEMENT"


def test_joint_and_isa_words_on_an_account_name():
    assert I.JOINT_WORDS.search("Barclays Joint Account") and not I.JOINT_WORDS.search("Everyday Saver")
    assert I.ISA_WORDS.search("Cash ISA Saver") and not I.ISA_WORDS.search("Isabel's account")


def test_interest_paid_in_the_year_counts_from_a_statement_across_the_year_end():
    ans = {"provider": "Bank A", "period_from": "2024-03-16", "period_to": "2024-04-17", "holders": [],
           "accounts": [{"account_name": "Saver", "interest_gross": "12.40", "paid_on": "2024-04-16"}]}
    f = I.clean(ans)
    assert I.checks(f, "2024-25", None, ans) == ("READ", [])               # paid 16 April 2024: this year's, no split
    late = dict(ans, period_from="2025-03-18", period_to="2025-04-17",
                accounts=[{"account_name": "Saver", "interest_gross": "13.10", "paid_on": "2025-04-17"}])
    assert I.checks(I.clean(late), "2024-25")[0] == "OTHER_YEAR"            # paid 17 April 2025: next year's
    undated = dict(ans, accounts=[{"account_name": "Saver", "interest_gross": "12.40"}])
    assert I.checks(I.clean(undated), "2024-25")[0] == "CHECK"             # no date printed: still split by a person


def test_the_years_certificate_is_the_whole_year():
    assert I.whole_year({"period_from": "2024-04-06", "period_to": "2025-04-05"}, "2024-04-06", "2025-04-05")
    assert I.whole_year({"period_from": None, "period_to": "2025-04-05"}, "2024-04-06", "2025-04-05")
    assert not I.whole_year({"period_from": "2025-03-18", "period_to": "2025-04-17"}, "2024-04-06", "2025-04-05")
    assert not I.whole_year({"period_from": "2025-01-06", "period_to": "2025-04-05"}, "2024-04-06", "2025-04-05")


def test_a_years_summary_in_a_months_statement_gives_the_years_interest():
    from backend.app.sa.extract.interest import with_text
    f = {"provider": "Bank A", "period_from": "2025-04-01", "period_to": "2025-04-30", "holders": [],
         "accounts": [{"account_last4": "6340", "account_name": "Saver", "isa": False, "joint": False,
                       "interest_gross": 21.81, "tax_deducted": 0.0, "paid_on": "2025-04-01"}]}
    text = ("01 - 30 Apr 2025 You earned £21.81 ... Interest Summary This is a summary of the gross interest earned "
            "on your account for the tax year 6 Apr 2024 to 5\r\nApr 2025. Gross interest earned £2,211.26")
    out = with_text(f, text)
    assert out["accounts"][0]["interest_gross"] == 2211.26 and (out["period_from"], out["period_to"]) == ("2024-04-06", "2025-04-05")
    assert with_text(f, "01 - 30 Apr 2025 You earned £21.81") == f        # no summary: the reading as it was


def test_a_text_layer_of_font_codes_is_not_read_as_text():
    from backend.app.sa.documents import readable
    assert not readable("".join(chr(c) for c in range(4, 30)) * 5)
    assert readable("Interest statement for the tax year 6 April 2024 to 5 April 2025: gross interest £384.61 paid.")


def test_a_clients_list_is_checked_against_its_total_row():
    from backend.app.sa.extract.interest import checks, with_text
    f = {"provider": None, "period_from": None, "period_to": None, "holders": [],
         "accounts": [{"account_last4": None, "account_name": "Saver", "isa": False, "joint": False,
                       "interest_gross": 780.7, "tax_deducted": 0.0, "paid_on": None}]}
    out = with_text(f, "Bank | account | gross int\nBank A | Saver | 780.7\nBank B\nbond | 1049.27\ntotal | 1829.97")
    status, notes = checks(out, "2024-25")
    assert out["printed_total"] == 1829.97 and status == "CHECK" and "1,049.27 less" in notes[0]
    whole = dict(out, accounts=out["accounts"] + [dict(out["accounts"][0], interest_gross=1049.27)])
    assert checks(whole, "2024-25") == ("READ", [])


def test_a_brokers_certificate_page_is_found_and_its_dividends_kept():
    from backend.app.sa.extract.interest import certificate_text, clean
    pages = ["Contents: Consolidated tax certificate 21", "Schedule of transactions",
             "We hereby certify that the dividends or interest summarised below were received by us. UK deposit interest 109.35",
             "Income schedules continued", "Guide"]
    assert certificate_text(pages).startswith("We hereby certify") and "Income schedules" in certificate_text(pages)
    assert certificate_text(["A bank statement"]) is None
    f = clean({"accounts": [{"account_name": "UK deposit interest", "interest_gross": 109.35}],
               "dividends": [{"payer": "UK companies dividends", "amount": "607.29", "overseas": False},
                             {"payer": "Overseas unit trust dividends", "amount": 641.19, "overseas": True},
                             {"payer": "UK venture capital trust dividends", "amount": None}]})
    assert [(d["company"], d["amount"], d["overseas"]) for d in f["dividends"]] == [
        ("UK companies dividends", 607.29, False), ("Overseas unit trust dividends", 641.19, True)]


def test_a_funds_interest_distribution_is_interest_not_a_dividend():
    from backend.app.sa.extract.interest import clean
    f = clean({"provider": "Broker A", "accounts": [{"account_name": "UK deposit interest", "interest_gross": 528.04}],
               "dividends": [{"payer": "UK Dividends", "amount": 691.0}, {"payer": "Interest on Unit Trusts", "amount": 582.74},
                             {"payer": "Loyalty Bonus", "amount": 0.87}]})
    assert [d["company"] for d in f["dividends"]] == ["UK Dividends"]
    assert [a["interest_gross"] for a in f["accounts"]] == [528.04, 582.74, 0.87]
