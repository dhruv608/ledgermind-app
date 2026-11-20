"""VAT code consistency in the ledger, VAT test V-A04: one supplier's lines on an account should carry one VAT code.

The VAT on a supply follows the supply, not the account (VAT Notice 700 s8; VATA 1994 s8: services from an overseas
supplier are reverse charged), so one account can rightly hold several codes: UK software at 20% and an overseas
subscription reverse charged. The same supplier on the same account usually supplies the same thing at the same rate,
so the check is per supplier within an account: a line whose code differs from that supplier's usual code is listed
to check against the invoice (VAT claimed that was not charged, or VAT missed)."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Optional, Tuple

from backend.app.services.cis.cash import contact_of

RATE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# A placeholder, not a supplier: Xero writes 'No Name' when a line has no contact (card lines often have none)
NO_SUPPLIER = re.compile(r"^(no name|unknown|various|sundry|sundries|cash|n/?a|none|-)$", re.I)
MIN_LINES = 3                    # a supplier with fewer coded lines on the account has no 'usual' code
SHOWN = 10                       # suppliers written out in the point


def vat_rate(code: str) -> Optional[float]:
    """The rate a VAT code names ('20% (VAT on Expenses)' 20, '20.0% S' 20, 'No VAT' 0, 'Exempt' 0); None when it names
    none ('RC SG' alone)."""
    m = RATE.search(code or "")
    if m:
        return float(m.group(1))
    return 0.0 if re.search(r"no vat|exempt|zero|out of scope|outside|non.?vat", code or "", re.I) else None


@dataclass
class OddLine:
    when: Optional[date]
    description: str
    net: float
    code: str


@dataclass
class SupplierMix:
    account: str
    supplier: str
    usual: str
    usual_lines: int
    odd: List[OddLine] = field(default_factory=list)

    @property
    def rate_differs(self) -> bool:
        """VAT charged on one and not the other (money at stake), not two names for nil VAT."""
        usual = vat_rate(self.usual)
        return any((vat_rate(o.code) or 0.0) != (usual or 0.0) for o in self.odd)


def _clean(code: str) -> str:
    return re.sub(r"\s+", " ", str(code or "")).strip()


def supplier_mixes(lines: Iterable[Tuple[str, str, Optional[date], float, str]]) -> List[SupplierMix]:
    """lines: (account, description, date, net, VAT code) for the P&L lines. Each supplier (the contact before ' - ')
    with MIN_LINES or more coded lines on one account whose codes differ: its usual code (the most used, when one is
    used more than any other) and the lines coded otherwise. A line with no code is not judged (payments carry none)."""
    groups = defaultdict(list)
    shown = {}                           # the supplier as the ledger first writes it
    for account, description, when, net, code in lines:
        code, supplier = _clean(code), contact_of(description)
        if not code or not supplier or NO_SUPPLIER.match(supplier) or abs(net) < 0.005:
            continue
        when = when if isinstance(when, date) and when == when else None      # NaT is a date that is not itself
        plain = re.sub(r"^\s*payment\s*:\s*", "", description, flags=re.I)
        shown.setdefault(supplier, re.sub(r"\s+", " ", plain.split(" - ")[0]).strip())
        groups[(account, supplier)].append(OddLine(when, description, round(net, 2), code))
    out: List[SupplierMix] = []
    for (account, supplier), items in groups.items():
        if len(items) < MIN_LINES:
            continue
        counts = Counter(i.code for i in items).most_common()
        if len(counts) < 2 or counts[0][1] == counts[1][1]:
            continue                     # one code, or no usual code to judge the others by
        usual = counts[0][0]
        out.append(SupplierMix(account, shown.get(supplier, supplier), usual, counts[0][1],
                               [i for i in items if i.code != usual]))
    return sorted(out, key=lambda m: (not m.rate_differs, -sum(abs(o.net) for o in m.odd)))


def describe(mixes: List[SupplierMix]) -> Tuple[str, str, float, str]:
    """(title, details, amount, severity) of the one point that lists them."""
    amount = round(sum(abs(o.net) for m in mixes for o in m.odd), 2)
    money = [m for m in mixes if m.rate_differs]
    parts = []
    for m in mixes[:SHOWN]:
        odd = ", ".join(f"{o.when.strftime('%d/%m/%Y') if o.when else 'no date'} £{abs(o.net):,.2f} '{o.code}'"
                        for o in m.odd[:4]) + (f" and {len(m.odd) - 4} more" if len(m.odd) > 4 else "")
        parts.append(f"{m.account}: {m.supplier} {m.usual_lines} line(s) '{m.usual}', otherwise {odd}")
    more = f" ({len(mixes) - SHOWN} more supplier(s) not shown.)" if len(mixes) > SHOWN else ""
    title = f"VAT codes: {len(mixes)} supplier(s) coded more than one way on the same account"
    details = (
        "The same supplier on the same account usually supplies at the same VAT rate, so a line with a different VAT "
        "code from the supplier's other lines is checked against its invoice: VAT claimed that was not charged, or "
        "VAT missed. " + "; ".join(parts) + "." + more + " A different code can be right (a different item, an "
        "overseas supply reverse charged, VATA 1994 s8); correct the code where the invoice shows it is wrong (the "
        "VAT records must show the VAT on each supply, VAT Regulations 1995 reg 31). Client question: "
        + ", ".join(m.supplier for m in (money or mixes)[:3]) + " coded at different VAT rates: please confirm whether "
        "its supplies are mixed-rate.")
    return title, details, amount, "LOW"
