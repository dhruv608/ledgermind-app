"""Tests for industry red flags that the general tests cannot do:

  margin_vs_last_year  gross margin this year against last year's (from last year's balances: the job in the app, its
                       final WP or the filed TB); a move of more points than the rule's limit is a question (restaurants,
                       retail, recruitment: analytical review)
  framework_is         the accounts framework chosen at setup is one the industry must not use (a charity on FRS 105:
                       charitable companies follow the Charities SORP, FRS 105 is not available to them)"""

from typing import Any, Dict, Optional

from backend.app.services.review.qt_common import SALES_SECTIONS, Ctx, Hit, _money, test

COST_OF_SALES = "Cost of sales"


def _margin(sales: float, costs: float) -> Optional[float]:
    return (sales - costs) / sales * 100 if sales > 0 else None


@test("margin_vs_last_year")
def margin_vs_last_year(ctx: Ctx, p: Dict[str, Any]) -> Optional[Hit]:
    from backend.app.services.review.last_year import prior_balances_by_code
    sales = ctx.sales
    costs = sum(v for k, v in ctx.bal.items() if ctx.section(k) == COST_OF_SALES)
    if sales < p.get("min_sales", 10000) or costs <= 0:
        return None
    try:
        last = prior_balances_by_code(ctx.engagement, ctx.db) or {}
    except Exception:
        return None
    last_sales = -sum(v for k, v in last.items() if ctx.section(k) in SALES_SECTIONS)
    last_costs = sum(v for k, v in last.items() if ctx.section(k) == COST_OF_SALES)
    now, before = _margin(sales, costs), _margin(last_sales, last_costs)
    if now is None or before is None or last_costs <= 0:
        return None
    move = now - before
    if abs(move) < p.get("points", 10):
        return None
    return Hit(f"Gross margin {now:.1f}% this year against {before:.1f}% last year ({move:+.1f} points)",
               f"Sales {_money(sales)}, cost of sales {_money(costs)}; last year sales {_money(last_sales)}, cost of "
               f"sales {_money(last_costs)}. A change this size needs a reason (prices, suppliers, wastage, stock "
               f"count, sales or costs missing or in the wrong year).", abs(move))


@test("framework_is")
def framework_is(ctx: Ctx, p: Dict[str, Any]) -> Optional[Hit]:
    framework = ((ctx.record or {}).get("client") or {}).get("framework")
    if framework not in p.get("frameworks", []):
        return None
    return Hit(p.get("why", "Accounts framework not allowed for this industry"),
               f"The setup has {framework}. {p.get('why', '')}".strip(), 0.0)
