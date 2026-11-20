"""The corporation tax computation (the firm's Tax_Comp layout, CT600 boxes) from the final balances."""

import math
from collections import defaultdict
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple


from backend.app.models.database import MasterCOA
from backend.app.services.mapping.chart_lookup import DISALLOWABLE_FINES_NAME
from backend.app.services.tax.s455 import s455_charge
from backend.app.services.tax.ct_constants import AIA_ADDITIONS, CA_TREATMENTS, CHARITABLE_DONATIONS, COST_OF_ADDITIONS, DISPOSALS, DISPOSAL_PROFIT_CODES, DIVIDEND_SECTIONS, DLA_CODES, DOUBLE_CAB_AS_CAR_FROM, ENTERTAINING, FOREIGN_TAX_CODES, HYBRID, INTANGIBLE_DEBIT, INTEREST_SECTION, MAIN_POOL_WDA_BEFORE_APRIL_2026, NOT_A_FINE, NO_ALLOWANCE_ADDITIONS, PICK_UP, POLITICAL_DONATIONS, PRIOR_YEAR_TAX, RENTAL_INCOME_CODES, ROAD_TAX, SINGLE_CAB, SMALL_POOL, SPECIAL_POOL_WDA, TAX_SECTIONS, VAN, VEHICLE_ADDITIONS, VEHICLE_EXTRAS, ZERO_EMISSION, ZERO_EMISSION_FYA_UNTIL, FYA_40_FROM, tax_parameters
from backend.app.services.tax.ct_model import CTComputation, CTLine
from backend.app.services.tax.ct_rates import _intangibles, corporation_tax



