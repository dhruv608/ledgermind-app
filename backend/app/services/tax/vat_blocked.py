"""Input VAT the ledger claimed where none can be claimed, from the VAT column of each
ledger line, net per firm code:

  V-D06  costs that carry no VAT: insurance and finance are exempt (VATA 1994 Sch 9 groups 2 and 5; HMRC 'VAT rates on
         different goods and services'), business rates, wages, NI, depreciation, penalties and donations are
         outside the scope, and the tax, wages and director's loan accounts are no supply at all. A VAT amount on them
         is a wrong VAT code: the VAT goes back to the cost (and to HMRC on the next return)
  V-D07  cars and fuel (VATA 1994 s24, SI 1992/3222 art 7, VIT50100, VIT55400, VIT55700, Notice 700/64): a car's
         purchase VAT is blocked, half of the VAT on leasing a car used privately is blocked, and road fuel used
         privately needs the fuel scale charge. A van is not blocked, and the ledger does not say which it is: a question

Water rates (business water can carry VAT), card charges (terminal rental is standard rated), postage (couriers
charge VAT) and pensions (a provider's fees carry VAT and are often posted to the pension accounts) are left out. Both points carry a suggested journal for the accountant to post on the answer; none is
proposed, since one bill can mix a VAT-able fee with an exempt premium."""

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

VAT_CONTROL = 5300
NO_VAT_MIN = 5.0      # V-D06: below this, rounding or a fee inside the bill
CARS_MIN = 50.0       # V-D07

NO_VAT_GROUPS: List[Tuple[str, Callable[[int], bool]]] = [
    ("insurance (exempt)", lambda c: c in (3170, 3232) or 3260 <= c <= 3263),
    ("business rates (no VAT)", lambda c: c == 3110),
    ("bank charges and interest (exempt)", lambda c: c == 3351 or 3600 <= c <= 3635),
    ("wages and NI (outside the scope)", lambda c: c in (3000, 3001, 3004, 3010, 3011)),
    ("depreciation (no supply)", lambda c: 3400 <= c <= 3406),
    ("penalties (outside the scope)", lambda c: c == 3391),
    ("donations (outside the scope)", lambda c: c in (3360, 3361)),
    ("tax, wages and director's loan accounts (no supply)", lambda c: c in (5310, 5320, 5330, 5400, 5800)),
]
CAR_LEASE, CAR_COST, CAR_ADDITIONS, FUEL = 3215, 4130, 4131, 3231


def no_vat_group(code: Optional[int]) -> Optional[str]:
    if code is None:
        return None
    return next((name for name, test in NO_VAT_GROUPS if test(code)), None)


@dataclass
class CodeVat:
    code: int
    vat: float = 0.0
    lines: int = 0
    sources: List[str] = field(default_factory=list)


def vat_by_code(rows: Iterable[Tuple[Optional[int], float, str]]) -> Dict[int, CodeVat]:
    """(code, VAT on the line, source) -> net VAT per code (a debit's VAT is +: claimed)."""
    out: Dict[int, CodeVat] = {}
    for code, vat, source in rows:
        if code is None or not vat or abs(vat) < 0.005:
            continue
        c = out.setdefault(code, CodeVat(code))
        c.vat += vat
        c.lines += 1
        if source and len(c.sources) < 3:
            c.sources.append(source)
    for c in out.values():
        c.vat = round(c.vat, 2)
    return out


def _entry(code: int, amount: float, name: Callable[[int], str]) -> str:
    dr, cr = (code, VAT_CONTROL) if amount > 0 else (VAT_CONTROL, code)
    a = abs(amount)
    return f"Dr {dr} {name(dr)} (£{a:,.2f}) / Cr {cr} {name(cr)} (£{a:,.2f})"


@dataclass
class BlockedPoint:
    ref: str
    title: str
    details: str
    amount: float
    journal: str
    sources: List[str]
    severity: str
    # The point's figures as a small table for the screen (review/point_figures.py), when known
    figures: Optional[str] = None


