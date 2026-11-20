"""
Restaurant / food business recognition and consistency checks. Runs only for a client whose industry the
accountant has confirmed as restaurant (RES). Rules 5-8 are done by other checks:
  Rule 5 staff paid outside payroll  -> payroll check (G6.2, from the payroll report)
  Rule 6 missing regular expenses    -> accruals check (G10.2)
  Rule 7 costs for after the year end -> prepayments check (E3.2)
  Rule 8 kitchen equipment expensed  -> capital check (C1.2)
This file does the rest:
  Rule 1  sales recorded straight from bank receipts, not from invoices or till (POS) entries
  Rule 2  payment gateway / delivery platform sales (Uber Eats, Deliveroo, Stripe...) with no commission shown,
          so sales may be recorded net instead of gross
  Rule 3  food and drink recorded outside cost of sales (subsistence, staff welfare, general expenses)
  Rule 4  supplier that looks personal (Amazon, supermarkets, lifestyle brands): confirm business purpose
  Sense check: gross profit % and staff costs % of sales for a restaurant
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import MasterCOA, TBRecord
from backend.app.services.sop.common import GLLine, MIN_LINE_AMOUNT, PAYROLL_CODES, gl_lines, supplier_name

SALES_SECTIONS = {"Sales"}
COST_OF_SALES = "Cost of sales"
STAFF_SECTION = "Employee costs"
# Money in straight from the bank (Xero Receive Money, QuickBooks Deposit / bank Expense lines), not an invoice or
# a till / POS entry (QuickBooks Sales Receipt, a journal of the daily takings)
BANK_SOURCES = re.compile(r"^(receive money|deposit|expense|spend money|bank transfer|transfer)$", re.IGNORECASE)

# Rule 2: the whole payee is the gateway ('Square Payments UK'), so a company like 'Square Enix' is not one
GATEWAY = re.compile(r"^(stripe|square|sumup|zettle|izettle|paypal|uber ?eats|uber|deliveroo|just ?eat|dojo|worldpay|"
                     r"teya|takepayments|clover|barclaycard|elavon|lloyds cardnet|cardnet)"
                     r"( (payments?|uk|ltd|limited|inc|europe|technologies|merchant services|eats|portier))*$",
                     re.IGNORECASE)

# Rule 3: food and drink, by wholesaler or by words in the description
FOOD = re.compile(r"\b(food|foods|ingredients?|meat|butchers?|fish|seafood|veg|vegetables?|fruit|bakery|bread|"
                  r"dairy|milk|cheese|eggs|flour|coffee beans|beverages?|soft drinks|wine|beer|spirits|catering|"
                  r"cash and carry|booker|brakes|bidfood|costco|makro|bestway|jj ?foods|sysco|country choice|"
                  r"matthew clark|kent frozen foods)\b", re.IGNORECASE)

# Rule 4: suppliers that look personal (an indicator only); the payee must start with the name
PERSONAL = re.compile(r"^(amazon|ebay|argos|ikea|primark|zara|h ?& ?m|asos|john lewis|boots|superdrug|"
                      r"netflix|spotify|disney|apple|playstation|xbox|nintendo|now tv|tesco|sainsbury'?s?|asda|"
                      r"aldi|lidl|morrisons|waitrose|co-?op|iceland|sports direct|jd sports|nike|adidas|airbnb|"
                      r"uber eats|deliveroo|just eat)\b", re.IGNORECASE)
PERSONAL_MIN_AMOUNT = 20.0
FOOD_MIN_AMOUNT = 20.0

# Sense check: usual ranges for a restaurant (to confirm with the accountant)
GROSS_PROFIT_RANGE = (55.0, 80.0)     # % of sales
STAFF_COST_RANGE = (15.0, 45.0)       # % of sales

FLAG_BANK_SALES = ("Sales are recorded directly from bank receipts. Bank receipts are not sales (payment gateways, "
                   "delays, refunds): sales should come from invoices or till (POS) reports.")
FLAG_NET_SALES = ("Sales come through a payment gateway / delivery platform but no commission is shown. Sales may be "
                  "recorded net: gross sales should go to revenue and the commission to expenses.")
FLAG_FOOD = "Food or drink recorded outside cost of sales. Misclassification inflates gross profit."
FLAG_PERSONAL = "Possible personal expense - confirm business purpose."
RESTAURANT_RULES = {1: (FLAG_BANK_SALES, "MEDIUM"), 2: (FLAG_NET_SALES, "MEDIUM"), 3: (FLAG_FOOD, "MEDIUM"),
                    4: (FLAG_PERSONAL, "LOW")}


@dataclass
class RestaurantFlag:
    rule: int
    when: Optional[date]
    account: str
    description: str
    amount: float
    reason: str


@dataclass
class RestaurantReview:
    sales: float
    cost_of_sales: float
    staff_costs: float
    flags: List[RestaurantFlag]

    @property
    def gross_profit_pct(self) -> Optional[float]:
        return round((self.sales - self.cost_of_sales) / self.sales * 100, 1) if self.sales else None

    @property
    def staff_cost_pct(self) -> Optional[float]:
        return round(self.staff_costs / self.sales * 100, 1) if self.sales else None

    def sense_checks(self) -> List[str]:
        """The closing sense-check questions, answered with this year's figures (only the ones that look wrong)."""
        notes = []
        gp, staff = self.gross_profit_pct, self.staff_cost_pct
        if gp is not None and not GROSS_PROFIT_RANGE[0] <= gp <= GROSS_PROFIT_RANGE[1]:
            notes.append(f"Gross profit is {gp}% of sales; a restaurant usually makes {GROSS_PROFIT_RANGE[0]:.0f}-"
                         f"{GROSS_PROFIT_RANGE[1]:.0f}%. Investigate classification or timing of sales and food costs.")
        if staff is not None and not STAFF_COST_RANGE[0] <= staff <= STAFF_COST_RANGE[1]:
            notes.append(f"Staff costs are {staff}% of sales; a restaurant usually spends {STAFF_COST_RANGE[0]:.0f}-"
                         f"{STAFF_COST_RANGE[1]:.0f}%. Check staff are paid through payroll and costs are complete.")
        return notes


