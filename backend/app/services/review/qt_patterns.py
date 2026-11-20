"""Query trigger tests on patterns and ratios: missing words or balances, shares of sales, spikes and margin swings,
regular payees, missing months, stock, debtor and stock days, the main customer, limited cost trader, investment
property."""

import re
from collections import defaultdict
from typing import Optional


from backend.app.services.sop.common import year_months
from backend.app.services.review.qt_common import Ctx, Hit, SALES_SECTIONS, _has_balance, _matching, _money, _payee, test



@test("absent_words")
def absent_words(ctx: Ctx, p) -> Optional[Hit]:
    """Nothing in the ledger matches the words (no licence, insurance or levy cost), when the business has some
    activity: sales over a minimum (and payroll when the query is about staff)."""
    if ctx.sales < p.get("min_sales", 10000):
        return None
    if p.get("needs_payroll") and not any(3000 <= k <= 3015 and abs(v) >= 1 for k, v in ctx.bal.items()):
        return None
    if p.get("min_payroll"):          # the pay bill (staff costs) has to be at least this much
        pay = sum(v for k, v in ctx.bal.items() if ctx.section(k) == "Employee costs" or 3000 <= k <= 3015)
        if pay < p["min_payroll"]:
            return None
    words = re.compile(p["words"], re.I)
    if any(words.search(f"{l.description} {l.account}") for l in ctx.lines) or \
            any(words.search(t.raw_account_name or "") for t in ctx.tb_records):
        return None
    return Hit(p["title"], "No ledger line or account mentions it.", 0.0)


@test("absent_balance")
def absent_balance(ctx: Ctx, p) -> Optional[Hit]:
    """No balance on the accounts the query expects (accrued income, WIP...), for a business with sales."""
    if ctx.sales < p.get("min_sales", 10000):
        return None
    if _has_balance(ctx, p.get("codes", ()), p.get("sections", ()), p.get("names", "")):
        return None
    return Hit(p["title"], "No account in the trial balance holds it.", 0.0)


@test("share_of_sales")
def share_of_sales(ctx: Ctx, p) -> Optional[Hit]:
    """Lines matching the words (or accounts in sections) as a share of sales, outside the expected band."""
    if ctx.sales < 10000:
        return None
    if p.get("sections"):
        total = sum(v for k, v in ctx.bal.items() if ctx.section(k) in p["sections"])
    else:
        total = sum(l.credit - l.debit if p.get("side") == "in" else l.debit - l.credit for l in _matching(ctx, p))
    if p.get("skip_zero") and abs(total) < 1:
        return None          # nothing found at all: the costs may sit under other names
    share = total / ctx.sales * 100
    low, high = p.get("low", 0), p.get("high", 1000)
    if low <= share <= high:
        return None
    return Hit(p["title"].format(share=f"{share:.0f}%", total=_money(total), sales=_money(ctx.sales)),
               f"{_money(total)} against sales of {_money(ctx.sales)} ({share:.1f}%); expected "
               + (f"at least {low}%." if high >= 1000 else f"{low}% to {high}%."), abs(total))


@test("last_month_spike")
def last_month_spike(ctx: Ctx, p) -> Optional[Hit]:
    """The year's last month well above the monthly average (stock or materials bought before the year end)."""
    months = year_months(ctx.engagement.period_end_date)
    by_month = defaultdict(float)
    for l in ctx.lines:
        if ctx.section(l.code) in p.get("sections", ["Cost of sales"]):
            by_month[(l.when.year, l.when.month)] += l.debit - l.credit
    series = [by_month.get((m.year, m.month), 0.0) for m in months]
    avg = sum(series[:-1]) / 11
    if avg < 500 or series[-1] < p.get("times", 1.5) * avg:
        return None
    return Hit(p["title"].format(last=_money(series[-1]), avg=_money(avg)),
               f"{months[-1]:%b %Y}: {_money(series[-1])} against {_money(avg)} a month before.", series[-1] - avg)


@test("monthly_margin_swing")
def monthly_margin_swing(ctx: Ctx, p) -> Optional[Hit]:
    """Monthly gross margin more than X points away from the year's."""
    months = year_months(ctx.engagement.period_end_date)
    sales, cost = defaultdict(float), defaultdict(float)
    for l in ctx.lines:
        key = (l.when.year, l.when.month)
        if ctx.section(l.code) in SALES_SECTIONS:
            sales[key] += l.credit - l.debit
        elif ctx.section(l.code) == "Cost of sales":
            cost[key] += l.debit - l.credit
    total_sales = sum(sales.values())
    if total_sales < 10000:
        return None
    year_gp = (total_sales - sum(cost.values())) / total_sales * 100
    points, odd = p.get("points", 15), []
    for m in months:
        k = (m.year, m.month)
        if sales.get(k, 0) > total_sales / 24:
            gp = (sales[k] - cost.get(k, 0)) / sales[k] * 100
            if abs(gp - year_gp) > points:
                odd.append(f"{m:%b %Y}: {gp:.0f}%")
    if not odd:
        return None
    return Hit(f"Gross margin swings in {len(odd)} month(s) against {year_gp:.0f}% for the year",
               "; ".join(odd[:8]) + ". Costs may be in the wrong month (cut-off) or stock not counted.", 0.0)


