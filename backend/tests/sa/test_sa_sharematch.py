"""Share matching (TCGA s104, s105, s106A; CG51560), made-up trades; no database."""

from types import SimpleNamespace as N

from backend.app.sa.sharematch import match


def t(on, side, qty, amount):
    return N(on=on, side=side, quantity=qty, amount=amount)


def test_pool_average_cost():
    m = match([t("2020-01-10", "BUY", 1000, 4000), t("2022-05-01", "BUY", 500, 3500), t("2025-09-01", "SELL", 600, 6000)])
    s = m["sales"][0]
    # pool 1,500 shares for £7,500: 600 cost £3,000
    assert (s["cost"], s["gain"], s["parts"][0]["rule"]) == (3000, 3000, "section 104 pool")
    assert m["pool"] == {"qty": 900, "cost": 4500}


def test_same_day_then_30_days_then_pool():
    m = match([t("2020-01-10", "POOL", 1000, 2000),
               t("2025-09-01", "SELL", 500, 5000), t("2025-09-01", "BUY", 100, 900),    # same day
               t("2025-09-20", "BUY", 200, 1600),                                        # bed and breakfast
               t("2025-11-01", "BUY", 300, 3000)])                                       # after 30 days: the pool
    s = m["sales"][0]
    assert [(p["rule"], p["qty"], p["cost"]) for p in s["parts"]] == [("same day", 100, 900), ("30 days", 200, 1600),
                                                                        ("section 104 pool", 200, 400)]
    assert (s["cost"], s["gain"]) == (2900, 2100) and m["pool"] == {"qty": 1100, "cost": 4600}


def test_same_day_before_an_earlier_sales_30_days():
    m = match([t("2020-01-10", "POOL", 1000, 1000), t("2025-09-01", "SELL", 100, 500),
               t("2025-09-05", "SELL", 100, 500), t("2025-09-05", "BUY", 100, 400)])
    first, second = m["sales"]
    assert second["parts"][0]["rule"] == "same day" and first["parts"][0]["rule"] == "section 104 pool"


def test_more_sold_than_held():
    m = match([t("2025-05-01", "BUY", 10, 100), t("2025-06-01", "SELL", 15, 300)])
    assert m["issues"] and m["sales"][0]["cost"] == 100
