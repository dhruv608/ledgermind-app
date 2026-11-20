"""A sole trader's bank lines sorted under the SA103 headings (made-up lines; no database needed)."""

import sys
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# The bank rules import the app's models, which make their tables on import: a stand-in database for this test
if "backend.app.core.database" not in sys.modules:
    _db = types.ModuleType("backend.app.core.database")
    _db.Base, _db.engine, _db.create_table = declarative_base(), create_engine("sqlite://"), lambda table: None
    _db.SessionLocal, _db.get_db = sessionmaker(bind=_db.engine), lambda: None
    sys.modules["backend.app.core.database"] = _db

from backend.app.sa import books as B                                       # noqa: E402
from backend.app.sa.extract.statement import Account, StatementLine as L    # noqa: E402


def account(*lines):
    return [("1234", "Bank", Account(lines=[L(on, d, i, o, None) for on, d, i, o in lines], opening=100.0))]


LINES = account(
    ("2025-03-30", "FASTER PAYMENTS RECEIPT REF.JOB FROM A Customer", 50, 0),           # before the period
    ("2025-04-10", "FASTER PAYMENTS RECEIPT REF.ELECTRICAL WORK FROM A Customer", 400, 0),
    ("2025-04-12", "CARD PAYMENT TO SCREWFIX DIRECT ON 11-04-2025", 0, 120),
    ("2025-04-20", "CREDIT FROM SCREWFIX DIR LTD ON 19-04-2025", 20, 0),
    ("2025-05-01", "BILL PAYMENT VIA FASTER PAYMENT TO J SMITH REFERENCE DRAWINGS", 0, 300),
    ("2025-05-02", "FASTER PAYMENTS RECEIPT REF.SAVINGS FROM PAT TRADER", 80, 0),
    ("2025-05-03", "CARD PAYMENT TO SHELL GARAGE ON 02-05-2025", 0, 45),
    ("2025-05-04", "CARD PAYMENT TO WWW.OAKFIELD-TRADING ON 03-05-2025", 0, 60),
)


def test_sorted_under_sa103_headings():
    lines = B.sort_lines(LINES, "Pat Trader", "2025-04-01", "2026-03-31")
    def by(words):
        return next(r for r in lines if words in r["description"])
    assert len(lines) == 7                                                   # the March line is last year's
    assert by("ELECTRICAL WORK")["heading"] == "TURNOVER"          # 'electrical work' is the job, not a refund
    assert by("DRAWINGS")["heading"] == B.DRAWINGS
    assert by("PAT TRADER")["heading"] == B.CAPITAL
    t = B.totals(lines)
    assert t["COST_OF_SALES"] == 100.0                                     # 120 bought less 20 back
    assert t["TRAVEL"] == 45.0 and t["TURNOVER"] == 400.0


def test_the_accountants_choice_wins():
    lines = B.sort_lines(LINES, "Pat Trader", "2025-04-01", "2026-03-31")
    odd = next(r for r in lines if "OAKFIELD" in r["description"])
    again = B.sort_lines(LINES, "Pat Trader", "2025-04-01", "2026-03-31", {odd["key"]: "OFFICE"})
    chosen = next(r for r in again if r["key"] == odd["key"])
    assert chosen["heading"] == "OFFICE" and chosen["chosen"] and B.totals(again)["OFFICE"] == 60.0


def test_signs_of_new_income():
    from backend.app.sa.signals import find
    def l(on, d, i, o, heading=""):
        return {"on": on, "description": d, "in": i, "out": o, "heading": heading}
    lines = [l("2025-05-01", "FASTER PAYMENT FROM J BLOGGS REF ROOM", 400, 0), l("2025-06-01", "FASTER PAYMENT FROM J BLOGGS REF ROOM", 400, 0),
             l("2025-07-01", "FASTER PAYMENT FROM J BLOGGS REF ROOM", 400, 0),
             l("2025-08-10", "ACME TRADING LTD DIVIDEND", 2000, 0),
             l("2025-09-03", "TRANSFER TO MONEYBOX SAVINGS", 0, 250),
             l("2025-10-05", "CREDIT FROM GRANDMA SMITH", 6000, 0),
             l("2025-11-01", "TRANSFER FROM OWN ACCOUNT", 9000, 0, "TRANSFER")]
    got = {s["kind"]: s for s in find(lines, "Pat Trader", set())}
    assert set(got) == {"regular", "dividend", "savings", "large"}
    assert len(got["regular"]["lines"]) == 3 and got["regular"]["total"] == 1200.0
    assert got["large"]["question"].startswith("What was the £6,000.00 on 2025-10-05 from")
    # Interest already on the return: no savings question
    assert "savings" not in {s["kind"] for s in find(lines, "Pat Trader", {"SAVINGS"})}


