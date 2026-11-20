"""The Self Assessment tax calculation, in TaxCalc's order. Pure: the person's income and
reliefs in, every figure of the calculation out; the rates come from parameters/rates.json by tax year.

  1  income by type: non-savings (employment, self-employment, property, pensions, foreign, other), savings, dividends
  2  reliefs deducted from net income (losses...), against non-savings first, then savings, then dividends
  3  adjusted net income (less gross Gift Aid and gross pension contributions under relief at source); personal
     allowance tapered by £1 for every £2 over £100,000 (ITA 2007 s35); set against non-savings, savings, dividends
  4  bands extended by gross Gift Aid and relief-at-source pension contributions (ITA 2007 s414, FA 2004 s192)
  5  non-savings at 20 / 40 / 45%; savings: starting rate band (£5,000 less taxable non-savings), personal savings
     allowance (s12B), then savings rates; dividends: allowance (s13A) then 8.75 / 33.75 / 39.35% (s8)
  6  tax reductions (VCT, EIS and SEIS subscriptions, finance costs at 20%, Marriage Allowance received, foreign tax
     credit last), never below nil
  7  Class 4 (6% between the limits, 2% above), Class 2 (treated as paid at or above the small profits threshold),
     High Income Child Benefit Charge (1% for each £200 over £60,000, ITEPA s681C)
  8  tax deducted at source, the balance, and next year's payments on account (TMA s59A: not when the relevant amount
     is under £1,000 or at least 80% of the liability was deducted at source)

Each band line's tax is rounded down to the penny, as HMRC and TaxCalc do (£12,289 at 8.75% = £1,075.28). Scottish rates are not held (England, Wales, NI)."""

import json
import math
from dataclasses import asdict, dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Dict, List, Optional

RATES = json.loads((Path(__file__).resolve().parents[1] / "parameters" / "rates.json").read_text(encoding="utf-8"))


def rates_for(tax_year: str) -> dict:
    if tax_year not in RATES:
        raise ValueError(f"No rates held for {tax_year}")
    return RATES[tax_year]


def _p(x: float) -> float:
    """To the penny, half up."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _down(x: float) -> float:
    """Down to the penny. Rounded to 6 places first: £36,442.70 at 20% is 7288.539999... in binary, and is £7,288.54."""
    return float(Decimal(str(round(x, 6))).quantize(Decimal("0.01"), rounding=ROUND_DOWN))


@dataclass
class Income:
    """The person's figures for the year (whole pounds as on the return)."""
    tax_year: str = "2025-26"
    employment: float = 0.0            # pay and taxable benefits less allowable expenses
    self_employment: float = 0.0       # taxable profits
    property: float = 0.0              # UK property profits (finance costs not deducted)
    pensions: float = 0.0              # state and private pensions
    foreign: float = 0.0               # foreign non-savings income
    other: float = 0.0                 # other non-savings income (SA101, trading allowance income...)
    savings: float = 0.0               # UK and foreign interest (gross)
    dividends: float = 0.0             # UK and foreign dividends
    reliefs: float = 0.0               # deducted from net income: losses, qualifying interest...
    gift_aid_gross: float = 0.0        # Gift Aid payments grossed up (net / 0.8)
    pension_ras_gross: float = 0.0     # pension contributions under relief at source, grossed up
    finance_costs: float = 0.0         # residential finance costs (incl. brought forward) for the 20% credit
    overseas_property: float = 0.0     # overseas property profit (inside 'foreign'), for its own finance cost credit
    overseas_finance_costs: float = 0.0  # overseas residential finance costs: limited by the overseas profit
    marriage_allowance: str = ""       # "received" or "transferred"
    class4_profits: Optional[float] = None   # profits for Class 4 (default: self_employment)
    class2_voluntary: bool = False     # pays Class 2 voluntarily on profits under the small profits threshold
    has_trade: bool = False            # a self-employment on the return (a loss too: Class 2 may be paid voluntarily)
    class4_exempt: str = ""            # PENSION_AGE / UNDER_16 / NON_RESIDENT: no Class 4 (SA103S box 37, SA103F 101)
    child_benefit: float = 0.0         # Child Benefit received in the year (for HICBC)
    student_loan: float = 0.0          # repayment worked out elsewhere (added to the liability)
    foreign_tax_credit: float = 0.0    # Foreign Tax Credit Relief worked out source by source (foreign.py)
    investments: Dict[str, float] = field(default_factory=dict)   # VCT / EIS / SEIS subscribed, for the tax reductions
    loan_interest: float = 0.0         # qualifying loan interest paid (a relief from income, capped: ITA s24A)
    tax_deducted: float = 0.0          # PAYE, CIS and other tax taken off at source
    payments_on_account_made: float = 0.0


