"""Figures by form and box (HMRC 2025-26 forms), made-up figures; no database."""

from types import SimpleNamespace as N

from backend.app.sa import boxes
from backend.app.sa.trade import one


def _biz(**kw):
    base = dict(id=1, name="Trade A", home_hours=0, home_months=0, car_miles=0, motorcycle_miles=0, capital_allowances=0,
                balancing_charges=0, use_trading_allowance=0, losses_bf=0, cis_deducted=0)
    base.update(kw)
    return N(**base)


def _item(heading, amount, disallowed=0):
    return N(heading=heading, amount=amount, disallowed=disallowed)


def _by_box(rows):
    return {r["box"]: r["value"] for r in rows}


def test_short_page_boxes():
    b = one(_biz(car_miles=1000, home_hours=60, home_months=12, cis_deducted=500, losses_bf=300),
            [_item("TURNOVER", 20000), _item("COST_OF_SALES", 5000), _item("SUBCONTRACTORS", 1000),
             _item("OFFICE", 300, 100), _item("PROFESSIONAL", 600), _item("FINANCE", 40), _item("LOAN_INTEREST", 60),
             _item("DEPRECIATION", 250)], "2025-26")
    page = boxes.self_employment({"businesses": [b]})[0]
    assert page["form"] == "SA103S"
    got = _by_box(page["rows"])
    # mileage 1,000 x 45p in box 12; use of home 12 x £18 in box 14; subcontractors with staff in box 13 (firm); depreciation never
    assert got["9"] == 20000 and got["11"] == 5000 and got["12"] == 450 and got["14"] == 216
    assert got["16"] == 600 and got["17"] == 100 and got["18"] == 200 and got["13"] == 1000 and "19" not in got
    assert got["20"] == 7566 and got["21"] == 12434
    assert got["28"] == b["adjusted_profit"] == 12434 and got["29"] == 300 and got["31"] == 12134 and got["38"] == 500


def test_trading_allowance_and_loss():
    b = one(_biz(use_trading_allowance=1), [_item("TURNOVER", 5400)], "2025-26")
    got = _by_box(boxes.self_employment({"businesses": [b]})[0]["rows"])
    assert got["10.1"] == 1000 and "20" not in got and got["28"] == 4400 and got["31"] == 4400
    loss = one(_biz(), [_item("TURNOVER", 1000), _item("OTHER", 3000)], "2025-26")
    got = _by_box(boxes.self_employment({"businesses": [loss]})[0]["rows"])
    assert got["22"] == 2000 and got["32"] == 2000 and got["35"] == 2000 and "31" not in got


def test_full_page_disallowed_boxes():
    b = one(_biz(), [_item("TURNOVER", 120000), _item("TRAVEL", 4000, 1000), _item("DEPRECIATION", 800)], "2025-26")
    got = _by_box(boxes.self_employment({"businesses": [b]})[0]["rows"])
    assert got["15"] == 120000 and got["20"] == 4000 and got["35"] == 1000 and got["29"] == 800 and got["44"] == 800
    assert got["31"] == 4800 and got["46"] == 1800 and got["47"] == 115200 and got["64"] == 117000 and got["76"] == 117000


def test_employment_and_main_return():
    line = lambda source, kind, amount, **kw: N(source=source, kind=kind, amount=amount, include=kw.get("include", 1),
                                                 share=kw.get("share", 1), tax_paid=kw.get("tax", 0), label=kw.get("label", ""),
                                                 note=kw.get("note"), doc_id=kw.get("doc"))
    lines = [line("EMPLOYMENT", "P60", 30000, tax=3486, label="Employer A", note="PAYE 123/AB456", doc=7),
             line("SAVINGS", "INTEREST", 900, share=0.5), line("SAVINGS", "ISA", 400),
             line("PENSIONS", "BENEFIT", 762.70, label="Jobseeker's Allowance"), line("PENSIONS", "STATE_PENSION", 11973),
             line("RELIEFS", "PENSION_RAS", 800), line("RELIEFS", "GIFT_AID", 100),
             line("DIVIDENDS", "DIVIDEND", 5000, include=0)]
    emp = boxes.employment(lines)[0]
    assert _by_box(emp["rows"]) == {"1": 30000, "2": 3486, "4": "123/AB456", "5": "Employer A"} and emp["rows"][0]["doc_id"] == 7
    tr3, tr4 = boxes.main_return(lines)
    assert _by_box(tr3["rows"]) == {"2": 450, "8": 11973, "15": 762.7}           # ISA and the left-out dividend not there
    assert _by_box(tr4["rows"]) == {"1": 1000, "5": 100}


