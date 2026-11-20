"""Query trigger tests on the books: keywords in the lines, balances, the TB out of balance, suspense, abnormal
balances, sales swings, VAT and flat rate limits, deferred tax, round journals, the ledger against the aged lists,
loans without interest."""

import re
from collections import defaultdict
from typing import Any, Dict, Optional


from backend.app.services.sop.common import year_months
from backend.app.services.review.qt_common import Ctx, FLAT_RATE_LEAVE_THRESHOLD, Hit, SALES_SECTIONS, VAT_REGISTRATION_THRESHOLD, _balances_figures, _has_balance, _line, _lines_figures, _money, _where, test



@test("keyword_lines")
def keyword_lines(ctx: Ctx, p: Dict[str, Any]) -> Optional[Hit]:
    if p.get("needs_vat") and not (ctx.record.get("vat") or {}).get("registered"):
        return None
    words = re.compile(p["words"], re.I)
    exclude = re.compile(p["exclude"], re.I) if p.get("exclude") else None
    skip_accounts = re.compile(p["skip_accounts"], re.I) if p.get("skip_accounts") else None
    side, where = p.get("side", "any"), p.get("where", "any")
    found = []
    for l in ctx.lines:
        if max(l.debit, l.credit) < max(1, p.get("line_min", 1)):     # line_min: only lines of at least this much
            continue
        # The other side of each bank line is the account it went to: the bank's own line would count it twice
        # (money out = a debit on the cost, money in = a credit on the income or other account)
        if ctx.section(l.code) == "Cash at bank and in hand":
            continue
        if side == "out" and l.debit <= 0 or side == "in" and l.credit <= 0:
            continue
        text = f"{l.description} {l.account}"
        if not words.search(text) or (exclude and exclude.search(text)) or not _where(ctx, l, where):
            continue
        # Lines on an account that already says what they are (rent, hotels, fuel...) are not in question
        if skip_accounts and (skip_accounts.search(l.account or "") or skip_accounts.search(ctx.name(l.code))):
            continue
        found.append(l)
    total = round(sum(l.debit - l.credit for l in found), 2)
    if not found or abs(total) < p.get("min_total", 1.0):
        return None
    if p.get("unless_codes") or p.get("unless_sections") or p.get("unless_names"):
        if _has_balance(ctx, p.get("unless_codes", ()), p.get("unless_sections", ()), p.get("unless_names", "")):
            return None
    if p.get("unless_words"):
        other = re.compile(p["unless_words"], re.I)
        if any(other.search(f"{l.description} {l.account}") for l in ctx.lines):
            return None
    found.sort(key=lambda l: -abs(l.debit - l.credit))
    title = p["title"].format(n=len(found), total=_money(total))
    return Hit(title, f"{len(found)} ledger line(s), {_money(total)} in all.", abs(total), [_line(l) for l in found[:6]],
               _lines_figures(found))


@test("balance")
def balance(ctx: Ctx, p: Dict[str, Any]) -> Optional[Hit]:
    pat = re.compile(p["names"], re.I) if p.get("names") else None
    found = []
    for t in ctx.tb_records:
        if abs(float(t.net_amount or 0)) < p.get("min", 0.01) or (p.get("bs") and ctx.is_pl(t.std_code)):
            continue
        if p.get("exclude_names") and re.search(p["exclude_names"], t.raw_account_name or "", re.I):
            continue
        if t.std_code in p.get("codes", ()) or ctx.section(t.std_code) in p.get("sections", ()) or (pat and pat.search(t.raw_account_name or "")):
            found.append((t.raw_account_name, float(t.net_amount or 0)))
    if not found:
        return None
    if p.get("unless_codes") or p.get("unless_sections") or p.get("unless_names"):
        if _has_balance(ctx, p.get("unless_codes", ()), p.get("unless_sections", ()), p.get("unless_names", "")):
            return None
    total = round(sum(v for _, v in found), 2)
    return Hit(p["title"].format(n=len(found), total=_money(total)),
               "; ".join(f"{n}: {_money(v)}{' Cr' if v < 0 else ''}" for n, v in found[:8]), abs(total),
               figures=_balances_figures(found) if len(found) > 1 else None)