@dataclass
class BandLine:
    kind: str                          # non_savings / savings / dividends
    band: str                          # starting / psa / allowance / basic / higher / additional
    amount: float
    rate: float
    tax: float


@dataclass
class Calculation:
    tax_year: str
    total_income: float
    net_income: float
    adjusted_net_income: float
    personal_allowance: float
    taxable: Dict[str, float]
    lines: List[BandLine] = field(default_factory=list)
    income_tax: float = 0.0            # before reductions
    reductions: Dict[str, float] = field(default_factory=dict)
    finance_costs_relieved: float = 0.0  # residential finance costs given the 20% credit this year
    overseas_finance_costs_relieved: float = 0.0  # the same for the overseas property business
    income_tax_due: float = 0.0        # after reductions
    class4: float = 0.0
    class2: float = 0.0
    class2_below_threshold: bool = False  # profits under the small profits threshold: Class 2 is not treated as paid
    class4_exempt: str = ""
    hicbc: float = 0.0
    student_loan: float = 0.0
    liability: float = 0.0             # income tax + Class 4 + Class 2 + HICBC + student loan
    tax_deducted: float = 0.0
    balance: float = 0.0               # liability less tax deducted at source
    poa_each: float = 0.0              # each payment on account for next year
    payments_on_account_made: float = 0.0
    due_31_january: float = 0.0        # balancing payment plus next year's first payment on account

    def as_dict(self) -> dict:
        return asdict(self)


def _take(amount: float, layers: List[float]) -> List[float]:
    """Split `amount` across layers in order; what is left over goes in the last."""
    out = []
    for cap in layers:
        part = min(amount, max(cap, 0.0))
        out.append(part)
        amount -= part
    out[-1] += amount
    return out