@test("regular_payee")
def regular_payee(ctx: Ctx, p) -> Optional[Hit]:
    """The same payee among the matching lines paid in most months (a 'subcontractor' working like an employee)."""
    months = defaultdict(set)
    totals = defaultdict(float)
    for l in _matching(ctx, p):
        name = _payee(l)
        if name:
            months[name].add((l.when.year, l.when.month))
            totals[name] += l.debit - l.credit
    regular = [(n, len(m), totals[n]) for n, m in months.items()
               if len(m) >= p.get("months", 7) and totals[n] >= p.get("payee_min", 0)]
    if not regular:
        return None
    regular.sort(key=lambda x: -x[2])
    return Hit(p["title"].format(n=len(regular)),
               "; ".join(f"{n}: paid in {k} months, {_money(t)}" for n, k, t in regular[:6]), sum(t for _, _, t in regular))


@test("months_without")
def months_without(ctx: Ctx, p) -> Optional[Hit]:
    """Months of the year with none of the matching lines, when the others have them (CIS nil returns)."""
    found = {(l.when.year, l.when.month) for l in _matching(ctx, p)}
    if len(found) < 3:
        return None
    gaps = [m for m in year_months(ctx.engagement.period_end_date) if (m.year, m.month) not in found]
    if not gaps:
        return None
    return Hit(p["title"].format(n=len(gaps)), "Months: " + ", ".join(f"{m:%b %Y}" for m in gaps), 0.0)


@test("stock_unchanged")
def stock_unchanged(ctx: Ctx, p) -> Optional[Hit]:
    """Closing stock nil, or the same as last year's."""
    rows = [t for t in ctx.tb_records if ctx.section(t.std_code) == "Stock"]
    closing = sum(float(t.net_amount or 0) for t in rows)
    opening = sum(float(t.opening_amount or 0) for t in rows if t.opening_amount is not None)
    if ctx.sales < 10000:
        return None
    if abs(closing) < 1:
        return Hit("No closing stock in the books", "The stock accounts are nil at the year end.", 0.0)
    if any(t.opening_amount is not None for t in rows) and abs(closing - opening) < 1:
        return Hit(f"Closing stock {_money(closing)} is the same as last year's", "Not counted this year?", closing)
    return None


@test("sales_present")
def sales_present(ctx: Ctx, p) -> Optional[Hit]:
    if ctx.sales < p.get("min_sales", 1000):
        return None
    return Hit(p["title"].format(sales=_money(ctx.sales)), f"Sales for the year {_money(ctx.sales)}.", 0.0)


@test("debtors_vs_quarter")
def debtors_vs_quarter(ctx: Ctx, p) -> Optional[Hit]:
    """Trade debtors large against a quarter's sales (invoice-based VAT paid on money not yet received)."""
    if not (ctx.record.get("vat") or {}).get("registered") or ctx.sales < 10000:
        return None
    debtors = sum(v for k, v in ctx.bal.items() if k == 4400)
    quarter = ctx.sales / 4
    if debtors < p.get("share", 0.5) * quarter:
        return None
    return Hit(f"Trade debtors {_money(debtors)} are {debtors / quarter * 100:.0f}% of a quarter's sales",
               "With invoice-based VAT, VAT is paid on these before the money comes in: is cash accounting better?", debtors)


@test("single_sales_account")
def single_sales_account(ctx: Ctx, p) -> Optional[Hit]:
    if not (ctx.record.get("vat") or {}).get("registered") or ctx.sales < 10000:
        return None
    accounts = [t for t in ctx.tb_records if ctx.section(t.std_code) in SALES_SECTIONS and abs(float(t.net_amount or 0)) >= 1]
    if len(accounts) != 1:
        return None
    return Hit(p["title"], f"One sales account: {accounts[0].raw_account_name}.", ctx.sales)


@test("main_customer")
def main_customer(ctx: Ctx, p) -> Optional[Hit]:
    """Most of the income from one customer (a personal service company: IR35)."""
    income = defaultdict(float)
    for l in ctx.lines:
        if ctx.section(l.code) in SALES_SECTIONS and l.credit > 0:
            name = _payee(l)
            if name:
                income[name] += l.credit - l.debit
    total = sum(income.values())
    if total < p.get("min_sales", 20000) or not income:
        return None
    name, amount = max(income.items(), key=lambda x: x[1])
    share = amount / total * 100
    if share < p.get("share", 80):
        return None
    return Hit(p["title"].format(name=name.title(), share=f"{share:.0f}%"),
               f"{name.title()}: {_money(amount)} of {_money(total)} income ({share:.0f}%).", amount)


