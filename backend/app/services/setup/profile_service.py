"""
The client profile: its facts, and what is detected from the uploaded TB and GL (industry, VAT registration, payroll,
CIS and materiality).
"""

import logging
import os
import json
import re
from datetime import timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.models.database import ClientEngagement, ClientProfile, TBRecord, GLTransaction
from backend.app.services.ingestion.client_identity import company_key
from backend.app.services.mapping.chart_lookup import ChartLookup, VAT_CONTROL, VAT_LONG_TERM, PAYE_NIC, NET_WAGES

logger = logging.getLogger(__name__)

# Settings on the setup screen. Once the accountant saves them they are his: auto-detect (run on every upload)
# leaves them alone, and next year's engagement for the same company starts with them.
# Carried into next year: facts about the company. Not carried: this year's figures and answers.
YEARLY_FIELDS = ("materiality_threshold",)
CARRIED_SETUP_PARTS = ("industry", "vat", "payroll", "cis", "ct", "people", "policies")
CARRIED_CLIENT_KEYS = ("company_number", "accounts_type")
SETUP_FIELDS = ("industry_code", "is_vat_registered", "vat_scheme", "has_payroll", "cis_status", "directors",
                "accounting_framework", "materiality_threshold", "capitalisation_threshold", "properties",
                "tax_inputs", "companies_house", "setup")


def confirmed_fields(profile: Optional[ClientProfile]) -> Set[str]:
    return set(json.loads(profile.confirmed_fields or "[]")) if profile is not None else set()


def confirmed_industry(profile: Optional[ClientProfile]) -> Optional[str]:
    """The client's industry once the accountant has confirmed it; the app's guess alone is not enough for
    industry-specific checks (one Deliveroo lunch does not make a restaurant)."""
    return profile.industry_code if "industry_code" in confirmed_fields(profile) else None


# Industry words most businesses' books hold whatever the trade (a gas bill, bank fees, postage, an Amazon order,
# a PayPal account, fuel, plant and machinery): not evidence of an industry
COMMON_WORDS = {"gas", "fees", "postage", "returns", "subscriptions", "deposit", "development", "fuel", "machinery",
                "stock", "carriage", "materials", "site", "skip", "paypal", "stripe", "amazon", "royal mail", "dpd",
                "xero", "square", "sumup", "dojo", "food", "drink", "production"}
# A counterparty described, not named ('letting agents', 'card acquirers'): not looked for in the ledger
DESCRIBED = re.compile(r"suppliers|agents|providers|acquirers|companies|lessors|boards|software|solicitors|"
                       r"wholesalers|forwarders|\(", re.I)
COUNTERPARTY_LINES = 3      # a counterparty on fewer sales lines is a one-off, not the trade
# The company's own name says the trade more surely than its ledger words ('Acme Catering', 'Acme Properties')
NAME_INDUSTRY = [
    (r"cater|kebab|diner|cafe|caf[eé]|fryer|fish ?(&|and) ?chips|pizza|restaurant|takeaway|bistro|grill|bakery|"
     r"burger|curry|tandoori|noodle|sushi", "RES"),
    (r"propert|estates?\b|lettings?\b|\brtm\b|right to manage|housing|homes?\b", "PRP"),
    (r"transport|logistics|haulage|couriers?\b|freight|removals", "TRN"),
    (r"solicitor|\blaw\b|legal|accountan|consult|advi[cs]|architect|surveyor", "PRO"),
    (r"software|digital|technolog|\btech\b|\bit (services|solutions)|systems\b|web|gaming|apps?\b", "SAAS"),
    (r"construct|builders?\b|building\b|installation|interiors|electrical|plumb|roofing|flooring|joinery|"
     r"scaffold|groundwork|carpent|decorat", "CON"),
    (r"recruit|staffing|locum|personnel|employment agency", "REC"),
    (r"wholesale|retail|store|stores\b|supermarket|convenience|off licen", "RTL"),
    (r"hair|salon|beauty|barber|pilates|fitness|\bgym\b|yoga|church|charity|\bcic\b|clinic|care\b", "UNIV"),
]
NAME_WEIGHT = 12            # above the threshold alone: the name decides unless the books clearly say otherwise
CLEAR_LEAD = 0.75           # the runner-up at or above this share of the best score: too close to call