def calculate(inc: Income) -> Calculation:
    r = rates_for(inc.tax_year)
    non_savings = (inc.employment + inc.self_employment + inc.property + inc.pensions + inc.foreign + inc.other)
    parts = {"non_savings": non_savings, "savings": inc.savings, "dividends": inc.dividends}
    total = sum(parts.values())

    # 2  reliefs from net income: non-savings, then savings, then dividends; qualifying loan interest capped at the
    #    greater of £50,000 and 25% of total income (ITA s24A)
    cap = r["loan_interest_cap"]
    loan_interest = min(inc.loan_interest, max(cap["fixed"], cap["share"] * total)) if inc.loan_interest else 0.0
    left = inc.reliefs + loan_interest
    for k in parts:
        cut = min(parts[k], left)
        parts[k] -= cut
        left -= cut
    net = sum(parts.values())

    # 3  personal allowance
    extension = inc.gift_aid_gross + inc.pension_ras_gross
    ani = net - extension
    pa = r["personal_allowance"]
    if ani > r["taper_from"]:
        pa = max(0.0, pa - math.floor((ani - r["taper_from"]) / 2))
    if inc.marriage_allowance == "transferred":
        pa = max(0.0, pa - r["marriage_allowance"])
    allowance = pa
    taxable = {}
    for k in parts:
        used = min(parts[k], allowance)
        taxable[k] = parts[k] - used
        allowance -= used

    # 4  bands
    basic_limit = r["basic_band"] + extension
    higher_limit = r["higher_limit"] + extension

    calc = Calculation(inc.tax_year, total, net, ani, pa, dict(taxable))
    pos = 0.0                                   # taxable income placed in the bands so far

    def charge(kind: str, amount: float, rates: Dict[str, float]) -> None:
        nonlocal pos
        basic, higher, additional = _take(amount, [basic_limit - pos, higher_limit - max(pos, basic_limit), 0.0])
        for band, part in (("basic", basic), ("higher", higher), ("additional", additional)):
            if part > 0:
                calc.lines.append(BandLine(kind, band, part, rates[band], _down(part * rates[band])))
        pos += amount

    def nil(kind: str, band: str, amount: float) -> None:
        nonlocal pos
        if amount > 0:
            calc.lines.append(BandLine(kind, band, amount, 0.0, 0.0))
            pos += amount

    # 5  non-savings
    charge("non_savings", taxable["non_savings"], r["rates"])
    # savings: starting rate band, then the personal savings allowance (by the highest rate any income reaches)
    total_taxable = sum(taxable.values())
    psa_key = ("additional" if total_taxable > higher_limit else "higher" if total_taxable > basic_limit else "basic")
    s = taxable["savings"]
    starting = min(s, max(0.0, r["savings_starting_band"] - taxable["non_savings"]))
    nil("savings", "starting", starting)
    psa = min(s - starting, r["personal_savings_allowance"][psa_key])
    nil("savings", "psa", psa)
    charge("savings", s - starting - psa, r["rates"])
    # dividends
    d = taxable["dividends"]
    da = min(d, r["dividend_allowance"])
    nil("dividends", "allowance", da)
    charge("dividends", d - da, r["dividend_rates"])

    calc.income_tax = _p(sum(l.tax for l in calc.lines))

    # 6  tax reductions
    room = calc.income_tax
    # investment reliefs first: VCT 30%, EIS 30%, SEIS 50% of the amount subscribed up to each year's limit
    for kind in ("VCT", "EIS", "SEIS"):
        amount = inc.investments.get(kind, 0.0)
        if amount:
            rate, limit = r["investment"][kind]
            cut = min(room, _p(min(amount, limit) * rate))
            if cut:
                calc.reductions[kind.lower()] = cut
                room -= cut
    # Residential finance costs (ITTOIA s274A): each property business on its own, the UK one and the overseas one,
    # limited by that business's profit; together limited by adjusted total income (overseas lets follow
    # the same finance cost rule). An overseas-only landlord gets the credit too
    uk_base = min(inc.finance_costs, inc.property) if inc.finance_costs and inc.property > 0 else 0.0
    os_base = (min(inc.overseas_finance_costs, inc.overseas_property)
               if inc.overseas_finance_costs and inc.overseas_property > 0 else 0.0)
    if uk_base or os_base:
        adjusted_total = max(0.0, taxable["non_savings"])        # net income less savings, dividends and allowances
        uk_base = min(uk_base, adjusted_total)
        os_base = min(os_base, adjusted_total - uk_base)
        base = uk_base + os_base
        cut = min(room, _p(base * r["finance_cost_credit"]))
        if cut:
            calc.reductions["finance_costs"] = cut
            # The finance costs relieved (the rest carries forward, business by business): all of each base, unless
            # the tax ran out first (the UK business takes it first)
            relieved = base if cut == _p(base * r["finance_cost_credit"]) else round(cut / r["finance_cost_credit"], 2)
            calc.finance_costs_relieved = round(min(uk_base, relieved), 2)
            calc.overseas_finance_costs_relieved = round(max(0.0, relieved - uk_base), 2)
            room -= cut
    if inc.marriage_allowance == "received":
        cut = min(room, _p(r["marriage_allowance"] * r["rates"]["basic"]))
        if cut:
            calc.reductions["marriage_allowance"] = cut
            room -= cut
    if inc.foreign_tax_credit:                  # given last, after the other reductions (HS263)
        cut = min(room, _p(inc.foreign_tax_credit))
        if cut:
            calc.reductions["foreign_tax_credit"] = cut
            room -= cut
    calc.income_tax_due = _p(room)

    # 7  NIC and the child benefit charge
    c4 = r["class4"]
    profits = inc.self_employment if inc.class4_profits is None else inc.class4_profits
    main = max(0.0, min(profits, c4["upper"]) - c4["lower"])
    above = max(0.0, profits - c4["upper"])
    # No Class 4 for one over State Pension age at the start of the year, under 16, or not UK resident (SSCBA
    # 1992 s17 and the 2001 Regulations, the accountant's choice on Tax calculation)
    calc.class4_exempt = inc.class4_exempt or ""
    calc.class4 = 0.0 if calc.class4_exempt else _p(_p(main * c4["main"]) + _p(above * c4["above"]))
    c2 = r["class2"]
    # Profits under the small profits threshold, a loss included: Class 2 is not treated as paid and may be paid
    # voluntarily to protect the State Pension (SSCBA 1992 s11)
    calc.class2_below_threshold = (inc.has_trade or profits > 0) and profits < c2["small_profits_threshold"]
    if inc.class2_voluntary and calc.class2_below_threshold:
        calc.class2 = _p(c2["weekly"] * c2["weeks"])
    h = r["hicbc"]
    if inc.child_benefit and ani > h["from"]:
        pct = min(100, math.floor((ani - h["from"]) / h["step"]))
        calc.hicbc = float(math.floor(inc.child_benefit * pct / 100))
    calc.student_loan = _p(inc.student_loan)

    # 8  liability, balance, payments on account
    calc.liability = _p(calc.income_tax_due + calc.class4 + calc.class2 + calc.hicbc + calc.student_loan)
    calc.tax_deducted = _p(inc.tax_deducted)
    calc.balance = _p(calc.liability - calc.tax_deducted)
    relevant = _p(calc.income_tax_due + calc.class4 + calc.hicbc - calc.tax_deducted)
    poa = r["poa"]
    base_liability = calc.income_tax_due + calc.class4 + calc.hicbc
    if relevant >= poa["min_relevant"] and not (base_liability and calc.tax_deducted >= poa["at_source_share"] * base_liability):
        calc.poa_each = _down(relevant / 2)
    calc.payments_on_account_made = _p(inc.payments_on_account_made)
    calc.due_31_january = _p(calc.balance - calc.payments_on_account_made + calc.poa_each)
    return calc