@test("debtor_days")
def debtor_days(ctx: Ctx, p) -> Optional[Hit]:
    """Debtors plus unbilled work, in days of sales, over the norm."""
    if ctx.sales < 10000:
        return None
    owed = sum(v for k, v in ctx.bal.items() if k == 4400 or ctx.section(k) == "Prepayments and accrued income" and "accrued" in ctx.name(k).lower())
    days = owed / ctx.sales * 365
    if days <= p.get("days", 90):
        return None
    return Hit(f"Debtors and unbilled work are {days:.0f} days of sales ({_money(owed)})",
               f"{_money(owed)} owed against sales of {_money(ctx.sales)}: are all the debts collectable?", owed)


@test("limited_cost_trader")
def limited_cost_trader(ctx: Ctx, p) -> Optional[Hit]:
    """Flat Rate Scheme with goods under 2% of turnover (or £1,000 a year): the 16.5% limited cost trader rate."""
    scheme = str((ctx.record.get("vat") or {}).get("scheme") or "").upper()
    if "FLAT" not in scheme or ctx.sales < 10000:
        return None
    goods = sum(v for k, v in ctx.bal.items() if ctx.section(k) == "Cost of sales")
    if goods >= max(0.02 * ctx.sales, 1000):
        return None
    return Hit(f"Flat Rate Scheme and goods of only {_money(goods)}: the 16.5% limited cost trader rate applies",
               f"Goods {_money(goods)} against turnover {_money(ctx.sales)} (under 2% or £1,000).", ctx.sales * 0.165)


@test("investment_property_at_cost")
def investment_property_at_cost(ctx: Ctx, p) -> Optional[Hit]:
    """FRS 102: investment property is held at fair value. Cost on the books and no revaluation this year."""
    framework = str((ctx.record.get("client") or {}).get("framework") or "").upper()
    if "105" in framework:
        return None
    held = sum(v for k, v in ctx.bal.items() if 4160 <= k <= 4167)
    if held < 1000:
        return None
    revalued = any(abs(ctx.bal.get(k, 0.0)) >= 1 for k in (4162, 7240)) or \
        any(l.code in (4162, 7240) for l in ctx.lines)
    if revalued:
        return None
    return Hit(f"Investment property of {_money(held)} and no fair value movement this year",
               "Under FRS 102 investment property is shown at fair value each year end.", held)


@test("monthly_swing")
def monthly_swing(ctx: Ctx, p) -> Optional[Hit]:
    """Months where the matching lines (fuel, energy...) are far from the year's monthly average."""
    by_month = defaultdict(float)
    for l in _matching(ctx, p):
        by_month[(l.when.year, l.when.month)] += abs(l.debit - l.credit)
    months = year_months(ctx.engagement.period_end_date)
    series = [by_month.get((m.year, m.month), 0.0) for m in months]
    avg = sum(series) / 12
    if avg < p.get("min_month", 200):
        return None
    share = p.get("share", 0.6)
    odd = [f"{m:%b %Y}: {_money(v)}" for m, v in zip(months, series) if abs(v - avg) > share * avg]
    if len(odd) < p.get("months", 2):
        return None
    return Hit(p["title"].format(n=len(odd), avg=_money(avg)), "; ".join(odd[:8]) + f" (average {_money(avg)} a month).", 0.0)


@test("one_account_in_section")
def one_account_in_section(ctx: Ctx, p) -> Optional[Hit]:
    """Only one account holds the section's balance (one 'Stock' line for a manufacturer)."""
    rows = [t for t in ctx.tb_records if ctx.section(t.std_code) in p["sections"] and abs(float(t.net_amount or 0)) >= 1]
    total = sum(float(t.net_amount or 0) for t in rows)
    if len(rows) != 1 or total < p.get("min", 1000):
        return None
    return Hit(p["title"].format(total=_money(total), name=rows[0].raw_account_name),
               f"One account: {rows[0].raw_account_name} {_money(total)}.", total)


@test("stock_days")
def stock_days(ctx: Ctx, p) -> Optional[Hit]:
    """Closing stock in days of cost of sales: slow-moving or obsolete stock when it is high."""
    stock = sum(v for k, v in ctx.bal.items() if ctx.section(k) == "Stock")
    cost = sum(v for k, v in ctx.bal.items() if ctx.section(k) == "Cost of sales")
    if stock < 1000 or cost < 1000:
        return None
    days = stock / cost * 365
    if days <= p.get("days", 180):
        return None
    return Hit(f"Closing stock {_money(stock)} is {days:.0f} days of cost of sales",
               f"Stock {_money(stock)} against cost of sales {_money(cost)} a year: any slow-moving or obsolete items to write down?", stock)