def test_property_page():
    prop = {"properties": [{"name": "1 Any Street", "share": 0.5}], "allowance": False, "allowance_used": 0,
            "boxes": {"RENT": 6000, "RATES_INSURANCE": 400, "REPAIRS": 600, "NONRES_FINANCE": 0, "PROFESSIONAL": 300,
                      "SERVICES": 0, "OTHER": 0, "DOMESTIC_ITEMS": 200, "RES_FINANCE": 2000, "CAPITAL": 0},
            "before_losses": 4500, "losses_used": 500, "profit": 4000, "loss_cf": 0, "finance_costs": 2300}
    page = boxes.property_page(prop)[0]
    assert _by_box(page["rows"]) == {"1": "1", "20": 6000, "24": 400, "25": 600, "27": 300, "36": 200, "38": 4500,
                                     "39": 500, "40": 4000, "44": 2000, "45": 300}
    assert page["note"] == "The person's share: 1 Any Street 50%"


def test_taxcalc_2025_26_self_employment_pages():
    """Two real TaxCalc 2025-26 self-employment summaries (figures only): every line and the net profit agree."""
    first = one(_biz(), [_item("TURNOVER", 26839), _item("COST_OF_SALES", 6517), _item("STAFF", 21), _item("TRAVEL", 1482),
                         _item("PREMISES", 684), _item("OFFICE", 634, 144), _item("FINANCE", 42), _item("PROFESSIONAL", 870),
                         _item("OTHER", -1)], "2025-26")
    got = _by_box(boxes.self_employment({"businesses": [first]})[0]["rows"])
    assert {k: got[k] for k in ("9", "11", "12", "13", "14", "16", "17", "18", "19", "20", "21", "31")} == {
        "9": 26839, "11": 6517, "12": 1482, "13": 21, "14": 684, "16": 870, "17": 42, "18": 490, "19": -1, "20": 10105,
        "21": 16734, "31": 16734}
    second = one(_biz(), [_item("TURNOVER", 8422), _item("TRAVEL", 3062), _item("PROFESSIONAL", 510), _item("OTHER", 540)], "2025-26")
    got = _by_box(boxes.self_employment({"businesses": [second]})[0]["rows"])
    assert (got["12"], got["16"], got["19"], got["20"], got["21"], got["31"]) == (3062, 510, 540, 4112, 4310, 4310)


def test_capital_allowances_by_kind():
    from backend.app.sa.allowances import for_business
    a = lambda id, kind, amount, private=0: N(id=id, kind=kind, description="", amount=amount, private_use=private)
    ca = for_business([a(1, "AIA", 3000), a(2, "MAIN", 10000, 0.25), a(3, "SPECIAL", 800), a(4, "ZEC", 20000)], "2025-26", False)
    got = [(l["kind"], l["allowance"], l["pool_cf"]) for l in ca["lines"]]
    # 18% of £10,000 less 25% private use; the £800 special pool is written off; the pool goes down by the full 18%
    assert got == [("AIA", 3000, 0), ("MAIN", 1350, 8200), ("SMALL", 800, 0), ("ZEC", 20000, 0)] and ca["total"] == 25150
    assert ca["issues"] == []
    assert for_business([a(1, "AIA", 3000)], "2025-26", True)["issues"][0].startswith("Cash basis")
    b = one(_biz(), [_item("TURNOVER", 60000)], "2025-26", ca)
    got = _by_box(boxes.self_employment({"businesses": [b]})[0]["rows"])
    assert (got["23"], got["24"], got["24.1"], got["25"], b["taxable_profit"]) == (3000, 800, 20000, 1350, 34850)
    big = one(_biz(), [_item("TURNOVER", 100000)], "2025-26", ca)
    got = _by_box(boxes.self_employment({"businesses": [big]})[0]["rows"])
    assert (got["49"], got["50"], got["51"], got["52.1"], got["57"]) == (3000, 1350, 800, 20000, 25150)