# ---------------------------------------------------------------------------------------------------------------
# Tests worked out from the figures
# ---------------------------------------------------------------------------------------------------------------
@test("tb_out_of_balance")
def tb_out_of_balance(ctx: Ctx, p) -> Optional[Hit]:
    diff = round(sum(float(t.net_amount or 0) for t in ctx.tb_records), 2)
    if abs(diff) >= 0.01:
        return Hit(f"The trial balance is out by {_money(diff)}", f"Debits less credits come to {_money(diff)}.", abs(diff))
    if not ctx.tb_records or not any(abs(float(t.net_amount or 0)) >= 0.01 for t in ctx.tb_records):
        return Hit("The trial balance has no balances — fix the TB import", "Every line in the trial balance has a zero net balance.", 0.0)
    return None


@test("suspense")
def suspense(ctx: Ctx, p) -> Optional[Hit]:
    pat = re.compile(r"suspense|clearing|unallocated|undeposited|ask (my )?accountant", re.I)
    found = [(t.raw_account_name, float(t.net_amount or 0)) for t in ctx.tb_records
             if abs(float(t.net_amount or 0)) >= 1 and not ctx.is_pl(t.std_code)
             and (pat.search(t.raw_account_name or "")
                  # an account not mapped yet waits on 9999 until it is checked: only a confirmed 9999 is suspense
                  or (t.std_code == 9999 and t.mapping_status not in ("NEEDS_REVIEW", "UNMAPPED", "AI_SUGGESTED")))]
    if not found:
        return None
    total = round(sum(abs(v) for _, v in found), 2)
    return Hit(f"Suspense or clearing balances of {_money(total)} to clear",
               "; ".join(f"{n}: {_money(v)}{' Cr' if v < 0 else ''}" for n, v in found), total,
               figures=_balances_figures(found) if len(found) > 1 else None)


@test("abnormal_balances")
def abnormal_balances(ctx: Ctx, p) -> Optional[Hit]:
    odd = []
    for t in ctx.tb_records:
        v, code, name = float(t.net_amount or 0), t.std_code, (t.std_name or "").lower()
        if abs(v) < 1 or code is None:
            continue
        sec = ctx.section(code)
        if code == 4400 and v < 0:
            odd.append(f"{t.raw_account_name}: trade debtors in credit {_money(v)}")
        elif code == 5200 and v > 0:
            odd.append(f"{t.raw_account_name}: trade creditors in debit {_money(v)}")
        elif sec == "Tangible assets" and "depreciation" in name and v > 0:
            odd.append(f"{t.raw_account_name}: depreciation in debit {_money(v)}")
        elif sec == "Tangible assets" and "depreciation" not in name and v < 0:
            odd.append(f"{t.raw_account_name}: asset cost in credit {_money(v)}")
        elif sec == "Cash at bank and in hand" and code == 4830 and v < 0:
            odd.append(f"{t.raw_account_name}: cash in hand in credit {_money(v)}")
    if not odd:
        return None
    return Hit(f"{len(odd)} balance(s) on the wrong side", "; ".join(odd[:8]), 0.0)


@test("monthly_sales_swing")
def monthly_sales_swing(ctx: Ctx, p) -> Optional[Hit]:
    """A month's sales more than X% away from the average of the 3 months before it."""
    months = year_months(ctx.engagement.period_end_date)
    by_month = defaultdict(float)
    for l in ctx.lines:
        if ctx.section(l.code) in SALES_SECTIONS:
            by_month[(l.when.year, l.when.month)] += l.credit - l.debit
    series = [round(by_month.get((m.year, m.month), 0.0), 2) for m in months]
    if sum(series) < 5000:
        return None
    share = p.get("share", 0.5)
    odd = []
    from backend.app.services.review.point_figures import row, table
    rows = []
    for i in range(3, 12):
        base = sum(series[i - 3:i]) / 3
        if base > 500 and abs(series[i] - base) > share * base:
            odd.append(f"{months[i]:%b %Y}: {_money(series[i])} against {_money(base)} on average before")
            rows.append(row(f"{months[i]:%b %Y}", series[i], base))
    if not odd:
        return None
    return Hit(f"Sales jump or drop in {len(odd)} month(s)", "; ".join(odd[:6]), 0.0,
               figures=table(["Month", "Sales", "Average of the 3 months before"], rows))


@test("vat_threshold")
def vat_threshold(ctx: Ctx, p) -> Optional[Hit]:
    registered = (ctx.record.get("vat") or {}).get("registered")
    if registered is not False or ctx.sales <= VAT_REGISTRATION_THRESHOLD:
        return None
    return Hit(f"Turnover {_money(ctx.sales)} is over the VAT registration threshold ({_money(VAT_REGISTRATION_THRESHOLD)}) "
               "and the client is not VAT registered", f"Sales for the year {_money(ctx.sales)}.", ctx.sales)


