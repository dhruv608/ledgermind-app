"""Settlement control tabs from the industry schedules: money that reaches the bank through a
provider who keeps fees, set against the provider's own report, one block per provider, a row per month.

  F-P Platform clearing (e-commerce, IND-ECM-05 / 06 / 09 / 10 / 11): Amazon, Shopify, eBay, Etsy, PayPal, Stripe ...
  K1-T Takings (restaurants, IND-RES-04 / 07 / 08 / 09): card terminals (Dojo, SumUp, Square, Worldpay, Zettle ...)
       and delivery apps (Deliveroo, Uber Eats, Just Eat), then a cash block: takings per Z-reports, banked, paid out
       in cash, cash in hand. The same for retail (IND-RTL-04 / 05, EPOS) and hair and beauty (IND-HBB-05, booking
       platforms: Fresha, Treatwell, Booksy ...).
  K1-R Remittances (healthcare, IND-HLT-05): income by payer (NHS, ICB / CCG, council) v the remittance advices.

  Payouts per bank        from the ledger (the provider's receipts on sales lines)
  Gross sales, fees, refunds, reserve held at the month end   typed from the provider's report (input)
  Payout per report       = gross sales - fees - refunds - (reserve at the end - reserve at the start)
  Difference              = payout per report - payouts per bank (must be nil once the report is typed)

Below each block: gross sales per the report against the ledger's sales on that provider's lines, and the gross-up
journal the totals give (fees and refunds out of the netted sales). Nothing is posted. A provider with less than
£500 in the year is left out (one Etsy sale is not worth a control)."""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from backend.app.services.workbook.balance_tabs.common import INPUT_FILL
from backend.app.services.workbook.context import BuildContext

MONEY = "#,##0.00;(#,##0.00);-"
MIN_PLATFORM = 500.0
PLATFORMS = (
    ("Amazon", re.compile(r"\bamazon\b|\bamzn\b", re.I)), ("Shopify", re.compile(r"shopify", re.I)),
    ("eBay", re.compile(r"\bebay\b", re.I)), ("Etsy", re.compile(r"\betsy\b", re.I)),
    ("PayPal", re.compile(r"paypal", re.I)), ("Stripe", re.compile(r"\bstripe\b", re.I)),
    ("TikTok Shop", re.compile(r"tiktok", re.I)), ("OnBuy", re.compile(r"\bonbuy\b", re.I)),
    ("Wayfair", re.compile(r"wayfair", re.I)), ("Not On The High Street", re.compile(r"notonthehighstreet|not on the high street", re.I)),
)
TAKINGS = (
    ("Deliveroo", re.compile(r"deliveroo|roofoods", re.I)), ("Uber Eats", re.compile(r"uber ?eats|\buber\b", re.I)),
    ("Just Eat", re.compile(r"just ?eat", re.I)), ("Dojo", re.compile(r"\bdojo\b|paymentsense", re.I)),
    ("SumUp", re.compile(r"sum ?up", re.I)), ("Square", re.compile(r"\bsquare\b|\bsq \*", re.I)),
    ("Worldpay", re.compile(r"worldpay", re.I)), ("Zettle", re.compile(r"zettle|izettle", re.I)),
    ("Teya", re.compile(r"\bteya\b|saltpay", re.I)), ("Barclaycard", re.compile(r"barclaycard|barclays merchant", re.I)),
    ("Takepayments", re.compile(r"takepayments", re.I)), ("Stripe", re.compile(r"\bstripe\b", re.I)),
    ("EVO", re.compile(r"\bevo\b|evo payments", re.I)), ("Elavon", re.compile(r"elavon", re.I)),
    ("Global Payments", re.compile(r"global payments|globalpay", re.I)), ("Cardnet", re.compile(r"cardnet", re.I)),
    ("First Data", re.compile(r"first data|fiserv|clover", re.I)),
)
BOOKINGS = TAKINGS + (
    ("Fresha", re.compile(r"fresha", re.I)), ("Treatwell", re.compile(r"treatwell", re.I)),
    ("Booksy", re.compile(r"booksy", re.I)), ("Phorest", re.compile(r"phorest", re.I)),
    ("Timely", re.compile(r"gettimely|\btimely\b", re.I)),
)
PAYERS = (
    ("NHS", re.compile(r"\bnhs\b|nhsbsa|nhs england|primary care support", re.I)),
    ("ICB / CCG", re.compile(r"\bicb\b|\bccg\b|integrated care|clinical commissioning", re.I)),
    ("Council", re.compile(r"council|borough|local authority", re.I)),
)
CASH_BANKED = re.compile(r"\bcash\b|counter credit|paid in at|deposit at", re.I)


@dataclass
class Settings:
    industry: str
    tab: str
    ref: str
    title: str
    providers: tuple
    anchor: str             # the tabs it goes after (regex on the tab name; the last match)
    rules: str              # the industry rule ids, for the gross-up line
    cash: bool = False      # a restaurant's cash block