def _section(l: GLLine, chart: Dict[int, MasterCOA]) -> str:
    return chart[l.code].category if l.code in chart else ""


def find_restaurant_issues(period_end: date, lines: Iterable[GLLine], chart: Dict[int, MasterCOA]) -> RestaurantReview:
    lines = [l for l in lines if l.when <= period_end and l.code in chart]
    sales_lines = [l for l in lines if _section(l, chart) in SALES_SECTIONS]
    expense = [l for l in lines if chart[l.code].financial_class == "Profit and Loss"
               and _section(l, chart) not in SALES_SECTIONS and l.debit >= MIN_LINE_AMOUNT]
    sales = sum(l.credit - l.debit for l in sales_lines)
    cost_of_sales = sum(l.debit - l.credit for l in lines if _section(l, chart) == COST_OF_SALES)
    staff = sum(l.debit - l.credit for l in lines if _section(l, chart) == STAFF_SECTION)
    flags: List[RestaurantFlag] = []

    # Rule 1: sales straight from the bank, by source (a summary: one line per account and source)
    from_bank: Dict[tuple, float] = {}
    for l in sales_lines:
        if BANK_SOURCES.match(l.source.strip()):
            key = (l.account, l.source)
            from_bank[key] = from_bank.get(key, 0.0) + l.credit - l.debit
    other_sales = sum(l.credit - l.debit for l in sales_lines if not BANK_SOURCES.match(l.source.strip()))
    for (account, source), amount in sorted(from_bank.items(), key=lambda x: -x[1]):
        if amount >= MIN_LINE_AMOUNT:
            share = f"{amount / sales * 100:.0f}% of sales" if sales else ""
            note = "" if other_sales >= MIN_LINE_AMOUNT else " No invoice or till (POS) sales were found at all."
            flags.append(RestaurantFlag(1, None, account, f"{source} entries posted to sales ({share}).{note}",
                                        round(amount, 2), FLAG_BANK_SALES))

    # Rule 2: gateway / platform sales, and the commission booked for each one
    gateway_sales: Dict[str, float] = {}
    commission: Dict[str, float] = {}
    for l in sales_lines:
        name = supplier_name(l.description)
        if GATEWAY.match(name):
            gateway_sales[name] = gateway_sales.get(name, 0.0) + l.credit - l.debit
    for l in expense:
        name = supplier_name(l.description)
        if GATEWAY.match(name):
            commission[name] = commission.get(name, 0.0) + l.debit
    for name, amount in sorted(gateway_sales.items(), key=lambda x: -x[1]):
        if amount >= MIN_LINE_AMOUNT and commission.get(name, 0.0) < MIN_LINE_AMOUNT:
            flags.append(RestaurantFlag(2, None, "Sales", f"{name}: £{amount:,.2f} of sales, no commission or fees "
                                        f"recorded for it", round(amount, 2), FLAG_NET_SALES))

    # Rules 3 and 4: one line each
    for l in expense:
        if _section(l, chart) == COST_OF_SALES or l.code in PAYROLL_CODES:
            continue
        if l.debit >= FOOD_MIN_AMOUNT and FOOD.search(l.description):
            flags.append(RestaurantFlag(3, l.when, l.account, l.description, l.debit, FLAG_FOOD))
        elif l.debit >= PERSONAL_MIN_AMOUNT and PERSONAL.match(supplier_name(l.description)):
            flags.append(RestaurantFlag(4, l.when, l.account, l.description, l.debit, FLAG_PERSONAL))

    return RestaurantReview(round(sales, 2), round(cost_of_sales, 2), round(staff, 2), flags)


def restaurant_review(engagement_id: str, period_end: date, tb_records: Iterable[TBRecord], db: Session) -> RestaurantReview:
    tb_records = list(tb_records)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    return find_restaurant_issues(period_end, gl_lines(engagement_id, tb_records, db), chart)