def test_money_in_that_is_not_takings():
    from backend.app.sa.books import BARE_TRANSFER, CARD_REFUND, NOT_TRADE_IN
    assert NOT_TRADE_IN.search("BANK GIRO CREDIT REF NR926857C DWP CA, 0000003026469488")
    assert NOT_TRADE_IN.search("BANK GIRO CREDIT REF WCC COUNTY FUND, 70132 CLIENT")
    assert not NOT_TRADE_IN.search("FASTER PAYMENTS RECEIPT REF.JOB COMPENSATION FROM A CUSTOMER")
    assert CARD_REFUND.search("CREDIT FROM MARKS&SPENCER PLC ON 04-01-2026") and BARE_TRANSFER.match("Transfer")


def test_rent_in_is_property_not_takings():
    lines = B.sort_lines(account(
        ("2025-07-01", "Rent for the month 01/07/2025 to 31/07/2025 - Mr J Tenant", 1000, 0),
        ("2025-07-31", "INV.121 SWEET LET LIMITED", 862.5, 0)), "Kay Writer", "2025-04-06", "2026-04-05")
    by = {l["description"][:4]: l for l in lines}
    assert by["Rent"]["heading"] == B.NOT_TRADE and "property" in by["Rent"]["how"]
    assert by["INV."]["heading"] == "TURNOVER"          # 'Let' in a customer's name is not rent


def test_the_clients_own_sheet_is_not_counted_twice():
    bank = Account(lines=[L("2025-07-31", "BROWN AND CO, INVOICE 121", 862.5, 0, 1862.5)], opening=1000.0)
    sheet_line = L("2025-07-30", "Inv.121 Brown & Co", 862.5, 0, None)
    sheet_line.no_balance = True                        # from a page with no balances (the client's own sheet)
    other = L("2025-08-05", "Inv.122 Someone", 300.0, 0, None)
    other.no_balance = True                             # not on the bank: kept
    sheet = Account(lines=[sheet_line, other], opening=None)
    lines = B.sort_lines([("1", "Bank", bank), ("1", "Bank", sheet)], "Kay Writer", "2025-04-06", "2026-04-05")
    assert sorted(l["in"] for l in lines) == [300.0, 862.5]


def test_rent_paid_over_by_the_agent_is_not_takings():
    from datetime import date
    lines = B.sort_lines(account(("2025-08-04", "FASTER PAYMENTS RECEIPT FROM AGENT LETTINGS", 794.50, 0),
                                 ("2025-08-05", "FASTER PAYMENTS RECEIPT FROM AGENT LETTINGS", 862.50, 0)),
                         "Kay Writer", "2025-04-06", "2026-04-05", None, [(date(2025, 8, 1), 794.50)])
    by = {l["in"]: l for l in lines}
    assert by[794.5]["heading"] == B.NOT_TRADE and "paid over" in by[794.5]["how"]
    assert by[862.5]["heading"] == "TURNOVER"                 # her own invoice to the same agent stays takings


def test_wages_from_the_employer_and_student_finance_are_not_takings():
    lines = B.sort_lines(account(("2025-05-28", "BANK CREDIT KODAK ALARIS LTD SALARY MAY", 2400.0, 0),
                                 ("2025-06-28", "BACS KODAK ALARIS", 2400.0, 0),
                                 ("2025-09-15", "SLC DISBURSEMENTS", 1385.0, 0),
                                 ("2025-07-01", "FASTER PAYMENTS RECEIPT FROM ACME CONSULTING", 3000.0, 0)),
                         "Wes Writer", "2025-04-06", "2026-04-05", None, None, ["GB11-Kodak Alaris Limited"])
    heads = {l["description"][:14]: l["heading"] for l in lines}
    assert heads["BACS KODAK ALA"] == B.NOT_TRADE and heads["SLC DISBURSEME"] == B.NOT_TRADE
    assert heads["FASTER PAYMENT"] == "TURNOVER"


def test_generic_business_names_are_not_context():
    from backend.app.sa.books import GENERIC_NAME
    assert GENERIC_NAME.match("Trade") and GENERIC_NAME.match("Self-employment") and not GENERIC_NAME.match("The Beauty Lounge")


def test_a_platform_payout_is_takings_not_a_refund():
    # A seller pays eBay its fees and eBay pays over the sales: the payout is takings; a refund stays a refund
    lines = B.sort_lines(account(
        ("2025-06-01", "CARD PAYMENT TO EBAY O*FEES ON 31-05-2025", 0, 120),
        ("2025-06-03", "EBAY Commerce UK Ltd / ref: P*12345", 3500, 0),
        ("2025-06-05", "EBAY REFUND / ref: P*999", 12, 0)), "Pat Seller", "2025-04-06", "2026-04-05")
    by = {l["description"][:9]: l for l in lines}
    assert by["EBAY Comm"]["heading"] == "TURNOVER" and "selling platform" in by["EBAY Comm"]["how"]
    assert by["EBAY REFU"]["heading"] != "TURNOVER"


