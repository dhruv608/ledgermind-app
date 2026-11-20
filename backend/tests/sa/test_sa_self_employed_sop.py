"""Self-employment rules (SA103S / SA103F): Class 2 on a loss (N5, S23), Class 4 exemptions (N4),
a loss claimed against other income with the s24A cap (N1, S22), transfers paired at any amount (Allocation rule 6),
and the £500 capital test (Allocation rule 4, S15). Figures only, no client data."""

from datetime import date
from types import SimpleNamespace as NS

from backend.app.sa.boxes import self_employment
from backend.app.sa.engine.calc import Income, calculate
from backend.app.sa.income import loss_claim


def test_a_loss_still_offers_voluntary_class2():
    c = calculate(Income(tax_year="2025-26", employment=20000, has_trade=True))
    assert c.class2_below_threshold and c.class2 == 0
    paid = calculate(Income(tax_year="2025-26", employment=20000, has_trade=True, class2_voluntary=True))
    assert paid.class2 == 182.0                                        # 52 weeks at £3.50


def test_no_trade_no_class2_point():
    assert not calculate(Income(tax_year="2025-26", employment=20000)).class2_below_threshold


def test_class4_exempt_over_state_pension_age():
    base = calculate(Income(tax_year="2025-26", self_employment=30000, has_trade=True))
    assert base.class4 > 0
    exempt = calculate(Income(tax_year="2025-26", self_employment=30000, has_trade=True, class4_exempt="PENSION_AGE"))
    assert exempt.class4 == 0 and exempt.class4_exempt == "PENSION_AGE"


def _trade(loss):
    b = {"loss_year": loss, "loss_current": 0.0, "loss_back": 0.0, "loss_cf": loss}
    return {"businesses": [b], "loss_year": loss, "loss_cf": loss}


def test_loss_against_other_income_this_year():
    inc, trade, notes = Income(tax_year="2025-26", employment=40000, has_trade=True), _trade(8000), []
    out = loss_claim(inc, trade, "CURRENT", notes)
    assert out["current"] == 8000 and inc.reliefs == 8000 and trade["loss_cf"] == 0
    assert trade["businesses"][0]["loss_current"] == 8000


def test_loss_claim_capped_at_50000_or_25_percent():
    inc, trade, notes = Income(tax_year="2025-26", employment=120000, has_trade=True), _trade(70000), []
    out = loss_claim(inc, trade, "CURRENT", notes)
    assert out["cap"] == 50000 and out["current"] == 50000 and trade["loss_cf"] == 20000
    inc2, trade2 = Income(tax_year="2025-26", employment=400000, has_trade=True), _trade(150000)
    assert loss_claim(inc2, trade2, "CURRENT", [])["current"] == 100000   # 25% of 400,000


def test_no_choice_carries_forward():
    inc, trade = Income(tax_year="2025-26", employment=40000), _trade(8000)
    assert loss_claim(inc, trade, "", [])["current"] == 0 and trade["loss_cf"] == 8000 and inc.reliefs == 0


def test_loss_and_nic_boxes_on_the_short_page():
    row ={"page": "SA103S", "name": "B", "adjusted_profit": -5000, "losses_used": 0, "taxable_profit": 0,
           "loss_current": 5000, "loss_back": 0, "loss_cf": 0, "cis_deducted": 0, "balancing_charges": 0,
           "trading_allowance": 1000, "income": 0, "headings": {"TURNOVER": {"amount": 0}, "OTHER_INCOME": {"amount": 0}}}
    pages = self_employment({"businesses": [row]}, {"class2": 182.0, "class4_exempt": "PENSION_AGE"})
    boxes = {r["box"]: r["value"] for r in pages[0]["rows"]}
    assert boxes["33"] == 5000 and boxes["36"] == "X" and boxes["37"] == "X" and "35" not in boxes


def test_a_small_transfer_pairs_only_when_the_bank_says_transfer():
    from backend.app.sa.books import own_transfer_pairs
    o = NS(money_out=120.0, money_in=0.0, when=date(2025, 6, 2), description="TRANSFER TO SAVINGS 1234")
    i = NS(money_out=0.0, money_in=120.0, when=date(2025, 6, 2), description="TRANSFER FROM CURRENT 5678")
    shop_out = NS(money_out=40.0, money_in=0.0, when=date(2025, 6, 3), description="AMAZON MARKETPLACE")
    shop_in = NS(money_out=0.0, money_in=40.0, when=date(2025, 6, 3), description="AMAZON MARKETPLACE REFUND")
    lines = [NS(line=x) for x in (o, i, shop_out, shop_in)]
    keep = {id(o): ("A", None), id(i): ("B", None), id(shop_out): ("A", None), id(shop_in): ("B", None)}
    assert own_transfer_pairs(lines, keep) == {id(o), id(i)}          # the shop's refund is not a transfer


def test_capital_test_words():
    from backend.app.sa.books import ASSET_SUPPLIER
    assert ASSET_SUPPLIER.search("SCREWFIX DIRECT") and ASSET_SUPPLIER.search("Machine Mart Ltd")
    assert not ASSET_SUPPLIER.search("TESCO STORES")