def _known_company_number(profile: ClientProfile, eng: ClientEngagement) -> Optional[str]:
    """The client's company number when it is known: saved on the setup (or carried from last year), else written
    in the heading of one of the uploaded files ('Company number : 12345678')."""
    from backend.app.services.setup import companies_house as ch
    try:
        saved = (json.loads(profile.setup or "{}").get("client") or {}).get("company_number")
    except (TypeError, ValueError):
        saved = None
    if saved:
        return str(saved).strip().upper()
    try:
        import io
        import pandas as pd
        from backend.app.services.bank_only.books import client_files
        files, _ = client_files(str(eng.id))
        for name, data in files:
            if not name.lower().endswith((".xlsx", ".xls", ".xlsm", ".csv")):
                continue
            book = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, nrows=12) \
                if not name.lower().endswith(".csv") else {"": pd.read_csv(io.BytesIO(data), header=None, nrows=12)}
            for frame in book.values():
                text = " ".join(str(v) for v in frame.values.flatten() if pd.notna(v))
                number = ch.number_in_text(text)
                if number:
                    return number
    except Exception:
        logger.exception("Company number not looked for in the files")
    return None


RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "rules")


def load_industry_signals() -> List[Dict[str, Any]]:
    from backend.app.services.shared import rules_store
    try:
        return rules_store.load("industry_detect")
    except OSError:
        return []


