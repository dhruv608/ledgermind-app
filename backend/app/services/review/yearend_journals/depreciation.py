"""Depreciation from the fixed asset register: register headings matched to the firm's classes, rates and months
held, and the charge proposed against what the books hold."""

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, FixedAssetRecord, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.review.setup_checks import ASSET_CLASS_CODES, setup_of
from backend.app.services.review.yearend_journals.common import (DEPRECIATION_PL, FAR_CLASS, MIN_AMOUNT,
                                                                REGISTER_TOLERANCE, _entry, _journal, _point)

# ---------------------------------------------------------------------------------------------------------------
# Depreciation from the fixed asset register
# ---------------------------------------------------------------------------------------------------------------
def _far_class(category: str, held: Dict[str, float], merged: Optional[Dict[str, str]] = None) -> Optional[str]:
    """The firm class for a register heading. A heading that fits several ('Office equipment': fixtures or plant)
    goes to the one where this client's TB holds the cost. A class the books keep under another class's codes
    (merged_classes) goes to that class."""
    fits = [cls for pattern, cls in FAR_CLASS if pattern.search(category or "")]
    cls = next((cls for cls in fits if abs(held.get(cls, 0.0)) >= MIN_AMOUNT), fits[0] if fits else None)
    return (merged or {}).get(cls, cls)


def merged_classes(far: List[FixedAssetRecord], tb_records: List[TBRecord], after: Dict[int, float]) -> Dict[str, str]:
    """Register classes the books keep under another class's codes: {register class: books class}. A register class
    the books hold nothing for, whose cost at the start of the year makes up exactly what another class's register
    cost is short of that class's books cost (e.g. the register's fixtures + plant = the books' plant on 4120). Their
    assets stay in the register asset by asset, each depreciated at its own rate (FRS 102 s17: parts with different
    lives are depreciated separately), and the charge goes to the books' class."""
    from itertools import combinations
    held = {cls: sum(abs(after.get(c, 0.0)) for c in codes["cost"]) for cls, codes in ASSET_CLASS_CODES.items()}
    opening = {cls: sum(float(t.opening_amount or 0) for t in tb_records if t.std_code in codes["cost"])
               for cls, codes in ASSET_CLASS_CODES.items()}
    reg: Dict[str, float] = {}
    for a in far:
        cls = _far_class(a.category, held)
        if cls in ASSET_CLASS_CODES:
            reg[cls] = reg.get(cls, 0.0) + float(a.cost_bwd or 0)
    orphans = [c for c, v in reg.items() if v >= MIN_AMOUNT and held.get(c, 0.0) < MIN_AMOUNT
               and abs(opening.get(c, 0.0)) < MIN_AMOUNT]
    out: Dict[str, str] = {}
    for target in ASSET_CLASS_CODES:
        if target in orphans or held.get(target, 0.0) < MIN_AMOUNT:
            continue
        gap = round(opening[target] - reg.get(target, 0.0), 2)
        if abs(gap) <= REGISTER_TOLERANCE:
            continue                                        # the register already agrees to the books
        free = [o for o in orphans if o not in out]
        match = next((combo for n in range(1, len(free) + 1) for combo in combinations(free, n)
                      if abs(sum(reg[o] for o in combo) - gap) <= REGISTER_TOLERANCE), None)
        for o in match or ():
            out[o] = target
    return out


