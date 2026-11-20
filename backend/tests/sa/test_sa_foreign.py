"""Foreign income (SA106), made-up figures; no database."""

from types import SimpleNamespace as N

from backend.app.sa import foreign
from backend.app.sa.engine.calc import Income, calculate


def src(id=1, **kw):
    base = dict(id=id, country="USA", kind="DIVIDEND", payer=f"Payer {id}", amount=0, foreign_tax=0, share=1, claim=1,
                doc_id=None, note=None)
    return N(**{**base, **kw})


def test_pension_taxed_in_full_and_uk_only_treaty():
    # From 6 April 2017 a foreign pension is taxed on the full amount (ITEPA s575, EIM75500): no 10% exemption
    r = foreign.one(src(country="ZAF", kind="PENSION", amount=10000, foreign_tax=1000))
    assert (r["exempt"], r["taxable"], r["creditable"]) == (0, 10000, 0)
    assert [i["key"] for i in r["issues"]] == ["reclaim:1"] and "the end of February" in r["notes"][0]


def test_credit_is_the_lower_of_foreign_tax_and_uk_tax():
    inc = Income(employment=60000)
    rows = [foreign.one(src(amount=1000, foreign_tax=150))]          # no treaty row: a decision, credit as paid
    foreign.apply(inc, rows)
    assert inc.dividends == 1000
    assert foreign.credits(inc, rows) == 150                          # UK tax on it: £500 over the allowance x 33.75%
    # The UK-USA treaty row (Art 10, at most 15%) sets the credit, so no 'check the treaty rate' note
    assert rows[0]["uk_tax"] == 168.75 and rows[0]["issues"] == [] and "Art 10" in rows[0]["treaty"]
    calc = calculate(inc)
    assert calc.reductions["foreign_tax_credit"] == 150


def test_no_uk_tax_no_credit_and_deduction_instead():
    inc = Income(employment=20000)
    # Spain: no row in the treaty table (Ireland's interest is now the UK's alone, Art 12)
    rows = [foreign.one(src(country="ESP", kind="INTEREST", amount=1000, foreign_tax=200))]
    foreign.apply(inc, rows)
    assert foreign.credits(inc, rows) == 0                            # covered by the personal savings allowance
    assert "not relieved" in rows[0]["notes"][-1]
    ded = foreign.one(src(kind="INTEREST", amount=1000, foreign_tax=200, claim=0))
    assert (ded["taxable"], ded["creditable"]) == (800, 0)


def test_sa106_boxes():
    rows = [foreign.one(src(1, kind="INTEREST", country="IRL", amount=500)),
            foreign.one(src(2, amount=1000, foreign_tax=150)),
            foreign.one(src(3, country="ZAF", kind="PENSION", amount=10000))]
    rows[1]["credit"] = 150.0
    page = foreign.boxes(rows)[0]
    got = [(r["box"], r["value"]) for r in page["rows"]]
    assert got == [("2", 150.0), ("A-F", 500), ("4", 500), ("A-F", 1000), ("6", 1000), ("A-F", 10000), ("9", 10000)]


def test_overseas_property_page_and_credit_row():
    from backend.app.sa import boxes
    fp = {"properties": [{"name": "Villa", "share": 1}], "allowance": False, "allowance_used": 0,
          "boxes": {"RENT": 12000, "RATES_INSURANCE": 800, "REPAIRS": 1200, "NONRES_FINANCE": 0, "PROFESSIONAL": 1000,
                    "SERVICES": 0, "OTHER": 0, "DOMESTIC_ITEMS": 500, "RES_FINANCE": 3000, "CAPITAL": 0},
          "before_losses": 8500, "losses_used": 1500, "profit": 7000, "loss_cf": 0, "finance_costs": 3000,
          "countries": [{"country": "ESP", "profit": 8500, "foreign_tax": 1600}]}
    got = {r["box"]: r["value"] for r in boxes.foreign_property_page(fp)[0]["rows"]}
    assert got == {"14": 12000, "15": "1", "17": 3000, "18": 9000, "23": 500, "24": 8500, "24.1": 3000, "26": 1500,
                   "27": 7000, "28": 1600}
    row = foreign.property_row(fp["countries"][0])
    inc = Income(employment=40000, foreign=7000, finance_costs=3000)
    assert foreign.credits(inc, [row]) == row["credit"] and 0 < row["credit"] <= 1600
