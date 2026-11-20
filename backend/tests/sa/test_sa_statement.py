"""Bank statements put together (made-up pages): duplicates, date order, the balance chain and breaks between pages."""

from backend.app.sa.extract.statement import PageRead, StatementLine as L, assemble, chain_break, covers


def page(n, bf, cf, *lines):
    return PageRead(n, [L(on, d, i, o, b) for on, d, i, o, b in lines], bf, cf)


MAY = page(1, 1000.0, 1150.0, ("2025-05-02", "Customer", 200, 0, 1200.0), ("2025-05-20", "Materials", 0, 50, 1150.0))
APRIL = page(2, 900.0, 1000.0, ("2025-04-08", "Customer", 150, 0, 1050.0), ("2025-04-30", "Fuel", 0, 50, 1000.0))


def test_newest_first_and_a_month_sent_twice():
    acc = assemble([(1, MAY), (1, APRIL), (2, page(9, 1000.0, 1150.0, *[(l.on, l.description, l.money_in, l.money_out, l.balance) for l in MAY.lines]))])
    assert acc.duplicates == 1 and [l.on for l in acc.lines][0] == "2025-04-08"
    assert (acc.opening, acc.closing, acc.money_in, acc.money_out, acc.checks) == (900.0, 1150.0, 350.0, 100.0, [])


def test_a_break_between_pages_is_a_check():
    june = page(3, 1170.0, 1100.0, ("2025-06-03", "Insurance", 0, 70, 1100.0))     # May ended at 1,150.00
    acc = assemble([(1, APRIL), (1, MAY), (1, june)])
    assert len(acc.checks) == 1 and "1,170.00" in acc.checks[0]


def test_chain_within_a_page_and_period_covered():
    lines = [L("2025-04-08", "a", 100, 0, None), L("2025-04-08", "b", 0, 30, 1070.0), L("2025-04-09", "c", 0, 10, 1061.0)]
    assert chain_break(lines, 1000.0) == 2                     # 1,070 - 10 is 1,060, not 1,061
    acc = assemble([(1, APRIL), (1, MAY)])
    assert len(covers(acc, "2025-04-06", "2026-04-05")) == 2   # starts 8 April, ends 20 May


def test_lines_printed_newest_first_are_put_in_date_order():
    from backend.app.sa.extract.statement import _page
    # Online banking: the newest line on top, each balance after its own line
    ans = {"brought_forward": None, "lines": [
        {"date": "2026-04-02", "description": "Shop", "in": None, "out": 43.90, "balance": 798.94},
        {"date": "2026-04-01", "description": "Rent in", "in": 27.00, "out": None, "balance": 842.84},
        {"date": "2026-03-31", "description": "Fuel", "in": None, "out": 15.50, "balance": 815.84}]}
    p = _page(1, ans, "reader")
    assert p.chains and [l.on for l in p.lines] == ["2026-03-31", "2026-04-01", "2026-04-02"]
    acc = assemble([(1, p)])
    assert (acc.opening, acc.closing, acc.checks) == (831.34, 798.94, [])


def test_a_text_page_amount_is_held_to_what_is_printed():
    # The reader dropped the pence point ('500.00' read as 50000): put back from the page's own text
    from backend.app.sa.extract.statement import as_printed, PageRead, StatementLine
    text = "BSF - 2\n500.00\n0.00\nFor recording\n3000.00\nTotal commission 630.00\nBalance 1,234.56"
    p = PageRead(1, [StatementLine("2025-12-08", "a", 50000.0, 0, None), StatementLine("2025-12-12", "b", 300000.0, 0, None),
                     StatementLine("2025-12-12", "c", 0, 63000.0, None), StatementLine("2025-12-13", "d", 1234.56, 0, None)], None, None)
    assert [(l.money_in, l.money_out) for l in as_printed(p, text).lines] == [(500.0, 0), (3000.0, 0), (0, 630.0), (1234.56, 0)]