def _rate(text: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    """'20% SLM' -> (20.0, 'STRAIGHT_LINE'); '25% RBM' -> (25.0, 'REDUCING_BALANCE')."""
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*%\s*([A-Za-z]*)", text or "")
    if not m:
        return None, None
    method = "REDUCING_BALANCE" if m.group(2).upper().startswith(("RB", "RED")) else "STRAIGHT_LINE"
    return float(m.group(1)), method


def _months_held(when: Optional[date], year_end: date, rule: str = "FULL_YEAR") -> int:
    """Months charged in the year of purchase, by the client's policy (setup, Policies): a full year (the firm's rule:
    a full year in the year of purchase, none in the year of sale), from the month of purchase
    (bought 25 Sep, year end 31 Jan: Sep to Jan = 5) or from the next month (bought 17 Feb, year end 31 May: Mar to
    May = 3). A full year too when the date is unknown."""
    if rule == "FULL_YEAR" or when is None or when > year_end:
        return 12
    months = (year_end.year - when.year) * 12 + year_end.month - when.month + (1 if rule != "NEXT_MONTH" else 0)
    return max(0, min(12, months))


def register_unreliable_classes(far: List[FixedAssetRecord], tb_records: List[TBRecord],
                                after: Dict[int, float], merged: Optional[Dict[str, str]] = None) -> set:
    """The asset classes whose depreciation the register cannot give: the books hold the class and the register has
    none of it, or the register's cost at the start of the year differs from the books' (an asset filed
    under another class, e.g. a bike under motor vehicles in the register and in plant in the books). The books'
    classes are followed, so those classes are worked from the books (setup_checks.depreciation_points)."""
    held = {cls: sum(abs(after.get(c, 0.0)) for c in codes["cost"]) for cls, codes in ASSET_CLASS_CODES.items()}
    reg: Dict[str, float] = {}
    for a in far:
        cls = _far_class(a.category, held, merged)
        if cls in ASSET_CLASS_CODES:
            reg[cls] = reg.get(cls, 0.0) + float(a.cost_bwd or 0)
    out = set()
    for cls, codes in ASSET_CLASS_CODES.items():
        # Cost, not book value: a different depreciation brought forward is the books' own error, and the register's
        # charge is still right
        books = sum(float(t.opening_amount or 0) for t in tb_records if t.std_code in codes["cost"])
        if cls not in reg:
            if held.get(cls, 0.0) >= MIN_AMOUNT:
                out.add(cls)
        elif abs(reg[cls] - books) > max(REGISTER_TOLERANCE, 0.02 * abs(books)):
            out.add(cls)
    return out


def far_depreciation(engagement: ClientEngagement, profile: Optional[ClientProfile], tb_records: List[TBRecord],
                     chart: ChartLookup, counter: List[int], after: Dict[int, float], far: List[FixedAssetRecord],
                     additions_dated: Dict[int, List[Tuple[Optional[date], float]]], skip: Optional[set] = None,
                     merged: Optional[Dict[str, str]] = None) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """Per asset class: the register's charge for the assets it lists, plus the TB's additions not in the register at
    the class rate for the months held (from the ledger dates on the additions account), against the charge already
    booked on the class's 'charge in year' account. The difference is proposed as Dr 3400 / Cr the class charge."""
    policies = setup_of(profile).get("policies") or {}
    rates = policies.get("depreciation") or {}
    # The client's own rule, else the firm's (Firm settings page)
    from sqlalchemy.orm import object_session
    from backend.app.services.review.setup_checks import firm_depreciation_settings
    rule = policies.get("additions_from") or firm_depreciation_settings(
        object_session(profile) if profile is not None else None)["additions_from"]
    held = {cls: sum(abs(after.get(c, 0.0)) for c in codes["cost"]) for cls, codes in ASSET_CLASS_CODES.items()}
    by_class: Dict[str, Dict[str, float]] = {}
    # The class's own assets first, so its rate (for additions the register does not list) is its own, not that of
    # a class the books keep under its codes
    own_first = sorted(far, key=lambda a: _far_class(a.category, held) != _far_class(a.category, held, merged))
    for a in own_first:
        cls = _far_class(a.category, held, merged)
        if cls is None or cls not in ASSET_CLASS_CODES:
            continue                         # intangibles: register v books only (far_books_check)
        c = by_class.setdefault(cls, {"charge": 0.0, "additions": 0.0, "rate": None, "method": None, "cost": 0.0,
                                      "assets": []})
        c["assets"].append(a)
        c["charge"] += float(a.depr_charge or 0)
        c["additions"] += float(a.additions or 0)
        c["cost"] += float(a.cost_fwd or 0) or (float(a.cost_bwd or 0) + float(a.additions or 0) - float(a.disposals or 0))
        rate, method = _rate(a.depr_rate_method)
        if rate and c["rate"] is None:
            c["rate"], c["method"] = rate, method
    findings, journals = [], []
    for cls, c in by_class.items():
        if skip and cls in skip:
            continue                     # the register and the books disagree on this class: worked from the books
        codes = ASSET_CLASS_CODES[cls]
        add_code, charge_bs = codes["cost"][1], codes["bs"]
        if c["rate"] is None:
            r = rates.get(cls) or {}
            c["rate"], c["method"] = (float(r["rate"]) if r.get("rate") else None), r.get("method")
        # No charge for the year in the register: worked by each asset's rate (else the class's), straight line on cost
        # or reducing balance on the value brought forward, this year's additions for the months held, nothing on an
        # asset sold in the year, never below nil (a full year when bought, none when sold)
        by_policy = False
        if abs(c["charge"]) < MIN_AMOUNT and c["rate"]:
            worked = 0.0
            for a in c["assets"]:
                if float(a.disposals or 0) > 0:
                    continue
                rate, method = _rate(a.depr_rate_method)
                rate, method = (rate, method) if rate else (c["rate"], c["method"])
                cost_bf, added = float(a.cost_bwd or 0), float(a.additions or 0)
                value_bf = max(0.0, cost_bf - float(a.depr_bwd or 0))
                base = cost_bf if method == "STRAIGHT_LINE" else value_bf
                months = _months_held(a.acquisition_date, engagement.period_end_date, rule) if added else 12
                charge = base * rate / 100 + added * rate / 100 * months / 12
                worked += min(charge, value_bf + added)
            if worked >= MIN_AMOUNT:
                c["charge"], by_policy = round(worked, 2), True
        # This year's additions in the TB that the register does not list yet, charged for the months held: the
        # additions account, plus this year's movement on the cost account (a TB of movements often posts purchases
        # straight to cost)
        cost_code = codes["cost"][0]
        cost_opening = sum(float(t.opening_amount or 0) for t in tb_records if t.std_code == cost_code)
        cost_movement = after.get(cost_code, 0.0) - cost_opening if any(
            t.opening_amount is not None for t in tb_records if t.std_code == cost_code) else 0.0
        tb_additions = round(after.get(add_code, 0.0) + max(cost_movement, 0.0), 2)
        new = round(tb_additions - c["additions"], 2)
        addition_charge, months_note = 0.0, ""
        if new >= MIN_AMOUNT and c["rate"]:
            dated = [(d, amt) for d, amt in additions_dated.get(add_code, []) + additions_dated.get(cost_code, [])
                     if amt > 0]
            total_dated = sum(amt for _, amt in dated)
            if dated and total_dated > 0:
                # The ledger's purchase lines, scaled to the additions not yet in the register
                for d, amt in dated:
                    months = _months_held(d, engagement.period_end_date, rule)
                    addition_charge += new * (amt / total_dated) * c["rate"] / 100 * months / 12
                held = sorted({_months_held(d, engagement.period_end_date, rule) for d, _ in dated})
                months_note = f" for {', '.join(str(m) for m in held)} month(s) held"
            else:
                addition_charge = new * c["rate"] / 100
                months_note = " for a full year (no purchase date in the ledger)"
        expected = round(c["charge"] + addition_charge, 2)
        booked = round(-after.get(charge_bs, 0.0), 2)           # the charge sits as a credit on the class's charge account
        if booked <= -REGISTER_TOLERANCE:
            # A debit on the charge account is not this year's depreciation: it takes accumulated depreciation down
            # (the books' brought forward corrected to the register). Topping it up would
            # charge last year's difference to this year's profit; a prior period correction goes through reserves
            # when material, this year's profit when not (FRS 102 s10): the accountant's call, not a journal
            findings.append(_point(
                engagement, "U-FA-007", f"Fixed assets: {cls.lower()} depreciation reduced in the books",
                f"{cls}: £{-booked:,.2f} debited to {charge_bs} {chart.name(charge_bs)} this year",
                f"The books take £{-booked:,.2f} off this year's {cls.lower()} depreciation ({charge_bs}): usually a "
                f"correction of the depreciation brought forward, not this year's charge. This year's charge is "
                f"worked from the register on its own (below). Decide where the correction belongs: opening reserves "
                f"if it is a material error in last year's figures, this year's profit if it is small (FRS 102 s10).",
                -booked, ""))
            booked = 0.0
        diff = round(expected - booked, 2)
        if abs(diff) < REGISTER_TOLERANCE:
            continue
        working = ((f"no charge in the register, worked at the rate: £{c['charge']:,.2f}" if by_policy else
                    f"register charge £{c['charge']:,.2f}")
                   + (f" + additions £{new:,.2f}"
                      + (f" at {c['rate']:g}%" if c.get("rate") is not None else " (no rate in the register or setup)")
                      + f"{months_note} = £{addition_charge:,.2f}" if new >= MIN_AMOUNT else ""))
        # Never more depreciation than the cost the books hold: the register can list assets the books do not have
        # (bought through repairs, suspense or another code). Charging for them would take the NBV below nil
        books_cost = round(sum(after.get(code, 0.0) for code in codes["cost"]), 2)
        books_nbv = round(books_cost + sum(after.get(code, 0.0) for code in codes["acc"]), 2)   # depreciation is a credit
        if diff > 0 and diff > books_nbv + REGISTER_TOLERANCE:
            missing = round(c["cost"] - books_cost, 2)
            allowed = round(max(0.0, books_nbv), 2)
            f = _point(engagement, "U-FA-006", f"Fixed assets: {cls.lower()} in the register, not in the books",
                       f"{cls}: the register's assets cost £{c['cost']:,.2f}, the books £{books_cost:,.2f}",
                       f"The fixed asset register holds {cls.lower()} costing £{c['cost']:,.2f}, but the fixed asset "
                       f"accounts hold £{books_cost:,.2f}"
                       + (f" (£{missing:,.2f} missing)" if missing >= MIN_AMOUNT else "") + ". Its depreciation "
                       f"({working}: £{diff:,.2f} still to book) would take the net book value below nil. Find where "
                       f"the missing assets were posted (repairs, suspense, another expense, a different asset code, or "
                       f"an account not yet mapped to fixed assets) and move them to cost; "
                       + (f"£{allowed:,.2f} of the depreciation is proposed now, the rest once the cost is in the books."
                          if allowed >= MIN_AMOUNT else "the depreciation is proposed once the cost is in the books.")
                       + " Client question: Please confirm where the assets in the register were recorded.",
                       abs(missing) if missing >= MIN_AMOUNT else diff, "", severity="HIGH")
            findings.append(f)
            if allowed < MIN_AMOUNT:
                continue
            diff = allowed
            working += f"; limited to the net book value in the books £{allowed:,.2f}"
        dr, cr = (DEPRECIATION_PL, charge_bs) if diff > 0 else (charge_bs, DEPRECIATION_PL)
        entry = _entry(dr, cr, abs(diff), chart)
        f = _point(engagement, "U-FA-005", f"Depreciation: {cls.lower()} (asset register)",
                   f"{cls}: depreciation £{expected:,.2f} per the asset register, £{booked:,.2f} in the books",
                   f"Worked from the fixed asset register: {working}. The books show £{booked:,.2f}. A journal is "
                   f"proposed (Journals tab): {entry}.", abs(diff), entry)
        from backend.app.services.review.point_figures import amounts as _amounts
        f.figures = _amounts([("Register charge" if not by_policy else "Worked at the rate", c["charge"])]
                             + ([("On this year's additions", addition_charge)] if new >= MIN_AMOUNT else [])
                             + [("Depreciation per the register", expected), ("Depreciation in the books", booked),
                                ("Difference", expected - booked, True)])
        findings.append(f)
        journals.append(_journal(engagement, counter, f"Depreciation of {cls.lower()} (asset register)",
                                 dr, cr, abs(diff), chart, f))
    return findings, journals
