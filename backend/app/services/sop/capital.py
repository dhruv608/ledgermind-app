"""
Revenue vs capital check: P&L expenses over the capitalisation limit that read like fixed asset purchases, found
with the capital expenditure keywords list.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord
from backend.app.services.sop.common import GLLine, NOT_PREPAYABLE_SECTIONS, PAYROLL_CODES, gl_lines

# Each group of the keywords list, with the fixed asset additions code it points to (None = no particular class)
CAPITAL_KEYWORDS: Dict[str, Tuple[Optional[int], List[str]]] = {
    "Core asset words": (None, [
        "asset", "fixed asset", "capital asset", "capital item", "capital purchase", "capital acquisition",
        "asset acquisition", "asset purchase", "asset addition", "asset register", "asset capitalisation",
        "capitalised cost", "capitalised expenditure", "non-current asset", "long-term asset", "durable asset",
        "tangible asset", "intangible asset", "installation", "commissioning", "setup cost", "initial setup",
        "first-time installation", "replacement unit", "upgrade unit", "system upgrade", "hardware upgrade",
        "equipment upgrade", "asset enhancement", "asset improvement", "capital improvement", "capacity expansion",
        "new installation", "new equipment", "new machinery", "asset build", "asset construction", "asset creation"]),
    "Property, land & buildings": (4111, [
        "land purchase", "freehold property", "leasehold property", "commercial property", "industrial property",
        "warehouse property", "office building", "office premises", "factory building", "shop premises",
        "retail unit", "industrial unit", "business premises", "property acquisition", "building acquisition",
        "property purchase", "building purchase", "construction cost", "building construction", "new build",
        "extension works", "structural works", "structural alteration", "structural modification", "building works",
        "major works", "capital works", "refurbishment", "renovation", "modernisation", "reconfiguration",
        "redevelopment", "fit-out", "fit out", "office fit-out", "shop fit-out", "warehouse fit-out",
        "factory fit-out", "leasehold improvements", "tenant improvements", "landscaping works",
        "permanent fixtures", "permanent installation", "roof replacement", "roofing works", "flooring installation",
        "concrete works", "steel works", "brickwork", "structural steel", "load-bearing works",
        "partition installation", "false ceiling installation", "suspended ceiling", "fire-rated doors",
        "fire protection installation", "partitioning"]),
    "Electrical, mechanical & infrastructure": (4141, [
        "electrical installation", "rewiring", "electrical upgrade", "power upgrade", "distribution board",
        "consumer unit", "electrical panel", "switchgear", "transformer", "generator", "backup generator",
        "ups system", "power backup system", "mechanical installation", "plumbing installation",
        "pipework installation", "water system installation", "drainage installation", "gas installation",
        "boiler installation", "heating system", "central heating system", "hvac system", "hvac",
        "air conditioning system", "air conditioning", "air conditioner", "air handling unit", "ventilation system",
        "extractor system", "extraction unit", "extractor fan", "ducting installation", "refrigeration system",
        "cold storage system", "walk-in freezer", "walk-in fridge", "fire alarm system", "sprinkler system",
        "fire suppression system", "security system", "alarm system", "cctv", "cctv installation",
        "access control system", "biometric system", "turnstile system", "gate automation",
        "roller shutter installation"]),
    "Plant, machinery & industrial equipment": (4121, [
        "plant", "plant and machinery", "machinery", "machine", "equipment", "operational equipment",
        "production equipment", "business equipment", "commercial equipment", "industrial equipment",
        "production line", "manufacturing line", "assembly line", "processing line", "industrial oven",
        "commercial oven", "kiln", "furnace", "compressor", "air compressor", "vacuum pump", "hydraulic system",
        "pneumatic system", "lathe machine", "milling machine", "drilling machine", "cutting machine",
        "laser cutter", "cnc machine", "3d printer", "packaging machine", "labelling machine", "weighing machine",
        "conveyor belt", "material handling system", "forklift", "pallet truck", "reach truck", "stacker", "crane",
        "hoist", "winch", "loading dock equipment", "dock leveller", "racking system", "storage racking",
        "industrial shelving", "heavy duty shelving", "warehouse automation", "robotic arm",
        "automation equipment", "industrial robot", "process control system", "power tools", "tools"]),
    "IT hardware & technology": (4151, [
        "computer", "desktop computer", "desktop", "laptop", "macbook", "workstation", "server", "rack server",
        "blade server", "storage server", "network storage", "nas device", "san storage", "data centre equipment",
        "it hardware", "computer hardware", "hardware", "network equipment", "network hardware", "router",
        "firewall appliance", "load balancer", "wireless access point", "structured cabling", "cat6 cabling",
        "fibre installation", "patch panel", "server rack", "rack cabinet", "it infrastructure", "epos system",
        "pos system", "till system", "payment terminal", "card machine", "biometric reader",
        "time attendance system", "access card system", "printer", "photocopier", "scanner",
        "multifunction printer", "large format printer", "plotter", "barcode scanner", "label printer",
        "display screen", "digital signage", "conference room av", "video conferencing equipment", "projector",
        "interactive display", "smart board", "ipad", "imac", "monitor"]),
    "Office furniture, fixtures & fittings": (4141, [
        "furniture", "office furniture", "office fit-out furniture", "fittings", "desk system", "office desk",
        "bench desk", "bench seating", "office chair", "ergonomic chair", "task chair", "executive chair",
        "conference table", "meeting room table", "boardroom table", "filing cabinet", "pedestal drawer",
        "storage cabinet", "cupboard unit", "shelving unit", "bookcase", "mobile storage", "locker system",
        "reception desk", "reception counter", "waiting area seating", "lounge seating", "partition system",
        "screen divider", "acoustic panels", "soundproof panels", "lighting installation", "led lighting system",
        "emergency lighting", "fixed lighting", "track lighting", "display shelving", "showroom fittings",
        "retail display units", "shelving", "desk", "desks", "chair", "chairs"]),
    "Vehicles & transport": (4131, [
        "motor vehicle", "vehicle", "motor", "car", "company car", "commercial vehicle", "van", "delivery van",
        "panel van", "box van", "refrigerated van", "pickup truck", "lorry", "truck", "hgv", "fleet vehicle",
        "vehicle acquisition", "vehicle purchase", "fleet purchase", "company van", "electric vehicle",
        "hybrid vehicle", "forklift truck", "warehouse vehicle", "industrial vehicle", "construction vehicle",
        "plant vehicle", "vehicle conversion", "vehicle body build", "vehicle fit-out", "vehicle racking",
        "vehicle refrigeration unit", "trailer", "semi-trailer", "flatbed trailer", "tow equipment", "e-bike",
        "registration number"]),
    "Kitchen, catering & hospitality equipment": (4121, [
        "commercial kitchen equipment", "catering equipment", "industrial kitchen", "commercial fridge",
        "commercial freezer", "blast freezer", "upright freezer", "chest freezer", "refrigeration unit",
        "display fridge", "wine cooler", "ice machine", "ice maker", "commercial dishwasher", "glass washer",
        "range cooker", "commercial hob", "grill", "fryer", "deep fat fryer", "combi oven", "commercial microwave",
        "food processor", "planetary mixer", "dough mixer", "coffee machine", "espresso machine",
        "bar equipment", "beer tap system", "cellar cooling system", "extract canopy", "kitchen extraction system",
        "fridge", "freezer", "dishwasher", "oven", "cooker"]),
    "Medical, dental, fitness & specialist equipment": (4121, [
        "medical equipment", "clinical equipment", "diagnostic equipment", "testing equipment",
        "laboratory equipment", "lab installation", "x-ray machine", "ultrasound machine", "mri equipment",
        "dental chair", "dental unit", "dental compressor", "sterilisation unit", "autoclave", "physio equipment",
        "rehabilitation equipment", "gym equipment", "fitness equipment", "treadmill", "cross trainer",
        "exercise bike", "weight machines", "free weights", "sports equipment", "therapy equipment"]),
    "Software & intangible assets": (4011, [
        "perpetual licence", "perpetual license", "enterprise software", "erp system", "crm system",
        "custom software development", "bespoke software", "software implementation", "software configuration",
        "system implementation", "platform development", "application development", "website development",
        "e-commerce platform build", "database development", "software enhancement", "licence acquisition",
        "intellectual property", "ip acquisition", "patent purchase", "trademark acquisition", "trademark",
        "trade mark registration", "software licence", "software license", "website build", "website design and build"]),
    "Purchase phrases seen in bank feeds": (None, [
        "purchase of", "supply and install", "supply & install", "supply & fit", "supply and fit",
        "installation charges", "new unit", "new system", "initial purchase", "first installation",
        "replacement of old", "upgrade of existing", "fit-out works", "equipment supply", "system installation",
        "hardware supply", "machine supply", "delivery and installation", "commissioning charges"]),
}
# Supplier names: an indicator, not proof (keywords list group 11)
CAPITAL_SUPPLIERS: Dict[str, Optional[int]] = {
    "currys": 4151, "dell": 4151, "hp": 4151, "apple": 4151, "lenovo": 4151, "canon": 4151, "ricoh": 4151,
    "xerox": 4151, "cisco": 4151, "ikea": 4141, "john lewis": 4141, "screwfix": 4121, "toolstation": 4121,
    "wickes": 4121, "b&q": 4121, "rs components": 4121, "siemens": 4121, "bosch": 4121, "jcb": 4121,
    "costco": None, "ford": 4131, "mercedes": 4131, "volkswagen": 4131, "toyota": 4131,
}
# Running costs, not assets (the SOP's exclusions, plus hire/lease/finance/parking-type costs)
CAPITAL_EXCLUSIONS = re.compile(
    r"\b(repairs?|servic(e|es|ing)|maintenance|amc|fuel|petrol|diesel|insurance|spare parts?|consumables?|"
    r"hire\w*|rental|rent|lease|leasing|hosting|subscriptions?|finance|loan|parking|mot|valet|car wash|toll|"
    r"instal+ments?|checked over|overheating|fault|novuna|vehicle solutions|vehicle contracts?|inspections?|"
    r"parts|vehicle tax|road tax|dvla)\b",
    re.IGNORECASE)
NOT_CAPITAL_SOURCES = ("journal", "receivable", "receive money", "invoice payment", "payment:")
# Accounts for hiring or running assets (plant hire, vehicle leasing, other vehicle costs): what is posted there pays
# for the use of an asset, never buys one
RUNNING_ACCOUNTS = re.compile(r"\b(hire|leasing|running|vehicle)\b", re.I)
# An expense account named for what is bought as an asset (the client's account name, not the firm's)
ASSET_ACCOUNT = re.compile(r"\b(equipment|computer accessories|computers?|hardware|tools|machinery|furniture|"
                           r"fixtures)\b", re.I)


def _keyword_pattern(words: Iterable[str]) -> "re.Pattern":
    parts = sorted({re.escape(w).replace(r"\ ", r"\s+") + r"(?:e?s)?" for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(parts) + r")(?![a-z0-9])", re.IGNORECASE)


_CAPITAL_GROUPS = [(group, code, _keyword_pattern(words)) for group, (code, words) in CAPITAL_KEYWORDS.items()]
_SUPPLIER_PATTERN = _keyword_pattern(CAPITAL_SUPPLIERS)

FLAG_CAPITAL = ("Expense above £{limit:,.0f} contains asset-related keywords. Review whether this should be "
                "capitalised as a fixed asset instead of expensed.")
CAPITAL_QUESTION = ("Please confirm whether this item is a fixed asset (lasting more than a year) or a running cost, "
                    "and send the purchase invoice.")


@dataclass
class CapitalFlag:
    when: date
    code: int
    account: str
    description: str
    amount: float
    keywords: List[str]
    groups: List[str]
    supplier_only: bool              # matched only on the supplier name: an indicator, not proof
    suggested_code: Optional[int]    # additions code of the asset class the words point to
    by_account: bool = False         # matched on the client's account name ('Computer Hardware', 'Equipment')
    one_off: bool = True             # no other payment of about the same amount on the account in the year


def find_capital_items(lines: Iterable[GLLine], chart: Dict[int, MasterCOA], limit: float) -> List[CapitalFlag]:
    """P&L expenses of at least the capitalisation limit (company policy £500) whose
    description or supplier contains asset words, unless they clearly describe a running cost."""
    flags = []
    lines = list(lines)
    # Payments of about the same amount on each account (within 5%): a cost repeated in the year is not a one-off
    by_account_amounts: Dict[str, List[float]] = {}
    for l in lines:
        if l.debit >= 1:
            by_account_amounts.setdefault(l.account or "", []).append(l.debit)
    for l in lines:
        if l.debit < limit or l.code not in chart or chart[l.code].financial_class != "Profit and Loss":
            continue
        if chart[l.code].category in NOT_PREPAYABLE_SECTIONS or l.code in PAYROLL_CODES:
            continue
        if RUNNING_ACCOUNTS.search(chart[l.code].std_name or ""):
            continue
        if any(s in l.source.lower() for s in NOT_CAPITAL_SOURCES):
            continue
        text = l.description or ""
        if CAPITAL_EXCLUSIONS.search(text):
            continue
        # 'Supplier - what was bought': words in what was bought are the strong signal; words that only appear in
        # the supplier's company name ('... Equipment Ltd') are an indicator, not proof
        supplier_part, _, bought = text.partition(" - ") if " - " in text else ("", "", text)

        def keyword_matches(part: str) -> Tuple[List[str], List[str], List[int]]:
            words, groups, codes = [], [], []
            for group, code, pattern in _CAPITAL_GROUPS:
                found = [m.group(0) for m in pattern.finditer(part)]
                if found:
                    words += found
                    groups.append(group)
                    if code:
                        codes.append(code)
            return words, groups, codes

        keywords, groups, codes = keyword_matches(bought)
        supplier_only = False
        by_account = False
        if not keywords and ASSET_ACCOUNT.search(l.account or ""):
            by_account = True
            # The client's own account says what was bought ('Equipment', 'Computer Accessories') when the line does
            # not: each line over the limit is a capital candidate (a projector or a machine posted to 'Equipment'
            # is capitalised item by item)
            keywords, groups, codes = keyword_matches(l.account or "")
            groups = [f"{g} (in the account's name)" for g in groups] or ["Account named for equipment"]
            keywords = keywords or [ASSET_ACCOUNT.search(l.account or "").group(0)]
            supplier_only = True     # an indicator, not proof: listed for review, never journalled by itself (an
                                     # automatic move on account names alone moves too many real costs)
        if not keywords:
            supplier_only = True
            named = _SUPPLIER_PATTERN.search(supplier_part or text)
            if named:
                code = CAPITAL_SUPPLIERS.get(named.group(0).lower())
                keywords, groups, codes = [named.group(0)], ["Supplier name (indicator, not proof)"], [code] if code else []
            else:
                keywords, groups, codes = keyword_matches(supplier_part)
                groups = [f"{g} (in the supplier's name only)" for g in groups]
            if not keywords:
                continue
        flags.append(CapitalFlag(
            when=l.when, code=l.code, account=l.account, description=text, amount=round(l.debit, 2),
            keywords=sorted({k.lower() for k in keywords}), groups=groups, supplier_only=supplier_only,
            suggested_code=max(set(codes), key=codes.count) if codes else None, by_account=by_account,
            one_off=sum(1 for a in by_account_amounts.get(l.account or "", []) if abs(a - l.debit) <= 0.05 * l.debit) <= 1,
        ))
    flags.sort(key=lambda f: (f.supplier_only, -f.amount))
    return flags


def capital_review(engagement_id: str, tb_records: Iterable[TBRecord], db: Session, limit: float = 500.0) -> List[CapitalFlag]:
    tb_records = list(tb_records)
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    return find_capital_items(gl_lines(engagement_id, tb_records, db), chart, limit)


DEFAULT_LIMIT = 500.0


def firm_capital_limits(db: Optional[Session]) -> Tuple[float, float]:
    """The firm's limits (Firm settings page): general purchases, and equipment (computers, phones, furniture,
    machines) which a firm may capitalise from a lower amount. Not set: £500 for both."""
    if db is None:
        return DEFAULT_LIMIT, DEFAULT_LIMIT
    import json
    from backend.app.models.firm_settings import FirmSetting
    row = db.get(FirmSetting, "capital_limits")
    try:
        saved = json.loads(row.value) if row is not None else {}
    except ValueError:
        saved = {}
    general = float(saved.get("general") or DEFAULT_LIMIT)
    return general, float(saved.get("equipment") or general)


def capitalisation_limit(engagement: ClientEngagement) -> float:
    """Items at or above this are reviewed as possible fixed assets: the client's own limit when the accountant set it
    (Client details), else the firm's general limit, else £500."""
    from sqlalchemy.orm import object_session
    from backend.app.services.setup.profile_service import confirmed_fields
    profile = getattr(engagement, "profile", None)
    if profile is not None and "capitalisation_threshold" in confirmed_fields(profile) and profile.capitalisation_threshold:
        return float(profile.capitalisation_threshold)
    return firm_capital_limits(object_session(engagement))[0]


def equipment_limit(engagement: ClientEngagement) -> float:
    """Equipment is reviewed from the firm's equipment limit when that is lower than the limit above."""
    from sqlalchemy.orm import object_session
    return min(capitalisation_limit(engagement), firm_capital_limits(object_session(engagement))[1])