def no_vat_costs(by_code: Dict[int, CodeVat], name: Callable[[int], str],
                 already: Callable[[int], float] = lambda c: 0.0) -> Optional[BlockedPoint]:
    """V-D06: one point listing each account with VAT on it, net of approved journals that moved it already."""
    rows = []
    for code in sorted(by_code):
        group = no_vat_group(code)
        if not group:
            continue
        left = round(by_code[code].vat - already(code), 2)
        if abs(left) >= NO_VAT_MIN:
            rows.append((code, group, left, by_code[code]))
    if not rows:
        return None
    total = round(sum(abs(r[2]) for r in rows), 2)
    listed = "; ".join(f"{code} {name(code)}: {'VAT claimed' if v > 0 else 'VAT charged'} £{abs(v):,.2f} on "
                       f"{c.lines} line(s), {group}" for code, group, v, c in rows)
    journals = "; ".join(_entry(code, v, name) for code, _g, v, _c in rows)
    return BlockedPoint(
        "V-D06", f"VAT of £{total:,.2f} on costs that carry no VAT ({', '.join(str(r[0]) for r in rows)})",
        f"{listed}. Insurance, bank charges and interest are exempt from VAT, and business rates, wages, NI, "
        f"depreciation, penalties, donations and payments to HMRC or the director carry none, so no input VAT can be "
        f"claimed on them (VATA 1994 s24-26, Sch 9; HMRC VAT rates guide). A VAT amount on these lines is a wrong VAT "
        f"code, and if it went on a return HMRC is owed it back (correct on the next return, V-I03). If a bill mixes an "
        f"exempt premium or charge with a VAT-able fee (a broker's admin fee), only the fee's VAT stays. Suggested "
        f"journal: {journals}.", total, journals, [s for r in rows for s in r[3].sources][:3],
        "MEDIUM" if total >= 100 else "LOW",
        _vat_figures(rows, name, total))


def _vat_figures(rows, name, total) -> Optional[str]:
    """V-D06's figures: each account, the lines, the VAT on them."""
    from backend.app.services.review.point_figures import row, table
    return table(["Account", "Lines", "VAT"], [row(f"{code} {name(code)}", str(c.lines), v) for code, _g, v, c in rows]
                 + [row("Total", None, total, strong=True)])


def cars_and_fuel(by_code: Dict[int, CodeVat], name: Callable[[int], str],
                  already: Callable[[int], float] = lambda c: 0.0) -> Optional[BlockedPoint]:
    """V-D07: VAT claimed on vehicles bought or leased and on fuel: a question (car or van, private use)."""
    def left(code: int) -> float:
        return round(by_code[code].vat - already(code), 2) if code in by_code else 0.0
    bought = round(left(CAR_COST) + left(CAR_ADDITIONS), 2)
    lease, fuel = left(CAR_LEASE), left(FUEL)
    total = round(sum(v for v in (bought, lease, fuel) if v > 0), 2)
    if total < CARS_MIN:
        return None
    parts, journals = [], []
    if bought > 0:
        code = CAR_ADDITIONS if CAR_ADDITIONS in by_code else CAR_COST
        parts.append(f"£{bought:,.2f} on vehicles bought ({code} {name(code)}): if a car, the VAT is blocked in full "
                     f"unless it is used only for the business and not available for private use (a taxi, a driving "
                     f"school car or one leased out), so it is part of the car's cost")
        journals.append(f"car bought: {_entry(code, bought, name)}")
    if lease > 0:
        half = round(lease / 2, 2)
        parts.append(f"£{lease:,.2f} on vehicle hire and leasing ({CAR_LEASE} {name(CAR_LEASE)}): if a car leased "
                     f"with any private use, half of the VAT on the rentals is blocked (£{half:,.2f})")
        journals.append(f"car lease, half: {_entry(CAR_LEASE, half, name)}")
    if fuel > 0:
        parts.append(f"£{fuel:,.2f} on fuel ({FUEL} {name(FUEL)}): if the business pays for fuel used privately, it "
                     f"must either account for the fuel scale charge for each car (output VAT), claim only the business "
                     f"mileage's VAT, or claim none")
    return BlockedPoint(
        "V-D07", f"VAT of £{total:,.2f} claimed on vehicles and fuel: cars or vans, and any private use?",
        "VAT claimed in full: " + "; ".join(parts) + ". A van or other commercial vehicle has no block (VATA 1994 "
        "s24, SI 1992/3222 art 7; HMRC VIT50100, VIT55400, VIT55700; Notice 700/64). Query to the client: For each "
        "vehicle the company bought or leased, is it a car or a van, and does anyone use it or its fuel privately? "
        + (f"If cars with private use, post: {'; '.join(journals)}." if journals else ""),
        total, "; ".join(journals), [s for c in (CAR_COST, CAR_ADDITIONS, CAR_LEASE, FUEL) if c in by_code
                                     for s in by_code[c].sources][:3],
        "MEDIUM" if total >= 500 else "LOW")