def test_thousands_printed_with_a_space_are_left_alone():
    # Revolut prints '£3 000.00': the 3000 read is right, not a dropped point (30.00 is printed elsewhere)
    from backend.app.sa.extract.statement import as_printed, PageRead, StatementLine
    text = "Payee £3 000.00 £3 659.73\nCostco £30.00 £2 718.77"
    p = PageRead(1, [StatementLine("2025-12-16", "To payee", 0, 3000.0, None), StatementLine("2025-12-17", "Costco", 0, 30.0, None)], None, None)
    assert [l.money_out for l in as_printed(p, text).lines] == [3000.0, 30.0]


def test_lines_put_in_the_statements_own_period():
    # An online download prints '31 Mar' with no year: a page read alone guessed 2024 for a 2025-26 statement
    from backend.app.sa.extract.statement import PageRead, StatementLine, into_period, period_of
    period = period_of(["Account details From 01/04/2025 To 31/03/2026 Your transactions"])
    assert period == ("2025-04-01", "2026-03-31")
    p = PageRead(2, [StatementLine("2024-06-13", "A", 10.0, 0, None), StatementLine("2023-12-24", "B", 5.0, 0, None),
                     StatementLine("2025-09-01", "C", 1.0, 0, None)], None, None)
    assert into_period([p], period) == 2 and [l.on for l in p.lines] == ["2025-06-13", "2025-12-24", "2025-09-01"]


def test_a_document_stops_starting_pages_when_its_time_is_up():
    # A slow AI service: past the time limit no new page is read; those pages are marked, not waited for
    from backend.app.sa.extract import statement
    calls = []
    real = statement._ask
    statement._ask = lambda img, model: calls.append(img) or None
    try:
        out = statement.read_pages([b"p1", b"p2", b"p3"], threads=1, time_limit=-1)
    finally:
        statement._ask = real
    assert calls == [] and [p.skipped for p in out] == [True, True, True]


def test_an_overdrawn_brought_forward_read_without_its_minus():
    from backend.app.sa.extract.statement import _page
    ans = {"brought_forward": 658.95, "lines": [
        {"date": "2024-04-06", "description": "Customer", "in": 500.0, "out": None, "balance": -158.95}]}
    p = _page(1, ans, "reader")
    assert p.chains and p.brought_forward == -658.95


def test_a_misread_brought_forward_is_put_right_by_the_page_before():
    from backend.app.sa.extract.statement import misread_brought_forward
    june = page(2, 1510.0, 1100.0, ("2025-06-03", "Insurance", 0, 50, 1100.0))     # May ended at 1,150.00
    june.chains = chain_break(june.lines, june.brought_forward) is None
    assert not june.chains
    assert misread_brought_forward([MAY, june]) == 1 and june.chains and june.brought_forward == 1150.0


def test_a_line_lost_at_the_top_of_a_page_stays_held():
    from backend.app.sa.extract.statement import misread_brought_forward
    # June opens at 1,150.00 like May's close, but its first balance needs 1,200.00: a line is missing
    june = page(2, 1150.0, 1150.0, ("2025-06-03", "Insurance", 0, 50, 1150.0))
    june.chains = chain_break(june.lines, june.brought_forward) is None
    assert misread_brought_forward([MAY, june]) == 0 and not june.chains


def test_a_page_with_no_balances_saved_twice_is_counted_once():
    report = page(1, None, None, ("2024-07-31", "Orders (total minus fees)", 2911.27, 0, None), ("2024-07-31", "Payouts", 0, 3163.73, None))
    again = page(1, None, None, *[(l.on, l.description, l.money_in, l.money_out, l.balance) for l in report.lines])
    acc = assemble([(1, report), (2, again)])
    assert acc.duplicates == 1 and len(acc.lines) == 2


def test_an_investment_accounts_value_change_is_not_takings():
    from backend.app.sa.books import INVESTMENT_VALUE
    assert INVESTMENT_VALUE.search("Change in Investment Value")
    assert INVESTMENT_VALUE.search("Unrealised gain")
    assert not INVESTMENT_VALUE.search("Valuation fee from client")         # a surveyor's takings stay takings