ECOMMERCE = Settings("ECM", "F-P Platform clearing", "F-P",
                     "Platform clearing: payouts per bank v the platforms' settlement reports", PLATFORMS, r"^F\d",
                     "IND-ECM-06")
RESTAURANT = Settings("RES", "K1-T Takings", "K1-T",
                      "Takings: card and delivery settlements v the providers' reports, and cash", TAKINGS, r"^K1\b",
                      "IND-RES-04", cash=True)


RETAIL = Settings("RTL", "K1-T Takings", "K1-T",
                  "Takings: card settlements v the providers' reports, EPOS takings and cash", TAKINGS, r"^K1\b",
                  "IND-RTL-04", cash=True)
HAIR = Settings("HBB", "K1-T Takings", "K1-T",
                "Takings: card, booking platforms and cash v the till / booking reports", BOOKINGS, r"^K1\b",
                "IND-HBB-05", cash=True)
HEALTH = Settings("HLT", "K1-R Remittances", "K1-R",
                  "Income by payer: NHS, ICB / CCG and council remittances v the remittance advices", PAYERS, r"^K1\b",
                  "IND-HLT-05")
BY_INDUSTRY = {"RES": RESTAURANT, "RTL": RETAIL, "HBB": HAIR, "HLT": HEALTH}


def platform_of(text: str, providers=PLATFORMS) -> Optional[str]:
    return next((name for name, words in providers if words.search(text or "")), None)


def add_platform_tab(ctx: BuildContext) -> Optional[str]:
    return _settlement_tab(ctx, ECOMMERCE)


def add_takings_tab(ctx: BuildContext) -> Optional[str]:
    """Restaurants, retail, hair and beauty: takings; healthcare: remittances by payer (whichever the industry is)."""
    from backend.app.services.setup.profile_service import confirmed_industry
    settings = BY_INDUSTRY.get(confirmed_industry(getattr(ctx.engagement, "profile", None)) or "")
    return _settlement_tab(ctx, settings) if settings else None


def _settlement_tab(ctx: BuildContext, s: Settings) -> Optional[str]:
    from sqlalchemy import select
    from backend.app.models.database import MasterCOA
    from backend.app.services.setup.profile_service import confirmed_industry
    from backend.app.services.sop.common import gl_lines, year_months
    profile = getattr(ctx.engagement, "profile", None)
    if ctx.db is None or confirmed_industry(profile) != s.industry:
        return None
    chart = {c.std_code: c for c in ctx.db.execute(select(MasterCOA)).scalars()}
    months = year_months(ctx.engagement.period_end_date)
    payouts: Dict[str, Dict[Tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))
    banked: Dict[Tuple[int, int], float] = defaultdict(float)
    sales: Dict[str, float] = defaultdict(float)
    for l in gl_lines(str(ctx.engagement.id), ctx.tb_records, ctx.db):
        c = chart.get(l.code)
        if c is None or l.when is None or c.category not in ("Sales", "Other operating income"):
            continue
        amount = round(l.credit - l.debit, 2)
        provider = platform_of(f"{l.description} {l.account}", s.providers)
        if provider is not None:
            sales[provider] += amount
            payouts[provider][(l.when.year, l.when.month)] += amount
        elif s.cash and CASH_BANKED.search(l.description or ""):
            banked[(l.when.year, l.when.month)] += amount
    # A provider with a few pounds in the year (one Etsy sale) is not worth a control
    payouts = {p: v for p, v in payouts.items() if abs(sum(v.values())) >= MIN_PLATFORM}
    if not payouts and not (s.cash and banked):
        return None
    wb = ctx.wb
    anchor = next((n for n in reversed(wb.sheetnames) if re.match(s.anchor, n)), None)
    ws = wb.create_sheet(s.tab, wb.sheetnames.index(anchor) + 1 if anchor else len(wb.sheetnames))
    ws["A1"], ws["A2"], ws["E1"] = "=A!B2", "='Notes & Queries'!A2", s.ref
    ws["A4"] = s.title
    ws["A4"].font = Font(name="Calibri", size=12, bold=True)
    ws["A5"] = ("Type each month from the provider's report in the shaded cells (reserve = the amount the provider "
                "held at the month end). The difference must be nil.")
    row = 7
    for provider, by_month in sorted(payouts.items()):
        row = _provider_block(ctx, ws, row, provider, by_month, months, round(sales[provider], 2), s.rules)
    if s.cash:
        row = _cash_block(ctx, ws, row, months, banked)
    ws.column_dimensions["A"].width = 34
    for col in "BCDEFGH":
        ws.column_dimensions[col].width = 16
    ctx.report_notes.append(f"{s.title.split(':')[0]} ({s.ref}): {len(payouts)} provider(s) to agree to their reports")
    return ws.title


