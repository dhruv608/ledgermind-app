"""Last year's accruals and prepayments read item by item from last year's final WP, anonymous
figures; no database."""

from backend.app.services.ingestion import last_year_adjustments as L


def test_items_from_the_this_year_column_until_the_totals():
    rows = [["Example Ltd", None, "G6"], ["Year Ended 31 January 2025"], ["Accruals"], [None, 2025, 2024],
            ["Accountancy fees - Y.E_31.01.2024", 1200, 1200, "G6.1"], ["Interest on Example Loan", 1740.9],
            ["Old item gone", 0, 300], [None, 2940.9, 1500], ["Opening balance", 1500], ["Accountancy fees", 999]]
    assert L.items_of_tab(rows) == [("Accountancy fees - Y.E_31.01.2024", 1200.0), ("Interest on Example Loan", 1740.9)]
    assert L._year_end(rows).isoformat() == "2025-01-31"
    # Workings and the roll of the balance are not items
    assert L.items_of_tab([["Accruals", 2025, 2024], ["Accruals b/fwd", 500, 0], ["Rent", 800, 0], [None, 1300, 0]]) == [("Rent", 800.0)]


def test_cost_codes_from_the_name():
    pl = lambda c: 3000 <= c < 4000
    tb = [(3241, "Software subscriptions"), (3140, "Repairs and maintenance"), (5200, "Trade creditors")]
    assert L.cost_code("3303 Professional fees", tb, pl) == 3303
    assert L.cost_code("Accountancy fees - Y.E_31.01.2024", tb, pl) == 3301
    assert L.cost_code("Interest on Example Loan", tb, pl) == 3631
    assert L.cost_code("Council Rent", tb, pl) == 3100
    assert L.cost_code("Boiler repairs and maintenance", tb, pl) == 3140      # words shared with the TB name
    assert L.cost_code("Something else", tb, pl) is None
    lease = [(3215, "Hire and leasing of motor vehicles"), (3000, "Wages and salaries")]
    assert L.cost_code("Advance payment for leasing", lease, pl) == 3215          # 'payment' alone places nothing
    tie = [(3140, "Cleaning and maintenance"), (3150, "Window cleaning")]
    assert L.cost_code("Cleaning", tie, pl) is None                               # two accounts as good: not guessed


def test_references_deferred_income_and_more_words():
    rows = [["Prepayments", None, 2025, 2024], ["E4.1", "Example insurance", 2041.67, 0], ["Deferred rental income", None, 500, 0],
            [None, None, 2541.67, 0]]
    assert L.items_of_tab(rows) == [("Example insurance", 2041.67)]         # the name beside its WP reference
    pl = lambda c: 1000 <= c < 4000
    assert [L.cost_code(n, [], pl) for n in ("Sub - contractor cost", "HMRC - P11D", "Fair/Exhibition", "Accruals b/f")] ==         [3020, 3001, 3280, None]


def test_a_sub_account_name_used_under_two_parents_follows_its_parent():
    """QuickBooks 'Sub-Contractors:<name>' and 'Sales:<name>': the TB lists the name under both codes, so the parent decides."""
    from types import SimpleNamespace as N
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.sop.common import code_matcher
    tb = [N(std_code=0, raw_account_name="Sales"), N(std_code=0, raw_account_name="Mira"),
          N(std_code=1440, raw_account_name="Sub-Contractors"), N(std_code=1440, raw_account_name="Mira"),
          N(std_code=3260, raw_account_name="Insurance")]
    code_of = code_matcher(ChartLookup.gl_account_codes(tb))
    assert (code_of("Sub-Contractors:Mira"), code_of("Sales:Mira"), code_of("Insurance:Cyber")) == (1440, 0, 3260)


def test_director_claims_from_last_years_journals():
    """Use of home and salary credited to the director's loan are claims; a dividend or a reclass is not."""
    js = [{"lines": [(3100, 312.0, 0.0), (5400, 0.0, 312.0)], "why": "(Being rent (WFH) as per previous year)"},
          {"lines": [(3010, 12570.0, 0.0), (5400, 0.0, 12570.0)], "why": "(Being director's Salary recorded)"},
          {"lines": [(8011, 30000.0, 0.0), (5400, 0.0, 30000.0)], "why": "(Being dividend recorded)"},
          {"lines": [(3280, 80.0, 0.0), (3283, 0.0, 80.0)], "why": "(Being re-analysed)"}]
    assert [(k, a) for k, _w, a in L.director_claims(js)] == [("HOME", 312.0), ("SALARY", 12570.0)]