@test("flat_rate_limit")
def flat_rate_limit(ctx: Ctx, p) -> Optional[Hit]:
    scheme = str((ctx.record.get("vat") or {}).get("scheme") or "").upper()
    if "FLAT" not in scheme or ctx.sales <= FLAT_RATE_LEAVE_THRESHOLD:
        return None
    return Hit(f"Flat Rate Scheme with turnover {_money(ctx.sales)}: over the £230,000 limit to stay on it",
               f"Sales for the year {_money(ctx.sales)}.", ctx.sales)


@test("deferred_tax_missing")
def deferred_tax_missing(ctx: Ctx, p) -> Optional[Hit]:
    framework = str((ctx.record.get("client") or {}).get("framework") or "").upper()
    if "102" not in framework or "105" in framework:
        return None
    fixed = sum(v for k, v in ctx.bal.items() if ctx.section(k) == "Tangible assets")
    has_dt = any(abs(v) >= 0.01 for k, v in ctx.bal.items() if ctx.section(k) in ("Deferred tax", "Provisions and liabilities"))
    if fixed < 1000 or has_dt:
        return None
    return Hit(f"Fixed assets of {_money(fixed)} and no deferred tax in the books (FRS 102)",
               "Capital allowances usually differ from depreciation, which gives a timing difference.", fixed)


@test("round_journals")
def round_journals(ctx: Ctx, p) -> Optional[Hit]:
    mat = float(((ctx.record.get("materiality") or {}).get("performance")) or p.get("min", 1000))
    found = [l for l in ctx.lines if re.search(r"journal", l.source or "", re.I)
             and max(l.debit, l.credit) >= max(mat, 500) and max(l.debit, l.credit) % 100 == 0]
    if not found:
        return None
    found.sort(key=lambda l: -max(l.debit, l.credit))
    total = sum(max(l.debit, l.credit) for l in found)
    return Hit(f"{len(found)} round-sum journal line(s), {_money(total)}",
               "Large journals in round sums are often estimates: check the support.", total, [_line(l) for l in found[:6]],
               _lines_figures(found))


@test("ledger_vs_aged_list")
def ledger_vs_aged_list(ctx: Ctx, p) -> Optional[Hit]:
    from backend.app.services.ingestion.ageing_reports import read_ageing_reports
    kind, code = p["kind"], p["code"]
    try:
        report = read_ageing_reports(str(ctx.engagement.id), ctx.engagement.period_end_date, ctx.tb_records).get(kind)
    except Exception:
        return None
    if report is None or report.total is None:
        return None
    books = abs(sum(float(t.net_amount or 0) for t in ctx.tb_records if t.std_code == code))
    diff = round(books - abs(report.total), 2)
    if abs(diff) < 1:
        return None
    what = "debtors" if kind == "AR" else "creditors"
    return Hit(f"Trade {what} in the books {_money(books)} against the aged list {_money(report.total)}: {_money(diff)} difference",
               f"Books {_money(books)}; aged {what} report ({report.file_name}) {_money(report.total)}.", abs(diff))


@test("loan_without_interest")
def loan_without_interest(ctx: Ctx, p) -> Optional[Hit]:
    loans = [(t.raw_account_name, float(t.net_amount or 0)) for t in ctx.tb_records
             if abs(float(t.net_amount or 0)) >= 1000 and re.search(r"\bloans?\b|bounce back|cbils|mortgage", t.raw_account_name or "", re.I)
             and not re.search(r"director|dla|staff|employee|interest", t.raw_account_name or "", re.I) and not ctx.is_pl(t.std_code)]
    if not loans:
        return None
    # Interest: the interest section, or an account named for it ('Loan Interest Paid') not mapped there yet
    interest = sum(v for k, v in ctx.bal.items() if ctx.section(k) == "Interest payable and similar charges") \
        + sum(float(t.net_amount or 0) for t in ctx.tb_records if re.search(r"interest", t.raw_account_name or "", re.I)
              and float(t.net_amount or 0) > 0 and ctx.section(t.std_code) != "Interest payable and similar charges")
    if abs(interest) >= 1:
        return None
    return Hit("Loan balances and no interest cost this year",
               "; ".join(f"{n}: {_money(v)}" for n, v in loans[:5]), sum(abs(v) for _, v in loans))
