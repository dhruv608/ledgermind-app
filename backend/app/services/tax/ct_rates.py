"""Corporation tax by financial year (small profits rate, marginal relief) and the intangible assets rules."""

from datetime import date, timedelta
from typing import Dict, List, Tuple


from backend.app.services.tax.ct_constants import GOODWILL_CHARGE, GOODWILL_COST, MAIN_RATE_FROM, OLD_FLAT_RATE, OTHER_INTANGIBLE_CHARGE, OTHER_INTANGIBLE_COST, tax_parameters
from backend.app.services.tax.ct_model import CTComputation



def _financial_year_slices(start: date, end: date) -> List[Tuple[date, date, int]]:
    """The period cut at each 1 April (UK financial years)."""
    slices, cur = [], start
    while cur <= end:
        next_april = date(cur.year if cur < date(cur.year, 4, 1) else cur.year + 1, 4, 1)
        stop = min(end, next_april - timedelta(days=1))
        slices.append((cur, stop, (stop - cur).days + 1))
        cur = stop + timedelta(days=1)
    return slices


def corporation_tax(profits: float, augmented: float, start: date, end: date, associates: int) -> Tuple[float, List[Dict]]:
    """CT on profits chargeable, financial year by financial year, with marginal relief (CTA 2010 s18A-s18N)."""
    p = tax_parameters()
    small, main = p.get("P-CT-SPR", 0.19), p.get("P-CT-MAIN", 0.25)
    lower_full, upper_full = p.get("P-CT-LOWER", 50000.0), p.get("P-CT-UPPER", 250000.0)
    total_days = (end - start).days + 1
    slices, total = [], 0.0
    for s, e, days in _financial_year_slices(start, end):
        share = days / total_days
        # Each slice's profit to the penny, as H1 works it (ROUND(profits x days / days, 2)), so the tax journal and the
        # computation on H1 agree to the penny
        profit, aug = round(profits * share, 2), round(augmented * share, 2)
        fy_start = date(s.year if s.month >= 4 else s.year - 1, 4, 1)
        year_days = (date(fy_start.year + 1, 4, 1) - fy_start).days      # 365, or 366 with a 29 February
        lower = lower_full * days / year_days / (associates + 1)
        upper = upper_full * days / year_days / (associates + 1)
        if s < MAIN_RATE_FROM:
            rate, relief, how = OLD_FLAT_RATE, 0.0, "19% (before 1 April 2023)"
        elif aug <= lower:
            rate, relief, how = small, 0.0, f"{small:.0%} small profits rate"
        elif aug >= upper:
            rate, relief, how = main, 0.0, f"{main:.0%} main rate"
        else:
            rate = main
            relief = 3 / 200 * (upper - aug) * (profit / aug if aug else 1.0)
            how = f"{main:.0%} less marginal relief"
        tax = profit * rate - relief
        total += tax
        slices.append({"from": s, "to": e, "days": days, "profit": round(profit, 2), "lower": round(lower, 2),
                       "upper": round(upper, 2), "rate": rate, "tax_at_rate": round(profit * rate, 2),
                       "marginal_relief": round(relief, 2), "tax": round(tax, 2), "basis": how})
    return round(total, 2), slices


def _intangibles(c: CTComputation, add, bal, codes: List[int], tax_inputs: Dict) -> None:
    """Amortisation and impairment of intangibles (CTA 2009 Part 8). Goodwill and customer-related
    assets are restricted: no relief for goodwill from before 1 April 2002, none when bought from a related individual
    (on incorporation, s849B), none from 8 July 2015 to 31 March 2019 (s816A), and from 1 April 2019 only 6.5% a year
    when bought with qualifying IP (s879A-s879O). So goodwill's charge is added back and always raises a query. Other
    intangibles (software, patents, trade marks) follow the accounts (s729) once the reviewer confirms they qualify:
    added back until then unless the firm allows them (Firm settings 'intangibles'). The reviewer's confirmed amount
    (client setup, 'amortisation_allowed') is allowed whatever the asset."""
    total = round(sum(bal(k) for k in codes), 2)
    if total < 0.01:
        if total <= -0.01:
            c.notes.append(f"Intangibles show a net credit of £{-total:,.2f} (an impairment reversed): it stays in the "
                           f"profit; take it out if the earlier debits were added back.")
        return
    goodwill = max(0.0, -bal(GOODWILL_CHARGE))
    other = max(0.0, -sum(bal(k) for k in OTHER_INTANGIBLE_CHARGE))
    if goodwill + other < 0.01:
        # The asset side does not say: by which intangibles the company holds (goodwill, or not known: goodwill's rule)
        holds_other = any(abs(bal(k)) >= 0.01 for k in OTHER_INTANGIBLE_COST)
        holds_goodwill = any(abs(bal(k)) >= 0.01 for k in GOODWILL_COST)
        goodwill, other = (0.0, total) if holds_other and not holds_goodwill else (total, 0.0)
    else:
        share = goodwill / (goodwill + other)
        goodwill = round(total * share, 2)
        other = round(total - goodwill, 2)
    confirmed = tax_inputs.get("amortisation_allowed")
    policy = tax_inputs.get("intangibles_policy") or "ADD_BACK"
    if confirmed is not None:
        allowed = min(total, max(0.0, float(confirmed)))
    else:
        allowed = other if policy == "ALLOW" else 0.0
    added = round(total - allowed, 2)
    if added >= 0.01:
        add("Add: amortisation and impairment of intangibles", added, "",
            "CTA 2009 Part 8: goodwill restricted; other intangibles once confirmed",
            codes=codes if allowed < 0.01 else ())
    if confirmed is not None:
        c.notes.append(f"Amortisation and impairment of intangibles: £{allowed:,.2f} allowed as confirmed on the client "
                       f"setup, £{added:,.2f} added back.")
        return
    if goodwill >= 0.01:
        c.goodwill_added_back = goodwill
        c.notes.append(f"Goodwill amortisation / impairment of £{goodwill:,.2f} is added back. Relief for goodwill is "
                       f"restricted (CTA 2009 Part 8): none if it was created before 1 April 2002, bought from a related "
                       f"individual (as on incorporation from the director's own business) or bought from 8 July 2015 "
                       f"to 31 March 2019; from 1 April 2019 only 6.5% a year and only when bought with qualifying IP. "
                       f"Ask when and from whom it was bought, and enter any allowable amount on the client setup "
                       f"(Amortisation confirmed allowable).")
    if other >= 0.01 and policy != "ALLOW":
        c.notes.append(f"Amortisation of other intangibles of £{other:,.2f} is added back until confirmed: software, "
                       f"patents and trade marks created, or bought from an unrelated party, after 1 April 2002 get "
                       f"relief with the accounts (CTA 2009 s729). If it qualifies, enter the amount on the client "
                       f"setup (Amortisation confirmed allowable).")
    elif other >= 0.01:
        c.notes.append(f"Amortisation of other intangibles of £{other:,.2f} is allowed with the accounts (CTA 2009 "
                       f"s729, the firm's setting): add it back if the asset was bought from a related party or before "
                       f"1 April 2002.")
