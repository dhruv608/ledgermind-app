"""Foreign amounts in pounds: every SA106 entry is in sterling (HS264, the SA106 notes). The rate is HMRC's published
average for the year to 31 March, the period nearest the tax year (BIM39505; parameters/fx_rates.json), and every
converted figure says which rate it used, so the accountant can use the rate on the day instead where that is fairer."""

import json
from pathlib import Path
from typing import Dict, Optional

RATES = json.loads((Path(__file__).parent / "parameters" / "fx_rates.json").read_text(encoding="utf-8"))


def rate(currency: Optional[str], tax_year: str) -> Optional[float]:
    """Units of the currency per £1 for the year (None: not in the table, or not a currency)."""
    c = (currency or "").upper().strip()
    if c in ("", "GBP"):
        return 1.0 if c == "GBP" else None
    return (RATES.get(tax_year) or {}).get("per_gbp", {}).get(c)


def to_gbp(amount: float, currency: Optional[str], tax_year: str) -> Optional[Dict]:
    """{gbp, rate, basis} for an amount in a foreign currency, or None when there is no rate for it."""
    r = rate(currency, tax_year)
    if not r:
        return None
    period = (RATES.get(tax_year) or {}).get("period", "")
    return {"gbp": round(amount / r, 2), "rate": r,
            "basis": f"{(currency or '').upper()} {r} to £1, HMRC average {period}" if currency.upper() != "GBP" else "pounds"}
