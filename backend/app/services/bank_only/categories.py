"""
Raw data route: what a Dext category ('Travel And Subsistence', 'Directors Current Account') or a head the accountant
already wrote on a bank statement ('Purchases', 'DLA', 'Fuel') means in the firm's chart. The accountant takes Dext's
category as the starting head and checks it; a bill in 'Directors Current
Account' was paid by the director personally: the cost goes by its nature and the director's loan is credited, it is
never a trade creditor.
"""

import re
from typing import Optional

SALES, DIRECTORS_LOAN = 0, 5400
PURCHASES, MATERIALS = 1100, 1400

# Words in the category or head -> firm code. First match wins, so the narrower words come first.
CATEGORY_CODES = [
    (r"director|\bdla\b|owner|personal", DIRECTORS_LOAN),
    (r"corporation tax|\bct\b", 5310),
    (r"computer equipment|asset.*computer|laptop|\bpc\b", 4151),
    (r"office equipment|asset.*office|fixtures|furniture", 4141),
    (r"asset.*(plant|machinery|equipment)|plant and machinery", 4121),
    (r"motor vehicle|asset.*vehicle", 4131),
    (r"\bincome\b|\bsales?\b|takings|turnover", SALES),
    (r"subcontract", 3020),
    (r"travel|subsistence|hotel|mileage", 3081),
    (r"telephone|broadband|mobile|telecom|internet", 3290),
    (r"accountan|bookkeep", 3301),
    (r"bank charge|bank fee", 3351),
    (r"website|web hosting|domain", 3293),
    (r"software|it and computer|computer expense|it costs|computer", 3240),
    (r"advertis|marketing", 3280),
    (r"professional|legal", 3303),
    (r"insurance", 3260),
    (r"subscription|membership", 3320),
    (r"fuel|motor|vehicle|parking|van", 3230),
    (r"repair|maintenance", 3250),
    (r"\brent\b", 3100),
    (r"\brates\b", 3110),
    (r"clean|waste", 3150),
    (r"security", 3160),
    (r"donation|charit", 3360),
    (r"postage|stationery|printing", 3270),
    (r"office", 3380),
    (r"direct cost|cost of sales", 1780),
    (r"material", MATERIALS),
    (r"purchase|stock|goods", 1100),
    (r"wages|salar", 3000),
    (r"sundry|general expense|tools", 3390),
]
_CATEGORY_CODES = [(re.compile(p, re.I), code) for p, code in CATEGORY_CODES]


def code_for(text: str, materials: int = PURCHASES) -> Optional[int]:
    """The firm code a Dext category or a written head stands for (None: not known, the accountant decides).
    Materials: 1100 Purchases, or 1400 when last year used 1400 (materials: the code for this client)."""
    text = (text or "").strip()
    if not text:
        return None
    for pattern, code in _CATEGORY_CODES:
        if pattern.search(text):
            return materials if code == MATERIALS else code
    return None


def materials_code(last_year: dict) -> int:
    """Materials go to 1100 Purchases, unless last year used 1400 Materials (and not 1100).
    last_year: {code: balance} of last year's TB."""
    used = {c for c, v in last_year.items() if abs(v or 0) >= 0.005}
    return MATERIALS if MATERIALS in used and PURCHASES not in used else PURCHASES


def no_bill_code(last_year: dict, bank_only: bool = False) -> int:
    """Bank payments for goods with no Dext bill: the code last year used; when last year shows neither, 1400
    Materials, but 1100 Purchases for a bank-only client (no Dext at all)."""
    used = {c for c, v in last_year.items() if abs(v or 0) >= 0.005}
    if PURCHASES in used and MATERIALS not in used:
        return PURCHASES
    if MATERIALS in used and PURCHASES not in used:
        return MATERIALS
    return PURCHASES if bank_only else MATERIALS


def paid_by_director(category: str) -> bool:
    """Dext's 'Directors Current Account' (or 'DLA'): the director paid the bill personally."""
    return code_for(category) == DIRECTORS_LOAN
