"""UK property (SA105) totals and the finance cost credit, with made-up figures."""

from types import SimpleNamespace as N

import pytest

from backend.app.sa.engine.calc import Income, calculate
from backend.app.sa.property import one


def _items(*rows):
    return [N(heading=h, amount=a) for h, a in rows]


def test_joint_let_half_share_finance_costs_kept_apart():
    items = _items(*[("RENT", 780)] * 12, *[("RES_FINANCE", 389.42)] * 12, ("REPAIRS", 250), ("REPAIRS", 887.21),
                   ("PROFESSIONAL", 552), ("PROFESSIONAL", 65), ("RATES_INSURANCE", 264.03), ("CAPITAL", 3200))
    r = one(N(id=1, name="Let house", share=0.5, use_allowance=0), items)
    assert (r["rents"], r["expenses"], r["profit_whole"]) == (9360.0, 2018.24, 7341.76)
    assert (r["profit"], r["finance_costs"], r["capital"]) == (3670.88, 2336.52, 3200.0)


def test_finance_credit_all_relieved_and_nothing_carried():
    c = calculate(Income(tax_year="2025-26", employment=52000, property=3670.88, finance_costs=2336.52, tax_deducted=7915))
    assert c.reductions["finance_costs"] == pytest.approx(467.30)
    assert c.finance_costs_relieved == pytest.approx(2336.52)          # not 2,336.50 from 467.30 / 20%
    assert c.balance == pytest.approx(1318.05)


def test_finance_credit_nil_when_no_income_above_the_allowance():
    c = calculate(Income(tax_year="2025-26", property=3000, finance_costs=5000))
    assert c.finance_costs_relieved == 0 and "finance_costs" not in c.reductions


def _prop(**kw):
    base = dict(id=1, name="Flat", share=1, use_allowance=0, owner="SOLE", kind="RESIDENTIAL", own_home=None,
                rent_a_room=None, let_from=None, let_to=None, ended=None)
    return N(**{**base, **kw})


def test_commercial_interest_is_an_expense_and_company_left_out():
    r = one(_prop(kind="COMMERCIAL"), _items(("RENT", 20000), ("RES_FINANCE", 5000)))
    assert (r["headings"]["NONRES_FINANCE"], r["finance_costs"], r["profit"]) == (5000, 0, 15000)
    c = one(_prop(owner="COMPANY"), _items(("RENT", 20000)))
    assert (c["in_pool"], c["profit"]) == (False, 0) and "R-SA105-09" in c["notes"][0]


def test_rent_a_room_within_limit_and_above_it():
    low = one(_prop(own_home="ROOM"), _items(("RENT", 7000), ("OTHER", 500)))
    assert (low["in_pool"], low["profit"], low["rent_a_room_exempt"]) == (False, 0, 7000)
    shared = one(_prop(own_home="ROOM", owner="SPOUSE", share=0.5), _items(("RENT", 9000)))   # £4,500 each, limit £3,750
    assert [i["key"] for i in shared["issues"]] == ["rentaroom:1"]
    scheme = one(_prop(own_home="ROOM", rent_a_room="RENT_A_ROOM"), _items(("RENT", 9000), ("OTHER", 3000)))
    assert (scheme["profit"], scheme["rent_a_room_exempt"]) == (1500, 7500)
    actual = one(_prop(own_home="ROOM", rent_a_room="ACTUAL"), _items(("RENT", 9000), ("OTHER", 3000)))
    assert (actual["in_pool"], actual["profit"], actual["issues"]) == (True, 6000, [])


def test_form_17_sold_and_dates():
    r = one(_prop(owner="SPOUSE", share=0.7, let_to="2025-12-31", ended="SOLD"), _items(("RENT", 1000)))
    assert [i["key"] for i in r["issues"]] == ["form17:1", "sold:1"]
    new = one(_prop(let_from="2025-07-01"), [N(heading="RENT", amount=500, on="2025-06-01")])
    assert any("started" in n for n in new["notes"]) and any("outside the letting dates" in n for n in new["notes"])


def test_the_property_allowance_is_put_as_a_choice_when_costs_are_under_it():
    from backend.app.models.database import User  # noqa: F401  (the users table the job models point at)
    from backend.app.sa import property as P

    class Q(list):
        def filter(self, *a):
            return self

        def order_by(self, *a):
            return self

        def all(self):
            return list(self)

        def count(self):
            return len(self)

    def pool(items, use=0):
        prop = N(id=1, name="Let flat", share=1, use_allowance=use, owner="SOLE", kind="RESIDENTIAL", country=None,
                 losses_bf=0, finance_bf=0, foreign_tax=0)
        for i in items:
            i.property_id, i.on = 1, None
        db = N(query=lambda m: Q([prop] if m.__name__ == "SAProperty" else items if m.__name__ == "SAPropertyItem" else []))
        return P.pooled(db, N(id="j", tax_year="2024-25"))

    r = pool(_items(*[("RENT", 1300)] * 12))
    issue = [i for row in r["properties"] for i in row["issues"] if i["key"] == "allowance:pool"]
    assert r["profit"] == 15600 and issue and "14,600.00" in issue[0]["text"]          # asked, never applied by itself
    assert not [i for row in pool(_items(*[("RENT", 1300)] * 12, ("REPAIRS", 1500)))["properties"] for i in row["issues"]]
    assert pool(_items(*[("RENT", 1300)] * 12), use=1)["profit"] == 14600
    # Small mortgage interest does not rule the allowance out: expenses and finance costs together under £1,000
    # (rule I6); together over it, no suggestion
    small = pool(_items(*[("RENT", 1300)] * 12, ("REPAIRS", 300), ("RES_FINANCE", 400)))
    assert [i for row in small["properties"] for i in row["issues"] if i["key"] == "allowance:pool"]
    big = pool(_items(*[("RENT", 1300)] * 12, ("REPAIRS", 300), ("RES_FINANCE", 800)))
    assert not [i for row in big["properties"] for i in row["issues"] if i["key"] == "allowance:pool"]