def _provider_block(ctx, ws, row, provider, by_month, months, sales, rules) -> int:
    heads = ["Month", "Payouts per bank", "Gross sales per report", "Fees and commission", "Refunds",
             "Reserve held at month end", "Payout per report", "Difference (must be nil)"]
    ws.cell(row=row, column=1, value=provider).font = ctx.bold_font
    row += 1
    ws.cell(row=row, column=1, value="Reserve held at the start of the year")
    opening = ws.cell(row=row, column=6)
    opening.fill, opening.number_format = INPUT_FILL, MONEY
    start = row
    row += 1
    for c, h in enumerate(heads, 1):
        ws.cell(row=row, column=c, value=h).font = ctx.bold_font
    first = row + 1
    for m in months:
        row += 1
        ws.cell(row=row, column=1, value=m.strftime("%b-%y"))
        v = by_month.get((m.year, m.month))
        ws.cell(row=row, column=2, value=round(v, 2) if v else None).number_format = MONEY
        for col in range(3, 7):
            cell = ws.cell(row=row, column=col)
            cell.fill, cell.number_format = INPUT_FILL, MONEY
        prev = f"F{row - 1}" if row > first else f"F{start}"
        ws.cell(row=row, column=7, value=f'=IF(C{row}="","",C{row}-D{row}-E{row}-(F{row}-N({prev})))').number_format = MONEY
        ws.cell(row=row, column=8, value=f'=IF(C{row}="","",ROUND(G{row}-B{row},2))').number_format = MONEY
    row += 1
    ws.cell(row=row, column=1, value="Total").font = ctx.bold_font
    for col in (2, 3, 4, 5, 7, 8):
        letter = get_column_letter(col)
        ws.cell(row=row, column=col, value=f"=SUM({letter}{first}:{letter}{row - 1})").number_format = MONEY
    total = row
    row += 2
    ws.cell(row=row, column=1, value=f"Sales in the ledger on {provider} lines")
    ws.cell(row=row, column=7, value=sales).number_format = MONEY
    row += 1
    ws.cell(row=row, column=1, value="Check: gross sales per report less the ledger's sales (must be nil)")
    ws.cell(row=row, column=7, value=f'=IF(C{total}=0,"",ROUND(C{total}-G{row - 1},2))').number_format = MONEY
    row += 1
    ws.cell(row=row, column=1, value=(f"Gross-up journal once typed ({rules}): Dr selling costs / commission "
                                      f"=D{total}, Dr sales returns =E{total}; Cr sales the same (fees and refunds out "
                                      f"of the netted payouts). Reserve held at the year end = a debtor."))
    return row + 3


def _cash_block(ctx, ws, row, months, banked) -> int:
    """IND-RES-07 / 09: takings per Z-reports (input) against the ledger, and the cash control: takings in cash less
    banked less paid out in cash = cash in hand (must not go negative)."""
    heads = ["Month", "Cash banked per bank", "Takings per Z-reports (all tenders)", "Of which cash",
             "Cash paid out (expenses, wages)", "Cash in hand at month end"]
    ws.cell(row=row, column=1, value="Cash").font = ctx.bold_font
    row += 1
    ws.cell(row=row, column=1, value="Cash in hand at the start of the year")
    opening = ws.cell(row=row, column=6)
    opening.fill, opening.number_format = INPUT_FILL, MONEY
    start = row
    row += 1
    for c, h in enumerate(heads, 1):
        ws.cell(row=row, column=c, value=h).font = ctx.bold_font
    first = row + 1
    for m in months:
        row += 1
        ws.cell(row=row, column=1, value=m.strftime("%b-%y"))
        v = banked.get((m.year, m.month))
        ws.cell(row=row, column=2, value=round(v, 2) if v else None).number_format = MONEY
        for col in (3, 4, 5):
            cell = ws.cell(row=row, column=col)
            cell.fill, cell.number_format = INPUT_FILL, MONEY
        prev = f"F{row - 1}" if row > first else f"F{start}"
        ws.cell(row=row, column=6, value=f'=IF(D{row}="","",N({prev})+D{row}-B{row}-E{row})').number_format = MONEY
    row += 1
    ws.cell(row=row, column=1, value="Total").font = ctx.bold_font
    for col in (2, 3, 4, 5):
        letter = get_column_letter(col)
        ws.cell(row=row, column=col, value=f"=SUM({letter}{first}:{letter}{row - 1})").number_format = MONEY
    total = row
    row += 2
    ws.cell(row=row, column=1, value="Sales in the ledger (all)")
    ws.cell(row=row, column=7, value="=-SUMIF('B1-ETB'!$A:$A,\"<1000\",'B1-ETB'!$N:$N)").number_format = MONEY
    row += 1
    ws.cell(row=row, column=1, value="Check: takings per Z-reports less the ledger's sales (IND-RES-07, must be nil)")
    ws.cell(row=row, column=7, value=f'=IF(C{total}=0,"",ROUND(C{total}-G{row - 1},2))').number_format = MONEY
    row += 1
    ws.cell(row=row, column=1, value=("Cash in hand must never go negative (IND-RES-09 / RES-11): a negative month "
                                      "means takings missing or expenses paid from another source."))
    return row + 2
