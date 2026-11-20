"""The corporation tax computation's codes, word rules and rates (law figures from rules/parameters.json), and the
firm's settings it reads."""

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict

from sqlalchemy.orm import Session


PARAMETERS_FILE = Path(__file__).resolve().parents[2] / "rules" / "parameters.json"
TAX_SECTIONS = {"Current tax", "Deferred tax"}
INTEREST_SECTION = "Interest receivable and similar income"
DIVIDEND_SECTIONS = {"Income from shares in group undertakings", "Income from participating interests",
                     "Income from other fixed asset investments", "Income from other current asset investments"}
RENTAL_INCOME_CODES = {400, 500}
ENTERTAINING = 3385
CHARITABLE_DONATIONS, POLITICAL_DONATIONS = 3360, 3361
CT_CHARGE = 3800
PRIOR_YEAR_TAX = 3810
FOREIGN_TAX_CODES = {3820, 3821}     # double taxation, foreign tax
DLA_CODES = (5400, 5401, 5402, 5800)
# Amortisation and impairment of intangibles (the P&L side) and the asset accounts that say which intangible it is:
# goodwill's charge in the year (4005) against the other intangibles' (other, development, intellectual property)
INTANGIBLE_DEBIT = re.compile(r"amortisation|impairment loss - intangible|reversal of impairment loss - intangible", re.I)
GOODWILL_CHARGE, GOODWILL_COST = 4005, (4000, 4001)
OTHER_INTANGIBLE_CHARGE, OTHER_INTANGIBLE_COST = (4014, 4026, 4037), (4010, 4011, 4020, 4021, 4030, 4031)
# Firm settings 'intangibles': software, patents, trade marks and other non-goodwill intangibles. ADD_BACK: added back
# until the reviewer confirms the asset qualifies (the default); ALLOW: relieved with the accounts
INTANGIBLES_POLICIES = ("ADD_BACK", "ALLOW")
# Fixed asset additions / disposals by class: which capital allowance each class gets
AIA_ADDITIONS = {4121: "Plant and equipment", 4141: "Fixtures and fittings", 4151: "Computer equipment"}
VEHICLE_ADDITIONS = 4131
# The cost account of each additions account: a TB of the year's movements often posts purchases straight to cost
COST_OF_ADDITIONS = {4121: 4120, 4141: 4140, 4151: 4150, 4131: 4130}
NO_ALLOWANCE_ADDITIONS = {4101: "Freehold land and property", 4111: "Leasehold land and property",
                          4161: "Investment property"}
# class: (cost disposed, depreciation on disposals)
DISPOSALS = {"Plant and equipment": (4122, 4125), "Motor vehicles": (4132, 4135),
             "Fixtures and fittings": (4142, 4145), "Computer equipment": (4152, 4155)}
# A fine or penalty as a bank or ledger line writes it (not 'Fine Foods': the word alone is not enough)
FINE_LINE = re.compile(r"\b(pcn|penalty charge|parking fine|fixed penalty|penalt(y|ies)|late filing|"
                       r"speeding fine|congestion charge penalty)\b", re.I)
# A 'penalty' that is not a fine: an early repayment / redemption charge on a loan is a loan relationship debit, a
# contract penalty or damages a business cost (BIM42515; only fines and tax penalties are barred, CTA 2009 s1303)
NOT_A_FINE = re.compile(r"\b(early (re)?payment|redemption|settlement figure|break (cost|fee)|exit fee|erc|"
                        r"prepayment (charge|fee)|loan|mortgage|finance agreement|hire purchase|contract|"
                        r"liquidated damages|cancellation)\b", re.I)
# Legal costs of a capital nature (CTA 2009 s53, CTM17600): buying property or a business, issuing shares
CAPITAL_LEGAL = re.compile(r"\b(conveyancing|completion statement|stamp duty|sdlt|land registry|purchase of (the )?"
                           r"(property|premises|building|land|business|shares)|acquisition of|share (issue|allotment)|"
                           r"issue of shares)\b", re.I)
LEGAL_FEES = 3302
# Gifts to customers or others (CTA 2009 s1298, BIM45065), not to staff (allowed) or to charity (donations)
GIFT_LINE = re.compile(r"\b(gifts?|hampers?|gift (cards?|vouchers?))\b", re.I)
NOT_A_CLIENT_GIFT = re.compile(r"\b(staff|employees?|team|charit(y|able)|donations?|gift aid|gift shop|gift wrap)\b",
                               re.I)