class ProfileService:
    @staticmethod
    def get_or_create_profile(db: Session, engagement_id: str) -> ClientProfile:
        stmt = select(ClientProfile).where(ClientProfile.engagement_id == engagement_id)
        profile = db.execute(stmt).scalar_one_or_none()
        if not profile:
            profile = ClientProfile(
                engagement_id=engagement_id,
                industry_code="UNIV",
                is_vat_registered=False,
                vat_scheme="STANDARD",
                has_payroll=False,
                cis_status="NONE",
                directors="[]",
                accounting_framework="FRS102_1A",
                materiality_threshold=0.00,
                capitalisation_threshold=500.00,
                auto_detected=False
            )
            ProfileService._carry_over(db, engagement_id, profile)
            db.add(profile)
            db.commit()
            db.refresh(profile)
        return profile

    @staticmethod
    def _carry_over(db: Session, engagement_id: str, profile: ClientProfile) -> None:
        """A new year starts with what the accountant set up last year for the same company."""
        eng = db.get(ClientEngagement, engagement_id)
        if eng is None:
            return
        key = company_key(eng.client_name)
        earlier = db.execute(
            select(ClientProfile).join(ClientEngagement, ClientProfile.engagement_id == ClientEngagement.id)
            .where(ClientEngagement.id != engagement_id, ClientEngagement.owner_user_id == eng.owner_user_id)
            .order_by(ClientEngagement.period_end_date.desc())
        ).scalars().all()
        last = next((p for p in earlier if company_key(p.engagement.client_name) == key and confirmed_fields(p)), None)
        if last is None:
            return
        # Facts about the company carry over; this year's own figures (materiality, period, last year's issues) do not.
        # Everything carried is marked so the screen asks for a check before it counts as this year's answer.
        carried = [f for f in confirmed_fields(last) if f not in YEARLY_FIELDS]
        for field in carried:
            setattr(profile, field, getattr(last, field))
        parts: List[str] = []
        if "setup" in carried and last.setup:
            old = json.loads(last.setup or "{}")
            new = {k: v for k, v in old.items() if k in CARRIED_SETUP_PARTS}
            client = {k: v for k, v in (old.get("client") or {}).items() if k in CARRIED_CLIENT_KEYS}
            if client:
                new["client"] = client
            parts = sorted(k for k in new if not k.startswith("_"))
            new["_carried"] = {"from": last.engagement.period_end_date.isoformat(),
                               "fields": sorted(f for f in carried if f != "setup"), "parts": parts}
            profile.setup = json.dumps(new)
        profile.confirmed_fields = json.dumps(sorted(carried))
        if last.tax_inputs:
            profile.tax_inputs = json.dumps(ProfileService._next_year_tax_inputs(json.loads(last.tax_inputs)))

    @staticmethod
    def _next_year_tax_inputs(last: Dict[str, Any]) -> Dict[str, Any]:
        """Last year's corporation tax facts for a new year: what its computation carried forward (losses, capital
        allowance pools), the same associated companies; this-year-only items start empty."""
        carried = last.get("_carried_forward") or {}
        out = {k: v for k, v in last.items() if k in ("associated_companies",)}
        for key in ("losses_bf", "main_pool_bf", "special_pool_bf"):
            value = carried.get(key, last.get(key))
            if value:
                out[key] = value
        return out

    @staticmethod
    def auto_detect_profile(db: Session, engagement_id: str, keep_confirmed: bool = True) -> ClientProfile:
        """Detects the industry (signals in industry_detect.json), VAT status, payroll and CIS from the TB and GL,
        and works out materiality."""
        profile = ProfileService.get_or_create_profile(db, engagement_id)

        stmt_tb = select(TBRecord).where(TBRecord.engagement_id == engagement_id)
        tb_records = db.execute(stmt_tb).scalars().all()

        # The words: the industry keywords in the account names (the TB's and the ledger's), the counterparties in
        # the ledger descriptions
        gl_rows = db.execute(select(GLTransaction.raw_account_name, GLTransaction.description)
                             .where(GLTransaction.engagement_id == engagement_id).limit(20000)).all()
        account_names = {r.raw_account_name.lower() for r in tb_records if r.raw_account_name}
        account_names |= {(a or "").lower() for a, _ in gl_rows if a}
        # Counterparties only on the sales accounts' lines: Deliveroo paying the client is a restaurant, the
        # client buying at Screwfix or on eBay is any business
        from backend.app.services.mapping.chart_lookup import account_name_keys
        sales_chart = ChartLookup(db)
        gl_codes = ChartLookup.gl_account_codes(tb_records)
        def on_sales(account: str) -> bool:
            code = next((gl_codes[k] for k in account_name_keys(account or "") if k in gl_codes), None)
            return sales_chart.is_sales(code)
        sales_accounts = {a for a, _ in gl_rows if a and on_sales(a)}
        gl_descriptions = [d.lower() for a, d in gl_rows if d and a in sales_accounts]

        signals = [s for s in load_industry_signals() if s.get("Signal weight") is not None]
        threshold = next((int(s["SIC code range (indicative)"]) for s in load_industry_signals()
                          if str(s.get("Industry", "")).startswith("Confirmation threshold")), 6)

        # 1. Industry Scoring: whole words only ('gas' is not in 'Vegas'); a counterparty counts when it is on
        # several lines (one Deliveroo lunch does not make a restaurant)
        scores: Dict[str, int] = {s["Industry"]: 0 for s in signals}
        match_details: Dict[str, List[str]] = {s["Industry"]: [] for s in signals}

        def word(text: str) -> "re.Pattern":
            return re.compile(r"(?<![a-z0-9])" + re.escape(text) + r"(?![a-z0-9])")

        for s in signals:
            ind = s["Industry"]
            weight = int(s.get("Signal weight") or 2)
            keywords = [k.strip().lower() for k in (s.get("CoA / GL keywords") or "").split(",") if k.strip()]
            for kw in keywords:
                if kw in COMMON_WORDS:
                    continue
                pattern = word(kw)
                if any(pattern.search(name) for name in account_names):
                    scores[ind] += weight * 2
                    match_details[ind].append(f"Keyword: {kw}")
            counterparties = [c.strip().lower() for c in (s.get("Typical counterparties") or "").split(",") if c.strip()]
            for cp in counterparties:
                if cp in COMMON_WORDS or DESCRIBED.search(cp):
                    continue
                pattern = word(cp)
                lines = sum(1 for d in gl_descriptions if pattern.search(d))
                if lines >= COUNTERPARTY_LINES:
                    scores[ind] += weight * 3
                    match_details[ind].append(f"Counterparty: {cp} ({lines} lines)")

        eng_for_name = db.get(ClientEngagement, engagement_id)
        client_name = (eng_for_name.client_name or "").lower() if eng_for_name else ""
        for pattern, ind in NAME_INDUSTRY:
            if re.search(pattern, client_name):
                scores[ind] = scores.get(ind, 0) + NAME_WEIGHT
                match_details.setdefault(ind, []).append(f"Company name: {client_name}")
                break

        # Determine winner: only a clear lead counts; otherwise the general checks, and the accountant chooses
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        best_industry = "UNIV"
        highest_score = ranked[0][1] if ranked else 0
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        unsure = None
        # Above the threshold: one keyword alone (exactly the threshold) is not enough to name the trade
        if highest_score > threshold and runner_up < highest_score * CLEAR_LEAD:
            best_industry = ranked[0][0]
        elif highest_score > 0:
            unsure = [ind for ind, score in ranked[:3] if score > 0]

        # The company's SIC codes on the public register decide; the ledger words only suggest. The register is
        # looked up once: by the company number when it is known (saved on the setup, carried from last year, or
        # written in a file heading), else by the client's exact name; with no exact match the closest companies
        # are kept for the accountant to confirm on the People step ('Is this your company?')
        from backend.app.services.setup import companies_house as ch
        register = json.loads(profile.companies_house) if profile.companies_house else {}
        ch_choices: List[Dict[str, Any]] = []
        if not register.get("company_number"):
            eng = db.get(ClientEngagement, engagement_id)
            if eng is not None and eng.client_name and eng.period_end_date:
                year_start = eng.prior_period_end_date + timedelta(days=1) if eng.prior_period_end_date else None
                number = _known_company_number(profile, eng)
                found, ch_choices = ch.find_client(eng.client_name, eng.period_end_date, year_start, number)
                if found:
                    register = found
                    profile.companies_house = json.dumps(found)
        ledger_industry = best_industry
        if ch.sic_industry(register):
            best_industry = ch.sic_industry(register)

        chart = ChartLookup(db)

        # 2. VAT Registration Auto-Detection
        # Firm VAT creditor accounts (5300 / 5700) or "vat control" / "vat liability" named accounts
        has_vat = False
        vat_scheme = "STANDARD"
        for r in tb_records:
            name = r.raw_account_name.lower()
            if r.std_code in (VAT_CONTROL, VAT_LONG_TERM) or "vat control" in name or "vat liability" in name:
                has_vat = True
                break
            if "vat" in name and (r.debit_amount > 0 or r.credit_amount > 0):
                has_vat = True
                break

        # 3. Payroll Auto-Detection
        has_payroll = False
        for r in tb_records:
            name = r.raw_account_name.lower()
            if chart.is_gross_wages(r.std_code) or r.std_code in (PAYE_NIC, NET_WAGES) or any(k in name for k in ["wages", "salaries", "paye", "nic", "pension"]):
                if (r.debit_amount or 0) > 0 or (r.credit_amount or 0) > 0:
                    has_payroll = True
                    break

        # 4. CIS Auto-Detection
        # From the CIS tax accounts: 4421 CIS suffered = subcontractor, 5321 CIS deducted = contractor
        from backend.app.services.cis.codes import cis_sides
        cis_status = cis_sides(tb_records, {r.std_code for r in tb_records if chart.is_sales(r.std_code)}).role

        # 5. Turnover & Materiality calculation (turnover = accounts mapped to the firm chart's Sales section)
        total_turnover = Decimal(str(chart.turnover(tb_records)))

        # Audit materiality: 1% of turnover or £1,000 minimum
        turnover_float = float(total_turnover)
        materiality = max(round(turnover_float * 0.01, 2), 1000.00)

        # Update profile: the accountant's saved settings stay, unless he asked to re-scan
        if not keep_confirmed:
            profile.confirmed_fields = "[]"
        keep = confirmed_fields(profile)
        detected = {"industry_code": best_industry, "is_vat_registered": has_vat, "vat_scheme": vat_scheme,
                    "has_payroll": has_payroll, "cis_status": cis_status,
                    "materiality_threshold": Decimal(str(materiality)), "capitalisation_threshold": Decimal("500.00")}
        for field, value in detected.items():
            if field not in keep:
                setattr(profile, field, value)
        profile.auto_detected = True
        profile.detection_signals = json.dumps({
            "detected_industry": best_industry,
            "industry_from": "SIC" if ch.sic_industry(register) else "ledger",
            "sic_codes": register.get("sic_codes", []),
            "ledger_industry": ledger_industry,
            "industry_score": highest_score,
            "signals": match_details.get(ledger_industry, []),
            "turnover_detected": turnover_float,
            "all_scores": {k: v for k, v in scores.items() if v > 0},
            # The ledger could not tell (weak or close scores): the industries it leans to, for the accountant
            "industry_unsure": unsure,
            # No exact Companies House match: the closest companies, to confirm on the People step
            "ch_choices": ch_choices,
        })

        db.commit()
        db.refresh(profile)
        return profile

    @staticmethod
    def update_profile(db: Session, engagement_id: str, updates: Dict[str, Any]) -> ClientProfile:
        profile = ProfileService.get_or_create_profile(db, engagement_id)

        saved = confirmed_fields(profile)
        for key, value in updates.items():
            if key in SETUP_FIELDS and value is not None:
                saved.add(key)
            if hasattr(profile, key) and value is not None:
                if key == "setup" and isinstance(value, dict) and profile.setup:
                    # The Data check tab's own part ('first year of trading') and the job details (pack dates, who
                    # works on it: job_details.py) are kept when the setup screen saves
                    old = json.loads(profile.setup) or {}
                    value = {**{k: old[k] for k in ("data", "job") if k in old and k not in value}, **value}
                if key in ("directors", "properties", "tax_inputs", "companies_house", "setup") and isinstance(value, (list, dict)):
                    setattr(profile, key, json.dumps(value))
                elif key in ("materiality_threshold", "capitalisation_threshold"):
                    setattr(profile, key, Decimal(str(value)))
                else:
                    setattr(profile, key, value)
        profile.confirmed_fields = json.dumps(sorted(saved))

        db.commit()
        db.refresh(profile)
        return profile