def test_the_balance_sheet_agrees_with_the_bank(monkeypatch):
    # A trade's small balance sheet (made-up lines): opening + profit - drawings = the bank balance at the end
    from types import SimpleNamespace as N
    from backend.app.sa import balance_sheet as BS
    acct = Account(lines=[L("2025-04-10", "FROM A CUSTOMER", 1000, 0, 1100.0), L("2025-05-01", "CARD SCREWFIX", 0, 200, 900.0),
                          L("2025-05-02", "TO P TEST DRAWINGS", 0, 300, 600.0)], opening=100.0)
    monkeypatch.setattr(B, "accounts", lambda db, job: [("1234", "Bank", acct)])
    monkeypatch.setattr(B, "view", lambda db, job, biz: {"lines": [], "totals": [
        {"heading": "TURNOVER", "amount": 1000.0}, {"heading": "COST_OF_SALES", "amount": 200.0},
        {"heading": "DRAWINGS", "amount": 300.0}]})
    r = BS.build(None, N(tax_year="2025-26"), N(period_start=None, period_end=None))
    assert r["capital"]["opening"] == 100.0 and r["capital"]["profit"] == 800.0 and r["capital"]["closing"] == 600.0
    assert r["net_assets"] == 600.0 and r["balances"] and r["notes"] == []


def test_a_car_bought_with_no_other_rule_is_left_to_the_accountant():
    # No rule fits a card payment to a car dealer: it was left unsorted, then the AI sorted the car into travel
    lines = B.sort_lines(account(("2024-08-14", "3880 13AUG24 , DEALER A CAR SALES , LTD , TOWN GB", 0, 11800)),
                         "Pat Trader", "2024-04-06", "2025-04-05")
    assert lines[0]["heading"] == "ASSET" and B.CAPITAL_PURCHASE in lines[0]["how"] and B.not_for_ai(lines[0])


def test_a_card_paid_off_with_no_card_statements_waits_for_them():
    # No card statements sent (made-up lines): the payment is not a cost, and the AI is not asked to make it one
    lines = B.sort_lines(account(("2024-07-08", "AMERICAN EXP 3773 PB9923******17790", 0, 9060.39),
                                 ("2024-04-22", "BP HSBC PREMIER543458 543458******8999", 0, 6534.0)),
                         "Pat Trader", "2024-04-06", "2025-04-05")
    assert all(l["heading"] == "UNSORTED" and B.CARD_UNSENT in l["how"] and B.not_for_ai(l) for l in lines)


def test_several_payments_from_a_company_with_no_trade_are_asked():
    from backend.app.sa.signals import find
    def l(on, d, i):
        return {"on": on, "description": d, "in": i, "out": 0, "heading": ""}
    lines = [l("2024-05-10", "ACME HOMECARE LIMITED PAYMENT", 145.69), l("2024-06-10", "ACME HOMECARE LIMITED PAYMENT", 1227.54),
             l("2024-07-10", "ACME HOMECARE LIMITED PAYMENT", 2184.26),
             l("2024-05-28", "BIGCO STORES LIMITED SALARY", 2000), l("2024-06-28", "BIGCO STORES LIMITED SALARY", 2000),
             l("2024-07-28", "BIGCO STORES LIMITED SALARY", 2000),
             l("2024-08-01", "PAYMENT FROM EMPLOYERCO LTD", 900), l("2024-09-01", "PAYMENT FROM EMPLOYERCO LTD", 900),
             l("2024-10-01", "PAYMENT FROM EMPLOYERCO LTD", 900)]
    got = [s for s in find(lines, "Pat Example", set(), ["Employerco Limited"]) if s["kind"] == "company"]
    assert len(got) == 1 and got[0]["total"] == 3557.49 and "ACME" in got[0]["lines"][0]["description"]
    # With a trade on the return a company paying in is a customer: not asked here
    assert not [s for s in find(lines, "Pat Example", {"SELF_EMPLOYMENT"}) if s["kind"] == "company"]


def test_vat_refund_and_a_loan_paid_in_are_not_takings():
    # Money in: a VAT refund is not income (figures net of VAT); a loan received is not income
    lines = B.sort_lines(account(("2024-09-02", "HMRC VAT REPAYMENT 123456789", 1450.0, 0),
                                 ("2024-10-01", "FUNDING CIRCLE LOAN ADVANCE", 10000.0, 0)),
                         "Pat Trader", "2024-04-06", "2025-04-05")
    heads = {l["description"][:12]: l["heading"] for l in lines}
    assert heads["HMRC VAT REP"] == B.VAT and heads["FUNDING CIRC"] == B.LOAN_IN
    assert all(l["heading"] in B.OUTSIDE for l in lines)
