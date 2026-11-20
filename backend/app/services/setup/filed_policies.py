"""The client's accounting policies as stated in last year's accounts filed at Companies House.

Depreciation: the policy note of full and small-company accounts states each class's method and rate ('Plant &
Machinery 15% SLM Motor Vehicles 25%SLM ...', 'Plant & Machinery 20% reducing balance'). FRS 102 s10 / s17.23: the
same policy is applied year to year, so it is this year's method and rate unless the accountant changes it. Micro-
entity accounts file no policy note: nothing is read from them.
"""
import json
import re
from datetime import date
from typing import Any, Dict, Optional

# Where the depreciation note lists its classes
POLICY_START = re.compile(r"depreciation is (provided|charged|calculated)|on the following bases|at the following "
                          r"(annual )?rates|useful (economic )?lives? as follows", re.I)
POLICY_WINDOW = 700

# A class's rate: 'Plant & Machinery 20% SLM', 'Motor vehicles - 25% reducing balance', 'Computers 33% on cost'
ITEM = re.compile(r"(?P<name>[A-Za-z][A-Za-z &,'/()-]{2,60}?)\s*[-:–]?\s*(?P<rate>\d{1,3}(?:\.\d+)?)\s*%\s*"
                  r"(?P<method>SLM|S/L|SL\b|RBM|RB\b|straight[- ]line|reducing[- ]balance|on cost|on a straight|"
                  r"on reducing|written down|on net book)?", re.I)
# ...or a life: 'Fixtures and fittings over 5 years'
LIFE = re.compile(r"(?P<name>[A-Za-z][A-Za-z &,'/()-]{2,60}?)\s*[-:–]?\s*(over\s+)?(?P<years>\d{1,2})\s*years", re.I)
STRAIGHT = re.compile(r"^(slm|s/l|sl|straight|on cost|on a straight)", re.I)
REDUCING = re.compile(r"^(rbm|rb|reducing|on reducing|written down|on net book)", re.I)
BASIS_STRAIGHT = re.compile(r"straight[- ]line basis|on cost\b|straight line method", re.I)
BASIS_REDUCING = re.compile(r"reducing balance basis|reducing balance method", re.I)

# Class by the words of its name, the more particular first
CLASSES = [("Computers", re.compile(r"computer|\bit equipment|\bit hardware", re.I)),
           ("Motor vehicles", re.compile(r"motor|vehicle|\bvans?\b|\bcars?\b", re.I)),
           ("Fixtures and fittings", re.compile(r"fixture|fitting|furniture|office equipment", re.I)),
           ("Plant and machinery", re.compile(r"plant|machinery|equipment|tools", re.I)),
           ("Leasehold property", re.compile(r"leasehold|improvements? to (the )?property|property improvements", re.I)),
           ("Freehold property", re.compile(r"freehold|land and buildings|land & buildings|buildings", re.I))]


def _class(name: str) -> Optional[str]:
    return next((cls for cls, words in CLASSES if words.search(name)), None)


def depreciation_policy(text: str) -> Dict[str, Dict[str, Any]]:
    """{asset class: {method, rate}} from the filed accounts' depreciation note; {} when the note is not there. A
    class whose method the note does not say (a rate alone, and no basis stated for all) is left out."""
    m = POLICY_START.search(text or "")
    if not m:
        return {}
    window = text[m.start(): m.start() + POLICY_WINDOW]
    basis = ("STRAIGHT_LINE" if BASIS_STRAIGHT.search(window) and not BASIS_REDUCING.search(window) else
             "REDUCING_BALANCE" if BASIS_REDUCING.search(window) and not BASIS_STRAIGHT.search(window) else None)
    out: Dict[str, Dict[str, Any]] = {}
    for item in ITEM.finditer(window):
        cls = _class(item.group("name"))
        if cls is None or cls in out:
            continue
        rate = float(item.group("rate"))
        word = item.group("method") or ""
        method = "STRAIGHT_LINE" if STRAIGHT.search(word) else "REDUCING_BALANCE" if REDUCING.search(word) else basis
        if method is None or not 0 < rate <= 100:
            continue
        out[cls] = {"method": method, "rate": round(100 / 3, 2) if rate in (33.0, 33.3, 33.33) else rate}
    for item in LIFE.finditer(window):
        cls = _class(item.group("name"))
        years = int(item.group("years"))
        if cls is None or cls in out or not 1 <= years <= 60:
            continue
        out[cls] = {"method": "STRAIGHT_LINE", "rate": round(100 / years, 2)}
    return out


def filed_depreciation(profile, before: date) -> Dict[str, Any]:
    """{'classes': {...}, 'made_up_to': 'YYYY-MM-DD'} from last year's filed accounts, read once and kept on the
    client's Companies House record (profile.companies_house); {} when there is no company number, no iXBRL accounts,
    or no policy note. The caller saves the profile."""
    from backend.app.services.setup import companies_house as ch
    if profile is None or not getattr(profile, "companies_house", None):
        return {}
    try:
        register = json.loads(profile.companies_house)
    except (TypeError, ValueError):
        return {}
    kept = register.get("filed_policy")
    if isinstance(kept, dict) and kept.get("before") == before.isoformat():
        return kept.get("depreciation") or {}
    number = register.get("company_number")
    if not number:
        return {}
    try:
        text, made_up = ch.filed_accounts_text(number, before)
    except Exception:
        return {}                         # not reachable now: asked again next time
    found = {"classes": depreciation_policy(text or ""), "made_up_to": made_up.isoformat() if made_up else None}
    found = found if found["classes"] else {}
    register["filed_policy"] = {"before": before.isoformat(), "depreciation": found}
    profile.companies_house = json.dumps(register)
    return found