def compute(period_start: date, period_end: date, balances: Dict[int, float], chart: Dict[int, MasterCOA],
            tax_inputs: Dict, tb_names: Dict[str, float], vehicle_lines: Iterable[Tuple[str, float]] = (),
            dla_advances: Iterable[Tuple[Optional[date], float]] = (),
            openings: Optional[Dict[int, float]] = None, dla_opening: Optional[float] = None,
            fine_lines: float = 0.0, tax_interest: float = 0.0, capital_legal: float = 0.0, gifts: float = 0.0,
            donations_paid: Optional[float] = None) -> CTComputation:
    """The computation itself, from final balances (no database), so it can be tested on its own."""
    days = (period_end - period_start).days + 1
    associates = int(tax_inputs.get("associated_companies") or 0)
    c = CTComputation(period_start, period_end, days, associates)
    bal = lambda code: balances.get(code, 0.0)
    section = lambda code: chart[code].category if code in chart else None
    is_pl = lambda code: code in chart and chart[code].financial_class == "Profit and Loss"
    name = lambda code: chart[code].std_name.lower() if code in chart else ""
    add = lambda label, amount, box="", note="", codes=(), sign=1, floor=False: c.lines.append(
        CTLine(label, round(amount, 2) + 0.0, box, note, tuple(sorted(codes)), sign, floor))     # + 0.0: never -0.00

    pl_codes = [k for k in balances if is_pl(k) and section(k) not in TAX_SECTIONS]
    turnover = -sum(bal(k) for k in pl_codes if section(k) == "Sales")
    pbt = -sum(bal(k) for k in pl_codes)
    c.profit_before_tax = round(pbt, 2)
    # UK corporation tax already charged in the accounts; foreign / double taxation (3820, 3821) is not UK tax
    # (3810, last year's tax over / under provided, is not this year's charge)
    c.tax_in_accounts = round(sum(bal(k) for k in balances if section(k) == "Current tax"
                                  and k not in FOREIGN_TAX_CODES and k != PRIOR_YEAR_TAX), 2)
    add("Turnover per accounts", turnover, "145", codes=[k for k in pl_codes if section(k) == "Sales"], sign=-1)
    add("Profit before tax per accounts", pbt, codes=pl_codes, sign=-1)

    # Add-backs (expenses are debits: positive balances)
    # (The chart files foreign exchange under its Depreciation heading: 'Foreign exchange gains/(losses) (Depreciation)')
    # ('Amortisation (Depreciation)', 3500, is an intangible's charge: worked out below, not as depreciation)
    depreciation_codes = [k for k in pl_codes if "depreciation" in name(k) and "disposal" not in name(k)
                          and "foreign exchange" not in name(k) and "exchange" not in name(k)
                          and not INTANGIBLE_DEBIT.search(name(k))]
    depreciation = sum(bal(k) for k in depreciation_codes)
    disposals_pl = sum(bal(k) for k in DISPOSAL_PROFIT_CODES if k in balances)     # + = loss, - = profit
    entertaining = max(0.0, bal(ENTERTAINING))
    fines = sum(v for n, v in tb_names.items()
                if DISALLOWABLE_FINES_NAME.search(n) and not NOT_A_FINE.search(n) and v > 0) + fine_lines
    charity, political = max(0.0, bal(CHARITABLE_DONATIONS)), max(0.0, bal(POLITICAL_DONATIONS))
    add("Add: depreciation", depreciation, codes=depreciation_codes)
    if disposals_pl > 0:
        add("Add: loss on disposal of fixed assets", disposals_pl, "", "Balancing adjustments come through capital allowances")
    add("Add: client entertaining", entertaining, "", "CTA 2009 s1298", codes=[ENTERTAINING], floor=True)
    if fines:
        add("Add: fines and penalties", fines, "", "CTA 2009 s54")
    if capital_legal > 0:
        add("Add: legal costs of a capital nature", capital_legal, "",
            "CTA 2009 s53: buying property, a business or shares, or issuing shares (CTM17600)")
    if gifts > 0:
        add("Add: gifts", gifts, "", "CTA 2009 s1298 (BIM45065); allowed only for an item of £50 or less a person a "
                                     "year carrying the business's advert (not food, drink, tobacco or vouchers, s1300)")
    tax_interest = max(0.0, tax_interest)
    if tax_interest:
        add("Add: interest and penalties on late VAT, PAYE and CIS", tax_interest, "",
            "CTA 2009 s1303; interest on late corporation tax stays allowed (CTM92190)")
    if charity:
        add("Add: charitable donations (relieved below)", charity, "305", codes=[CHARITABLE_DONATIONS], floor=True)
    if political:
        add("Add: political donations", political, codes=[POLITICAL_DONATIONS], floor=True)
    _intangibles(c, add, bal, [k for k in pl_codes if INTANGIBLE_DEBIT.search(name(k))], tax_inputs)

    # Income that is not trading income
    interest_codes = [k for k in pl_codes if section(k) == INTEREST_SECTION]
    investment_codes = [k for k in pl_codes if section(k) in DIVIDEND_SECTIONS and "interest" in name(k)]
    interest = -sum(bal(k) for k in interest_codes)
    investment_interest = -sum(bal(k) for k in investment_codes)
    dividends = -sum(bal(k) for k in pl_codes if section(k) in DIVIDEND_SECTIONS and "dividend" in name(k))
    if dividends < -1:
        # A debit on dividends received is almost always dividends paid (equity, not P&L) mapped to the wrong code
        c.notes.append(f"Dividends received shows a debit of £{-dividends:,.2f}: probably dividends paid, which are "
                       f"not an expense. Check the mapping (dividends paid go to reserves, code 8010/8011).")
    dividends = round(dividends, 2) if dividends >= 1 else 0.0
    rent = -sum(bal(k) for k in RENTAL_INCOME_CODES if k in balances)
    profit_on_disposal = -disposals_pl if disposals_pl < 0 else 0.0
    if profit_on_disposal:
        add("Less: profit on disposal of fixed assets", -profit_on_disposal)
    if interest + investment_interest:
        add("Less: interest receivable (non-trade)", -(interest + investment_interest), "170",
            codes=interest_codes + investment_codes)
    # Rent (CTA 2009 Part 4): a property business, taxed on the rent less its costs (PIM2005), unless the accountant
    # says the letting is part of the trade (the reviewer's choice, setup ct.rent_basis). With no other
    # sales the whole profit is the property business's; with other sales the costs are split: the property costs the
    # accountant gives, else in proportion to the income (just and reasonable, PIM2056)
    letting = rent >= 1 and (tax_inputs.get("rent_basis") or "").upper() != "TRADE"
    rent_in_sales = -sum(bal(k) for k in RENTAL_INCOME_CODES if k in balances and section(k) == "Sales")
    other_sales = turnover - rent_in_sales
    whole_property = letting and other_sales < 1
    adjusted = (pbt + depreciation + max(0.0, disposals_pl) + entertaining + fines + tax_interest + charity + political
                - profit_on_disposal - interest - investment_interest - dividends)
    property_costs = 0.0
    if letting and not whole_property:
        entered = tax_inputs.get("property_costs")
        costs = max(0.0, rent + other_sales - adjusted)
        property_costs = round(float(entered) if entered not in (None, "") else costs * rent / (rent + other_sales), 2)
        add("Less: rental income (property business)", -rent, "190", codes=[k for k in RENTAL_INCOME_CODES if k in balances])
        add("Add: property business costs", property_costs, "",
            "As given in the client details" if entered not in (None, "") else
            f"Costs split by income: rent is {rent / (rent + other_sales):.0%} of the income. Enter the actual property "
            f"costs in the client details if they differ")
        adjusted += property_costs - rent
    if dividends:
        add("Less: dividends received (exempt)", -dividends, "620")
    add("Adjusted profit before capital allowances", adjusted)

    # Capital allowances (CAA 2001)
    p = tax_parameters()
    aia_limit = p.get("P-AIA", 1000000.0) * min(days, 365) / 365
    openings = openings or {}

    def added(code: int) -> float:
        """This year's additions: the additions account, plus the year's increase on the cost account when its
        opening balance is known (purchases posted straight to cost)."""
        cost = COST_OF_ADDITIONS.get(code)
        on_cost = max(0.0, bal(cost) - openings[cost]) if cost in openings else 0.0
        return max(0.0, bal(code)) + on_cost

    # Every addition with the app's suggestion and the accountant's choice (tax_inputs.ca_choices: the accountant
    # decides, the app only suggests): equipment classes AIA; vehicles line by line from the ledger
    # (a van AIA, with the HP fees that come with it; a new electric car 100% FYA; any other car the special rate pool)
    choices = tax_inputs.get("ca_choices") or {}
    assets: List[Dict] = []

    def asset(key: str, group: str, description: str, cost: float, suggested: str, when=None) -> Dict:
        row = {"key": key, "group": group, "description": description, "cost": round(cost, 2), "when": when,
               "suggested": suggested, "choice": choices.get(key) if choices.get(key) in CA_TREATMENTS else suggested}
        assets.append(row)
        return row

    for code, label in AIA_ADDITIONS.items():
        if added(code) > 0:
            asset(f"class:{code}", label, f"{label} additions", added(code), "AIA")
    vehicles = added(VEHICLE_ADDITIONS)
    lines3 = [(v[0], v[1], v[2] if len(v) > 2 else None) for v in vehicle_lines]
    def is_van(d: str, when) -> bool:
        if VAN.search(d or ""):
            return True
        if PICK_UP.search(d or ""):
            bought = date.fromisoformat(str(when)[:10]) if when else period_end
            return bool(SINGLE_CAB.search(d or "")) or bought < DOUBLE_CAB_AS_CAR_FROM
        return False
    any_van = any(is_van(d, when) and a > 0 for d, a, when in lines3)
    vehicle_rows = []
    for i, (d, a, when) in enumerate(lines3):
        if a <= 0:
            continue
        if ROAD_TAX.search(d or ""):
            suggested = "NONE"
        elif is_van(d, when) or (any_van and VEHICLE_EXTRAS.search(d or "")):
            suggested = "AIA"
        elif ZERO_EMISSION.search(d or "") and not HYBRID.search(d or ""):
            bought = date.fromisoformat(str(when)[:10]) if when else period_end
            suggested = "FYA" if bought <= ZERO_EMISSION_FYA_UNTIL else "MAIN"
        else:
            suggested = "SPECIAL"
        vehicle_rows.append(asset(f"vehicle:{when}:{a:.2f}:{(d or '')[:40]}", "Motor vehicles", d or "Vehicle",
                                  a, suggested, when))
    # The vehicle additions in the accounts, shared out in this order (as the ledger lines can add up to more or less
    # than the additions account): AIA, first-year allowance, the pools; anything left over is one more row
    left = vehicles
    shares: Dict[str, float] = defaultdict(float)
    for treatment in ("AIA", "FYA", "MAIN", "SPECIAL", "NONE"):
        for row in vehicle_rows:
            if row["choice"] == treatment:
                part = min(left, row["cost"])
                shares[treatment] += part
                left -= part
    if left >= 0.5:
        rest = asset("vehicle:other", "Motor vehicles", "Vehicle additions not found in the ledger", left, "SPECIAL")
        shares[rest["choice"]] += left

    aia_items = {row["group"]: row["cost"] for row in assets if row["key"].startswith("class:") and row["choice"] == "AIA"}
    if shares["AIA"]:
        aia_items["Vans and commercial vehicles"] = shares["AIA"]
    zero_emission = shares["FYA"] + sum(r["cost"] for r in assets if r["key"].startswith("class:") and r["choice"] == "FYA")
    cars = shares["SPECIAL"]
    main_additions = shares["MAIN"] + sum(r["cost"] for r in assets if r["key"].startswith("class:") and r["choice"] == "MAIN")
    special_additions = sum(r["cost"] for r in assets if r["key"].startswith("class:") and r["choice"] == "SPECIAL")
    no_allowance = shares["NONE"] + sum(r["cost"] for r in assets if r["key"].startswith("class:") and r["choice"] == "NONE")
    c.ca_assets = assets
    changed = [r for r in assets if r["choice"] != r["suggested"]]
    if changed:
        c.notes.append(f"Capital allowances: the accountant chose the treatment of {len(changed)} addition(s) "
                       f"({'; '.join(r['description'][:30] + ': ' + CA_TREATMENTS[r['choice']] for r in changed[:4])}).")
    if no_allowance:
        c.notes.append(f"Additions of £{no_allowance:,.2f} given no capital allowances (accountant's choice).")
    aia_claim = min(sum(aia_items.values()), aia_limit)
    # A claim for less than the full allowance (CAA 2001 s51A 'may claim', s56(5); CA81400): the accountant's amount;
    # AIA expenditure not claimed goes into the main pool
    aia_unclaimed = 0.0
    if tax_inputs.get("aia_claim") not in (None, ""):
        wanted = max(0.0, min(aia_claim, float(tax_inputs["aia_claim"])))
        aia_unclaimed, aia_claim = round(aia_claim - wanted, 2), wanted
    if zero_emission:
        c.capital_allowances.append(CTLine("First-year allowance: zero-emission cars (100%)", round(zero_emission, 2), "711"))
        c.notes.append(f"Zero-emission car additions of £{zero_emission:,.2f} given 100% first-year allowance: confirm "
                       f"they were new and unused (a used electric car goes to the main pool).")
    for label, amount in aia_items.items():
        c.capital_allowances.append(CTLine(f"AIA: {label} additions", amount, "698"))
    if aia_unclaimed:
        c.capital_allowances.append(CTLine("AIA not claimed (to the main pool, the accountant's claim)", -aia_unclaimed, "698"))
        c.notes.append(f"Annual investment allowance claimed £{aia_claim:,.2f} (the accountant's figure); £{aia_unclaimed:,.2f} "
                       f"goes into the main pool (CAA 2001 s51A, s58).")
    if sum(aia_items.values()) > aia_limit:
        c.notes.append(f"Additions exceed the annual investment allowance (£{aia_limit:,.0f} for this period); the "
                       f"excess goes to the pools.")
    if associates and aia_claim:
        c.notes.append("The annual investment allowance is shared with associated companies in a group or under "
                       "common control: confirm the share claimed by this company.")
    excess_aia = max(0.0, sum(aia_items.values()) - aia_limit)
    # 40% first-year allowance on main-rate spending from 1 January 2026 over the AIA (CAA 2001 s45U, CA23195A): new
    # and unused, not cars. The other 60% joins the main pool in the next period (CA23195D), so no WDA on it now. The
    # books carry no purchase dates for plant: given when the whole period is from 1 January 2026, else a note
    fya40 = 0.0
    if excess_aia and period_end >= FYA_40_FROM and tax_inputs.get("fya_40") is not False:
        if period_start >= FYA_40_FROM:
            fya40 = round(excess_aia * p.get("P-FYA-40", 0.40), 2)
            c.capital_allowances.append(CTLine("First-year allowance: main rate additions over the AIA (40%)", fya40, "711"))
            c.notes.append(f"40% first-year allowance of £{fya40:,.2f} on the £{excess_aia:,.2f} of additions over the "
                           f"annual investment allowance (CAA 2001 s45U): confirm they were new and unused (not second-hand, "
                           f"not cars); the other £{excess_aia - fya40:,.2f} joins the main pool next period.")
        else:
            c.notes.append(f"Additions of £{excess_aia:,.2f} over the annual investment allowance: any of them new and "
                           f"unused, bought on or after 1 January 2026, can take the 40% first-year allowance "
                           f"(CAA 2001 s45U) instead of the main pool.")
    for code, label in NO_ALLOWANCE_ADDITIONS.items():
        if bal(code) > 0:
            c.notes.append(f"{label} additions of £{bal(code):,.2f} get no capital allowances (land and buildings); "
                           f"check for structures and buildings allowance (3%) or integral features (special pool).")

    # Disposal proceeds: cost disposed - depreciation on it + profit (or - loss) on disposal, capped at cost. A car
    # comes out of the pool it went into: the special rate pool when there is one (the firm puts cars there), the
    # main pool otherwise (CAA 2001 s61, s104A); plant, fixtures and computers out of the main pool
    cost_disposed = sum(-bal(cost) for cost, _dep in DISPOSALS.values() if bal(cost) < 0)
    dep_disposed = sum(bal(dep) for _cost, dep in DISPOSALS.values() if bal(dep) > 0)
    proceeds = min(cost_disposed, max(0.0, cost_disposed - dep_disposed - disposals_pl)) if cost_disposed else 0.0
    car_cost = max(0.0, -bal(DISPOSALS["Motor vehicles"][0]))
    in_special = float(tax_inputs.get("special_pool_bf") or 0) + shares["SPECIAL"] > 0
    car_proceeds = round(proceeds * car_cost / cost_disposed, 2) if cost_disposed and in_special else 0.0
    if proceeds:
        c.notes.append(f"Disposal proceeds of about £{proceeds:,.2f} were worked out from the disposal accounts "
                       f"(cost less depreciation, plus profit or less loss); use the actual sale price if known.")

    # Writing-down allowances: main pool rate 18% before 1 April 2026, 14% from then (time-apportioned)
    # A period that crosses 1 April 2026 gets the hybrid rate by days, rounded up to two decimal places of a percent
    # (CA23222); 18% for the whole period would claim more than the law allows (CA23220), so it is not a choice
    before = (min(period_end, date(2026, 3, 31)) - period_start).days + 1 if period_start <= date(2026, 3, 31) else 0
    main_rate = (MAIN_POOL_WDA_BEFORE_APRIL_2026 * before + p.get("P-WDA-MAIN", 0.14) * (days - before)) / days
    main_rate = math.ceil(round(main_rate * 10000, 6)) / 10000
    main_rate *= min(days, 365) / 365
    special_rate = SPECIAL_POOL_WDA * min(days, 365) / 365
    # Cars (not vans, not zero-emission) go to the special rate pool, the firm's rule: the books
    # do not say a car's CO2, and an ordinary petrol or diesel car is above 50g/km
    fya40_rest = round(excess_aia - fya40, 2) if fya40 else 0.0      # into the pool after this period's WDA
    main_pool = (float(tax_inputs.get("main_pool_bf") or 0) + main_additions + (0.0 if fya40 else excess_aia)
                 + aia_unclaimed - (proceeds - car_proceeds))
    special_pool = float(tax_inputs.get("special_pool_bf") or 0) + cars + special_additions - car_proceeds
    if cars:
        c.notes.append(f"Car additions of £{cars:,.2f} put in the special rate pool (6%). A car with CO2 of 50g/km or "
                       f"less goes in the main pool instead; a vehicle registered as a van gets AIA; a new "
                       f"zero-emission car gets 100% first-year allowance.")
    main_bc, special_bc = max(0.0, -main_pool), max(0.0, -special_pool)       # for the H1.2 table
    balancing_charge = 0.0
    if main_pool < 0:
        balancing_charge, main_pool = -main_pool, 0.0
    if special_pool < 0:
        balancing_charge, special_pool = balancing_charge - special_pool, 0.0
    if car_proceeds:
        c.notes.append(f"Car disposal proceeds of about £{car_proceeds:,.2f} taken out of the special rate pool (where the "
                       f"firm puts cars); a car that was in the main pool comes out of the main pool instead.")
    main_wda = main_pool if 0 < main_pool <= SMALL_POOL * min(days, 365) / 365 else main_pool * main_rate
    special_wda = special_pool if 0 < special_pool <= SMALL_POOL * min(days, 365) / 365 else special_pool * special_rate
    # Less than the full writing-down allowance claimed (CAA 2001 s56(5), CA81400): the rest stays in the pool
    for key, label in (("main_wda_claim", "main"), ("special_wda_claim", "special")):
        if tax_inputs.get(key) not in (None, ""):
            full = main_wda if label == "main" else special_wda
            wanted = max(0.0, min(full, float(tax_inputs[key])))
            if wanted < full - 0.005:
                c.notes.append(f"Writing-down allowance on the {label} pool claimed £{wanted:,.2f} of £{full:,.2f} "
                               f"(the accountant's claim, CAA 2001 s56(5)); the rest stays in the pool.")
            if label == "main":
                main_wda = wanted
            else:
                special_wda = wanted
    if main_wda:
        c.capital_allowances.append(CTLine(f"Main pool writing-down allowance ({main_rate:.2%})", round(main_wda, 2), "714"))
    if special_wda:
        c.capital_allowances.append(CTLine(f"Special rate pool writing-down allowance ({special_rate:.2%})", round(special_wda, 2), "714"))
    c.main_pool_cf = round(main_pool - main_wda + fya40_rest, 2)
    # Assets held from last year (cost on the fixed asset codes) and no pool brought forward entered: the allowances
    # on them are missing, a query (CT-CA-003), not a nil
    held_bf = sum(v for code, v in balances.items() if 4120 <= code < 4160 and code % 10 == 0 and v > 0)
    c.pools_missing = held_bf >= 1 and not tax_inputs.get("main_pool_bf") and not tax_inputs.get("special_pool_bf")
    c.special_pool_cf = round(special_pool - special_wda, 2)
    # H1.2: the same figures per pool (nothing new worked out: what the lines above used)
    r2 = lambda v: round(v, 2)
    if sum(aia_items.values()) or zero_emission:
        c.pools.append({"pool": "Annual investment allowance / first-year allowance", "bf": 0.0,
                        "additions": r2(sum(aia_items.values()) + zero_emission - fya40_rest),
                        "aia_fya": r2(aia_claim + zero_emission + fya40), "disposals": 0.0, "balancing_charge": 0.0,
                        "balancing_allowance": 0.0, "wda": 0.0,
                        "cf": 0.0, "note": "AIA over the limit or not claimed goes to the main pool" if
                        (excess_aia or aia_unclaimed) else ""})
    c.pools.append({"pool": "Main pool", "bf": r2(float(tax_inputs.get("main_pool_bf") or 0)),
                    "additions": r2(main_additions + (0.0 if fya40 else excess_aia) + aia_unclaimed + fya40_rest),
                    "aia_fya": 0.0,
                    "disposals": r2(proceeds - car_proceeds), "balancing_charge": r2(main_bc),
                    "balancing_allowance": 0.0, "wda": r2(main_wda), "cf": c.main_pool_cf,
                    "note": f"WDA {main_rate:.2%}"})
    c.pools.append({"pool": "Special rate pool", "bf": r2(float(tax_inputs.get("special_pool_bf") or 0)),
                    "additions": r2(cars + special_additions), "aia_fya": 0.0, "disposals": r2(car_proceeds),
                    "balancing_charge": r2(special_bc), "balancing_allowance": 0.0, "wda": r2(special_wda),
                    "cf": c.special_pool_cf, "note": f"WDA {special_rate:.2%}"})
    allowances = aia_claim + zero_emission + main_wda + special_wda
    add("Less: capital allowances", -allowances, "690")
    if balancing_charge:
        add("Add: balancing charge", balancing_charge, "705")

    trading = adjusted - allowances + balancing_charge
    losses_bf = float(tax_inputs.get("losses_bf") or 0)
    property_profit = rent - property_costs if letting and not whole_property else 0.0
    if whole_property:
        # All the income is rent: the profit after capital allowances is the property business's (box 190)
        property_profit, trading = trading, 0.0
        add("Transfer to property business: all the income is rent", -property_profit, "",
            "CTA 2009 Part 4: costs and capital allowances go against the rent")
    # A trading loss this year is carried forward unless the accountant claims it against this year's other profits
    # or the year before (CTA 2010 s37: a claim, so not assumed); the queries below ask
    c.trading_profit = round(max(trading, 0.0), 2)
    c.trading_loss = round(max(-trading, 0.0), 2)
    if c.trading_loss:
        c.notes.append(f"Trading loss of £{c.trading_loss:,.2f} carried forward. It could instead be set against this "
                       f"year's other profits or carried back 12 months (CTA 2010 s37): confirm the claim.")
    add("Trading profits", c.trading_profit, "155")
    c.property_profit = round(property_profit, 2)
    property_loss = max(0.0, -property_profit)
    total = c.trading_profit + interest + investment_interest + max(0.0, property_profit)
    # A property loss is set against the company's total profits of the same period first (CTA 2010 s62(3)); what is
    # left is carried forward against future total profits (s62(5), PIM4236)
    loss_set_off = round(min(property_loss, max(0.0, total)), 2)
    if property_loss:
        c.property_losses_carried_forward = round(property_loss - loss_set_off, 2)
        c.notes.append(f"Property business loss £{property_loss:,.2f}: £{loss_set_off:,.2f} set against this year's other "
                       f"profits, £{c.property_losses_carried_forward:,.2f} carried forward against future total profits "
                       f"(CTA 2010 s62).")
    # Losses brought forward: from 1 April 2017 against total profits, and the company may claim less than all of
    # them (CTA 2010 s45A, CTM04135); a loss from before April 2017 only against the same trade's profits (s45,
    # tax_inputs.losses_bf_pre2017). The amount claimed is the accountant's when given (tax_inputs.losses_claim)
    pre2017 = float(tax_inputs.get("losses_bf_pre2017") or 0)
    used_pre = round(min(pre2017, c.trading_profit), 2)
    left = max(0.0, total - loss_set_off - used_pre)
    claim = tax_inputs.get("losses_claim")
    used_post = round(min(losses_bf, left, float(claim)) if claim not in (None, "") else min(losses_bf, left), 2)
    c.losses_used = round(used_pre + used_post, 2)
    c.losses_carried_forward = round(pre2017 - used_pre + losses_bf - used_post + c.trading_loss, 2)
    if c.losses_used:
        add("Less: losses brought forward", -c.losses_used, "160",
            "Losses from April 2017 against total profits (CTA 2010 s45A); earlier ones against trading profits (s45)")
    if total > 5000000 and c.losses_used:
        c.notes.append("Profits above £5m: the 50% restriction on brought-forward losses may apply.")
    net_trading = c.trading_profit
    profits = total - loss_set_off - c.losses_used
    # Qualifying charitable donations are relieved when made, i.e. paid (CTA 2010 s189-190): a donation accrued at the
    # year end and unpaid is not; with ledger lines, the paid part of the charge
    relievable = charity if donations_paid is None else max(0.0, min(charity, donations_paid))
    if relievable < charity - 0.005:
        c.notes.append(f"Charitable donations of £{charity - relievable:,.2f} in the accounts were not paid in the "
                       f"period (accrued): no relief until paid (CTA 2010 s189).")
    donations_relief = min(relievable, max(0.0, profits))
    add("Net trading profits", round(net_trading - min(c.losses_used, net_trading), 2), "165")
    if interest + investment_interest:
        add("Non-trade loan relationship profits (interest)", interest + investment_interest, "170")
    if letting:
        add("Property business income", max(0.0, property_profit), "190")
    if loss_set_off:
        add("Less: property business loss of this year", -loss_set_off, "250")
    add("Profits before donations and group relief", profits, "300")
    if donations_relief:
        add("Less: qualifying charitable donations", -donations_relief, "305")
    c.profits_chargeable = round(max(0.0, profits - donations_relief), 2)
    add("Profits chargeable to corporation tax", c.profits_chargeable, "315")

    # Augmented profits leave out dividends from 51% group companies (CTA 2010 s18L, CTM03915)
    augmented = c.profits_chargeable + max(0.0, dividends - float(tax_inputs.get("group_dividends") or 0))
    ct, c.rate_slices = corporation_tax(c.profits_chargeable, augmented, period_start, period_end, associates)
    c.double_tax_relief = round(min(float(tax_inputs.get("double_tax_relief") or 0), ct), 2)
    c.corporation_tax = round(ct - c.double_tax_relief, 2)
    add("Corporation tax", ct, "430")
    if c.double_tax_relief:
        add("Less: double taxation relief", -c.double_tax_relief, "450")
    add("Corporation tax chargeable", c.corporation_tax, "440")

    # s455 on overdrawn director loans, less what was repaid within 9 months of the year end
    # Last year's overdrawn balance carried its own s455 last year: this year's charge is on the increase only
    dla = sum(bal(k) for k in DLA_CODES if k in balances)
    if dla > 0.01:
        repaid = float(tax_inputs.get("dla_repaid_within_9_months") or 0)
        charged_before = max(0.0, dla_opening or 0.0)
        new_loans = max(0.0, dla - charged_before)
        s455 = s455_charge(max(0.0, new_loans - repaid), list(dla_advances))
        c.s455_tax, c.s455_explanation = s455["tax"], s455["explanation"]
        add("s455 tax on overdrawn director loans (CT600A)", c.s455_tax, "A80",
            f"Overdrawn £{dla:,.2f}"
            + (f", less £{charged_before:,.2f} overdrawn last year (s455 charged then)" if charged_before else "")
            + (f", less £{repaid:,.2f} repaid within 9 months" if repaid else ""))
        if charged_before and dla < charged_before:
            c.notes.append(f"The directors' loan fell from £{charged_before:,.2f} to £{dla:,.2f}: s455 paid on last year's "
                           f"balance can be reclaimed for the part repaid (s458), nine months after this year end.")
    c.total_tax = round(c.corporation_tax + c.s455_tax, 2)
    add("Total tax chargeable", c.total_tax, "510")
    if days > 365:
        c.notes.append(f"The period is {days} days: a CT accounting period is at most 12 months, so two returns are "
                       f"needed and this single computation is only an estimate.")
    return c