def test_a_selling_platforms_own_report_and_its_month_sent_twice():
    from types import SimpleNamespace as NS
    from backend.app.sa.books import platform_of, platform_copies, PLATFORM_PAYOUT, PLATFORM_FUNDING, CARD_REPAYMENT
    assert platform_of("Client A/eBay/Reports/Financial Statement 2024-06.pdf", "eBay Commerce UK Ltd.") == "ebay"
    assert platform_of("Client A/PayPal/Statement 2025-03.pdf", "Lloyds Bank") is None     # a bank's, in the wrong folder
    assert platform_of("Client A/PayPal/Statement 2024-05.pdf", None) == "paypal"
    detailed = {"pages": [{"lines": [[f"2024-06-{d:02d}", "Sale", 10, 0, None] for d in range(1, 31)]}]}
    summary = {"pages": [{"lines": [["2024-06-30", "Orders (total minus fees)", 300, 0, None], ["2024-06-30", "Payouts", 0, 290, None]]}]}
    week1 = {"pages": [{"lines": [["2024-07-01", "Sale", 5, 0, None], ["2024-07-07", "Sale", 5, 0, None]]}]}
    week2 = {"pages": [{"lines": [["2024-07-08", "Sale", 5, 0, None], ["2024-07-14", "Sale", 5, 0, None]]}]}
    docs = [NS(id=i) for i in (1, 2, 3, 4)]
    fields = {1: detailed, 2: summary, 3: week1, 4: week2}
    assert platform_copies(docs, fields, {1: "ebay", 2: "ebay", 3: "ebay", 4: "ebay"}) == {2}   # weekly ones all kept
    assert PLATFORM_PAYOUT.search("Payouts") and PLATFORM_FUNDING.search("General Credit Card Deposit")
    assert CARD_REPAYMENT.search("DIRECT DEBIT PAYMENT - THANK YOU") and CARD_REPAYMENT.search("Payments received")
    assert not CARD_REPAYMENT.search("Faster payment received from Customer A")   # a customer paying: takings


def test_a_statements_currency_is_read_as_its_code():
    from backend.app.sa.extract.statement import currency_of
    assert currency_of("€") == "EUR" and currency_of("Sterling") == "GBP" and currency_of("usd") == "USD"
    assert currency_of(None) is None and currency_of("euros and pounds") is None


def test_own_transfers_and_payments_from_people_when_the_client_lets_property():
    from backend.app.sa.books import OWN_TRANSFER, from_a_person
    assert OWN_TRANSFER.search("404758 51501151 INTERNAL TRANSFER")
    assert not OWN_TRANSFER.search("TRANSFER FROM CUSTOMER A LTD")
    assert from_a_person("MISS PERSON A") and from_a_person("BACS Person Alpha")
    assert not from_a_person("ALPHA DEVELOPMENTS LT") and not from_a_person("CARD PAYMENT SHOP A")


def test_wages_paid_in_are_never_a_refund_of_a_cost():
    from backend.app.sa.books import WAGES_IN
    assert WAGES_IN.search("Received From Employer A Ref: Wage") and WAGES_IN.search("SALARY EMPLOYER B")
    assert not WAGES_IN.search("Refund from Supplier A")                  # a supplier's refund still lowers the cost


def test_a_car_bought_is_not_a_running_cost():
    from backend.app.sa.books import car_bought
    assert car_bought("PAYMENT TO DEALER A CAR SALES LTD", 11800) and car_bought("SHOP A MOTORS LTD", 8500)
    assert not car_bought("SHOP A MOTORS LTD SERVICE", 250)              # a garage's bill stays a cost


def test_money_for_a_vehicle_sold_is_not_takings():
    from backend.app.sa.books import VEHICLE_SOLD
    assert VEHICLE_SOLD.search("PERSON A VAN DEPOSIT 4000") and VEHICLE_SOLD.search("Sale of my van")
    assert not VEHICLE_SOLD.search("VANESSA DEPOSIT") and not VEHICLE_SOLD.search("INV 55 CUSTOMER A")