# Interest and penalties on late tax in the interest accounts: on late VAT, PAYE / NIC and CIS they are not allowed
# (CTA 2009 s1303, BIM42520, BIM45740); interest on late corporation tax is (a loan relationship debit, CTM92190)
LATE_TAX_CHARGES = 3670                                    # firm chart: late payment tax charges
HMRC_TAX_TEXT = re.compile(r"\b(hmrc|h\.?m\.?r\.?c|vat|paye|nic|national insurance|cis)\b", re.I)
CT_TEXT = re.compile(r"\b(corporation tax|ct|ct600)\b", re.I)
DISPOSAL_PROFIT_CODES = {2870, 2871, 3560, 3561}           # profit / (loss) on disposal accounts
ZERO_EMISSION = re.compile(r"\b(electric|zero[- ]emission|ev|bev|tesla)\b", re.IGNORECASE)
# A hybrid is not zero-emission: only a 0 g/km car gets the 100% allowance (CAA 2001 s45D, CA23153)
HYBRID = re.compile(r"\b(hybrid|phev|plug-?in|hev|mhev)\b", re.IGNORECASE)
# The 100% allowance covers cars bought up to 31 March 2027 for corporation tax (CA23153); a 0 g/km car bought later
# goes to the main pool (50 g/km or less, BIM47730)
ZERO_EMISSION_FYA_UNTIL = date(2027, 3, 31)
# 40% first-year allowance for new main-rate plant from this date (CAA 2001 s45U, CA23195A)
FYA_40_FROM = date(2026, 1, 1)
VAN = re.compile(r"\b(van|vans|truck|lorry|minibus|tractor|forklift|motorcycle|motorbike|commercials?|"
                 r"sprinter|transit|relay|vivaro|trafic|transporter|crafter|ducato|movano|berlingo|kangoo|proace|"
                 r"tipper|luton)\b", re.IGNORECASE)
# Pick-ups: a double cab bought from 1 April 2025 is a car for capital allowances whatever its payload (CA23511); a
# single cab stays a van
PICK_UP = re.compile(r"\b(pick-?up|hilux|ranger|navara|l200|amarok|d-?max|warrior)\b", re.IGNORECASE)
SINGLE_CAB = re.compile(r"\b(single[- ]cab|regular cab|chassis cab)\b", re.IGNORECASE)
DOUBLE_CAB_AS_CAR_FROM = date(2025, 4, 1)
# Vehicle tax booked with a vehicle: a running cost, not capital (no allowance; it belongs in motor expenses)
ROAD_TAX = re.compile(r"\b(road fund|road tax|vehicle tax|vehicle excise|ved)\b", re.IGNORECASE)
# Costs bought with a van that are part of its cost (not road fund licence: vehicle tax is a running cost)
VEHICLE_EXTRAS = re.compile(r"\b(fees?|agreement|option|delivery|registration|number plates?|plates)\b", re.IGNORECASE)
MAIN_POOL_WDA_BEFORE_APRIL_2026 = 0.18   # 14% from 1 April 2026 (P-WDA-MAIN); periods straddling it get a mix
SPECIAL_POOL_WDA = 0.06
SMALL_POOL = 1000.0
# What the accountant can choose for each addition (the capital allowances list on the Review tab)
CA_TREATMENTS = {"AIA": "AIA", "FYA": "100% first-year allowance (new electric car)", "MAIN": "Main pool",
                 "SPECIAL": "Special rate pool (6%)", "NONE": "No allowance"}
MAIN_RATE_FROM = date(2023, 4, 1)        # small profits rate / marginal relief regime starts (FY2023)
OLD_FLAT_RATE = 0.19                     # FY2022 and earlier
CT_UNSETTLED_LIMIT = 1000.0     # suspense and one-sided transfers above this: the profit, and so the tax, is not final


def ct_hold_limit(db: Session) -> float:
    """The firm's limit on suspense before a bank job's tax is held back (Firm settings page), else £1,000."""
    from backend.app.models.firm_settings import FirmSetting
    row = db.get(FirmSetting, "ct_hold_limit")
    try:
        amount = json.loads(row.value).get("amount") if row is not None else None
    except ValueError:
        amount = None
    return float(amount) if amount is not None else CT_UNSETTLED_LIMIT


def firm_intangibles_policy(db: Session) -> str:
    """The firm's rule for non-goodwill intangibles' amortisation (Firm settings): ADD_BACK (the default) or ALLOW."""
    from backend.app.models.firm_settings import FirmSetting
    row = db.get(FirmSetting, "intangibles")
    try:
        policy = json.loads(row.value).get("policy") if row is not None else None
    except ValueError:
        policy = None
    return policy if policy in INTANGIBLES_POLICIES else "ADD_BACK"


@lru_cache(maxsize=1)
def tax_parameters() -> Dict[str, float]:
    with open(PARAMETERS_FILE, encoding="utf-8") as f:
        return {p["Param_ID"]: float(p["Value"]) for p in json.load(f) if isinstance(p.get("Value"), (int, float))}
