"""The kind of entity a client is, where the law treats it differently from a company.

An LLP (Limited Liability Partnerships Act 2000) is tax-transparent: its trade is treated as carried on by its members
in partnership, who are taxed on their profit shares (CTA 2009 s1273, ITTOIA 2005 s863), so it pays no corporation tax.
It has no shares, so no share capital and no dividends; it is not a close company, so no s455 charge on loans to
members. Told by its name ('... LLP', 'Limited Liability Partnership') or its Companies House number (OC, SO, NC)."""

import json
import re

LLP_NAME = re.compile(r"\bL\.?L\.?P\.?\b|limited liability partnership", re.I)
LLP_NUMBER = re.compile(r"^(OC|SO|NC)\d{6}$", re.I)


def is_llp(engagement, profile=None) -> bool:
    if engagement is not None and LLP_NAME.search(engagement.client_name or ""):
        return True
    try:
        register = json.loads(getattr(profile, "companies_house", None) or "{}") if profile is not None else {}
    except ValueError:
        register = {}
    return bool(LLP_NUMBER.match(str(register.get("company_number") or "").strip()))


# Review points that only apply to a company: dividends and the s455 charge on an overdrawn director's loan
COMPANY_ONLY_REFS = ("U-DIV-", "U-DLA-001", "U-DLA-002")    # dividends, s455, a beneficial loan to an employee