def test_the_same_weeks_printed_twice_in_one_file_are_counted_once():
    a = page(1, 1000.0, 1150.0, ("2025-05-02", "Customer A", 200, 0, 1200.0), ("2025-05-20", "Materials", 0, 50, 1150.0))
    # the same two lines in another layout, later in the file (other words, same day, amount and balance)
    b = page(9, None, 1150.0, ("2025-05-02", "FP CUSTOMER A REF 123", 200, 0, 1200.0), ("2025-05-20", "CARD MATERIALS", 0, 50, 1150.0))
    acc = assemble([(1, a), (1, b)])
    assert len(acc.lines) == 2 and acc.money_in == 200.0


def test_a_card_statements_monthly_summary_is_not_a_payment():
    from backend.app.sa.books import CARD_SUMMARY
    assert CARD_SUMMARY.search("New transactions, fees and charges") and CARD_SUMMARY.search("Previous balance")
    assert not CARD_SUMMARY.search("Bank charges for the month")


def test_paying_off_a_credit_card_is_own_money_moved():
    from backend.app.sa.books import PAY_CARD_OFF, CARD_COST_WORDS
    off = lambda t: bool(PAY_CARD_OFF.search(t)) and not CARD_COST_WORDS.search(t)
    assert off("Direct Debit to Card A Credit Card Ref: 5570") and off("BARCLAYCARD")
    assert not off("CREDIT CARD FEE") and not off("AQUARIUM SUPPLIES")


def test_wages_from_an_employer_whose_name_the_bank_cuts_short():
    from backend.app.sa.books import employer_in, _employer_words
    w = _employer_words(["Alphabeta Kabi Limited"])
    assert employer_in("Automated Credit 349935419ALPHABE", w)
    assert not employer_in("Automated Credit CUSTOMER A UK", w)


def test_an_overdrawn_balance_read_without_its_sign_is_turned_round():
    from backend.app.sa.extract.statement import overdrawn_signs
    lines = [L("2024-04-07", "Rent in", 2883.0, 0, 3820.87), L("2024-04-08", "Payment", 0, 3443.44, 377.43),
             L("2024-04-08", "Cheque", 0, 494.04, 116.61)]           # printed '116.61D': -116.61
    assert overdrawn_signs(lines, 937.87) == 1 and lines[2].balance == -116.61
    assert chain_break(lines, 937.87) is None


def test_the_same_money_out_of_one_own_account_and_into_another_is_a_transfer():
    from datetime import date
    from types import SimpleNamespace as NS
    from backend.app.sa.books import own_transfer_pairs
    o = NS(money_out=9000.0, money_in=0.0, when=date(2024, 11, 18), description="OnLine Transaction SHOP A AF VIA MOBILE")
    i = NS(money_out=0.0, money_in=9000.0, when=date(2024, 11, 18), description="OnLine Transaction SHOP B AF VIA MOBILE")
    sale = NS(money_out=0.0, money_in=9000.0, when=date(2024, 11, 18), description="Automated Credit CUSTOMER X")
    lines = [NS(line=x) for x in (o, i, sale)]
    keep = {id(o): ("0770", None), id(i): ("4186", None), id(sale): ("4186", None)}
    assert own_transfer_pairs(lines, keep) == {id(o), id(i)}          # the customer's 9,000 stays takings


def test_a_card_statements_summary_box_is_not_a_line():
    from backend.app.sa.extract.statement import _lines
    got = _lines({"lines": [{"date": "2024-11-10", "description": "Total amount you repaid between 19 October and 10 November",
                             "in": 13944.53},
                            {"date": "2024-11-10", "description": "Amount spent on purchases", "out": 13946.56},
                            {"date": "2024-11-10", "description": "Balance carried forward", "out": 10.5},
                            {"date": "2024-11-02", "description": "PAYMENT RECEIVED THANK YOU", "in": 500.0},
                            {"date": "2024-11-03", "description": "NEW BALANCE ATHLETICS", "out": 64.2},
                            {"date": "2024-11-10", "description": "New balance", "out": 5.0}]}, 0)
    assert [l.description for l in got] == ["PAYMENT RECEIVED THANK YOU", "NEW BALANCE ATHLETICS"]
