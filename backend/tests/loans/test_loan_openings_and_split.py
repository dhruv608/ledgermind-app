"""Loans whose last-year balance the TB keeps by code only (several lenders on one code), last year's working paper's
balance per lender, and the split within one year from the rate the ledger's monthly interest shows (FRS 102 20.62,
s4 P-004). Figures from two clients, made anonymous."""
from datetime import date
from types import SimpleNamespace as N

from openpyxl import Workbook

from backend.app.services.ingestion.last_year_adjustments import loans_carried_forward
from backend.app.services.review.last_year_openings import lender_unknown
from backend.app.services.review.loans_review import loan_openings_by_code
from backend.app.services.workbook.balance_tabs.loans import _capital_in_twelve, _monthly_rate, _share_last_year

A = lambda name, code=5001, opening=0.0, net=0.0: N(raw_account_name=name, std_code=code, opening_amount=opening,
                                                   net_amount=net)


def test_a_code_balance_naming_no_lender_is_not_guessed_onto_one():
    hp = [A("23112 - HP 2 - BT75 DSV"), A("2310 - PCP 1 - HN24 XRV")]
    assert lender_unknown("Hire purchase between 1 and 5 years", 5001, hp)
    banks = [A("5100 - Bank Loan/Iwoca", 5100), A("Funding Circle Loan-short term", 5100)]
    assert lender_unknown("Bank loans", 5100, banks)
    # The code's plain account takes it, a named lender takes its own, one lender takes all, other codes unchanged
    assert not lender_unknown("Bank loans", 5100, [A("5100 - 5100 Bank loans (Current liabilities)", 5100)] + banks)
    assert not lender_unknown("Funding Circle loan", 5500, [A("5402 Funding Circle Loan", 5500), A("Lloyds Loan", 5500)])
    assert not lender_unknown("Bank loans", 5100, [A("Funding Circle Loan", 5100)])
    assert not lender_unknown("Trade creditors", 5200, [A("Supplier A", 5200), A("Supplier B", 5200)])


def _paper():
    wb = Workbook()
    wb.active.title = "G4 - Bank Loan"                       # a lead: its total is no lender's
    wb.active.append(["Client"])
    wb.active.append(["Lender X loan", 13508.59])
    wb.active.append(["Balance C/Fwd.", 39956.58])
    ws = wb.create_sheet("G4.2-LLOYDS-BBL-8582")             # a lender's own tab
    for row in (["Client"], ["Year"], ["Bank loan - LLOYDS"], ["Opening balance", 5280],
                ["Closing balance as on 31.05.2025", 2640]):
        ws.append(row)
    ws = wb.create_sheet("Hire Purchase")                    # one column block per agreement
    ws.append(["Closing balance", None, 120070.01])          # the summary's own total
    ws.append(["Van agreement AB12 CDE", None, None, "Car agreement FG34 HIJ", None, None, "Truck HP KL56", None])
    ws.append(["Balance B/Fwd", 5000, None, "Balance B/Fwd", 9000, None, "Balance B/Fwd", 100])
    ws.append(["Closing balance", None, 4000.5, "Closing balance", None, 7000, "Closing balance", None, 0])
    ws = wb.create_sheet("G4-VAT")                           # another paper's numbering
    ws.append(["VAT"])
    ws.append(["Closing balance", 18628.29])
    return wb


def test_reads_each_lenders_balance_from_last_years_paper():
    assert loans_carried_forward(_paper()) == {"LLOYDS-BBL-8582": 2640.0, "Van agreement AB12 CDE": 4000.5,
                                               "Car agreement FG34 HIJ": 7000.0}


def _hp_lines():
    """A car HP: £38,525 drawn, £916.82 a month, the lender's interest charged to the account each month."""
    interest = [214.41, 210.5, 206.57, 202.62, 198.65, 194.65, 190.63, 186.59, 182.53]
    lines = [("24/12/2025", 0, 0, 0, 0, 0, 0, None, 38525.0)]
    for m, i in enumerate(interest, 1):
        lines.append((f"22/{m:02d}/2026", 0, 0, 0, 0, 0, 0, 916.82, None))
        lines.append((f"28/{m:02d}/2026", 0, 0, 0, 0, 0, 0, None, i))
    return lines


def test_split_from_the_rate_the_ledger_shows():
    rate = _monthly_rate(_hp_lines(), 916.82, date(2025, 9, 30))
    assert abs(rate - 0.005564) < 0.00001                     # 6.68% a year
    # The firm's schedule: £9,136.76 within one year of £32,070.77 owed
    assert abs(_capital_in_twelve(32070.77, 916.82, rate) - 9136.76) < 1.0
    assert _capital_in_twelve(500.0, 916.82, rate) == 500.0   # never more than owed
    flat = [(f"01/{m:02d}/2026", 0, 0, 0, 0, 0, 0, None, 50.0) for m in range(1, 7)]
    assert _monthly_rate(flat, 400.0, date(2025, 9, 30)) is None     # no fall: no rate, today's estimate stays


def test_last_years_paper_shares_the_code_balance_out():
    bf = A("Brought forward: Bank loans", 5500, opening=-40000.0, net=-40000.0)
    lloyds, fc, iwoca = A("5401 Lloyds Bank Loan", 5500), A("5402 Funding Circle Loan", 5500), A("Iwoca loan", 5500)
    opening_of = lambda t: float(t.opening_amount or 0.0)
    unallocated = {}
    shift, from_wp = _share_last_year({"LLOYDS-BBL-4201": 13508.59, "Funding Circle Loan": 23807.99},
                                      [bf, lloyds, fc, iwoca], opening_of, unallocated)
    assert shift[id(lloyds)] == -13508.59 and shift[id(fc)] == -23807.99 and id(iwoca) not in shift
    assert shift[id(bf)] == round(13508.59 + 23807.99, 2)   # what is left stays brought forward: £2,683.42
    assert from_wp[id(fc)] == ("Funding Circle Loan", 23807.99)
    # Never more than last year's TB holds
    shift, _ = _share_last_year({"Funding Circle Loan": 90000.0}, [bf, fc], opening_of, {})
    assert shift[id(fc)] == -40000.0 and shift[id(bf)] == 40000.0


def test_asks_for_each_lenders_balance_when_not_known():
    eng = N(id="e", profile=N(tax_inputs="{}"))
    tb = [A("Brought forward: Hire purchase between 1 and 5 years", 5001, opening=-181643.4, net=-181643.4),
          A("HP 2 - BT75 DSV", 5001), A("PCP 1 - HN24 XRV", 5000)]
    point = loan_openings_by_code(eng, tb)
    assert point[0].procedure_ref == "U-LOAN-007" and point[0].quantified_amount == 181643.4
    known = N(id="e", profile=N(tax_inputs='{"_last_year_wp": {"loans_cf": {"HP 2 BT75 DSV": 181643.4}}}'))
    assert loan_openings_by_code(known, tb) == []
