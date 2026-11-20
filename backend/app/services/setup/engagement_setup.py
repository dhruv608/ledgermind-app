"""
Engagement Setup: the client context record, what the data suggests for it, the rules it
switches on (rules/engagement_rules.json, editable by the firm), the blocking gaps that keep the review from running,
and the warnings.

A setting counts as answered only when the accountant has saved it on the setup screen (confirmed_fields) or typed it
into the setup record. Values the app detected are shown as suggestions, never treated as answers.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, ClientProfile, MasterCOA, PayrollP32Record, TBRecord
from backend.app.services.ingestion.client_identity import company_key
from backend.app.services.tax.ct_computation import tax_parameters

RULES_FILE = Path(__file__).resolve().parents[2] / "rules" / "engagement_rules.json"
INDUSTRY_FILE = Path(__file__).resolve().parents[2] / "rules" / "industry_setup.json"
PARAMETERS_FILE = Path(__file__).resolve().parents[2] / "rules" / "parameters.json"

INDUSTRY_NAMES = {"CON": "Construction", "RES": "Restaurant", "MFG": "Manufacturing", "PRP": "Property",
                  "ECM": "E-commerce", "PRO": "Professional services", "SAAS": "IT / SaaS", "RTL": "Retail / Wholesale",
                  "REC": "Recruitment", "TRN": "Transport", "PRD": "Property trading / development",
                  "HBB": "Hair, beauty and barbers", "CNS": "Contractors and consultants", "HLT": "Healthcare and care",
                  "CHR": "Charities", "HLD": "Holding / investment company", "UNIV": "General"}
FRAMEWORK_NAMES = {"FRS105": "FRS 105", "FRS102_1A": "FRS 102 1A", "FULL_FRS102": "FRS 102 full", "IFRS": "IFRS"}
PERFORMANCE_PCT, TRIVIAL_PCT = 0.75, 0.05     # of overall materiality (both can be overwritten)


# ---------------------------------------------------------------------------------------------------------------
# Parameters (size limits and thresholds come from the firm's table, never typed into the screen)
# ---------------------------------------------------------------------------------------------------------------
def _money(text: str) -> float:
    m = re.match(r"£?\s*([\d.]+)\s*([mk]?)", text.strip(), re.I)
    if not m:
        return 0.0
    return float(m.group(1)) * {"m": 1_000_000, "k": 1_000, "": 1}[m.group(2).lower()]


# The limits before SI 2024/1303 (financial years beginning before 6 April 2025): the firm's FRS tab uses these
# for such years (e.g. a year from 1 April 2025)
NEW_LIMITS_FROM = date(2025, 4, 6)
LIMITS_BEFORE = [{"band": "Micro", "turnover": 632_000.0, "assets": 316_000.0, "employees": 10},
                 {"band": "Small", "turnover": 10_200_000.0, "assets": 5_100_000.0, "employees": 50},
                 {"band": "Medium", "turnover": 36_000_000.0, "assets": 18_000_000.0, "employees": 250}]


def size_limits(period_start: Optional[date] = None) -> List[Dict[str, Any]]:
    """[{band, turnover, assets, employees}] smallest first, from P-SIZE-MICRO / SMALL / MEDIUM (financial years
    beginning on or after 6 April 2025); the earlier limits for a year that began before."""
    if period_start is not None and period_start < NEW_LIMITS_FROM:
        return [dict(x) for x in LIMITS_BEFORE]
    params = {p["Param_ID"]: p for p in json.loads(PARAMETERS_FILE.read_text(encoding="utf-8"))}
    out = []
    for band, pid in (("Micro", "P-SIZE-MICRO"), ("Small", "P-SIZE-SMALL"), ("Medium", "P-SIZE-MEDIUM")):
        p = params.get(pid)
        if not p:
            continue
        turnover, assets = (_money(x) for x in str(p["Value"]).split("/")[:2])
        emp = re.search(r"≤\s*(\d+)\s*employees", p.get("Description", ""))
        out.append({"band": band, "turnover": turnover, "assets": assets, "employees": int(emp.group(1)) if emp else None})
    return out


def size_band(turnover: Optional[float], assets: Optional[float], employees: Optional[float],
              period_start: Optional[date] = None) -> Optional[str]:
    """A company is in a band when it meets at least two of the three limits (one-year indication only)."""
    known = [v is not None for v in (turnover, assets, employees)]
    if sum(known) < 2:
        return None
    for lim in size_limits(period_start):
        met = sum([turnover is not None and turnover <= lim["turnover"], assets is not None and assets <= lim["assets"],
                   employees is not None and lim["employees"] is not None and employees <= lim["employees"]])
        if met >= 2:
            return lim["band"]
    return "Large"


# ---------------------------------------------------------------------------------------------------------------
# Figures from the client's own data (for suggestions and the size test)
# ---------------------------------------------------------------------------------------------------------------
def data_figures(eng: ClientEngagement, db: Session) -> Dict[str, Any]:
    chart = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars()}
    tb = db.execute(select(TBRecord).where(TBRecord.engagement_id == eng.id)).scalars().all()
    turnover = -sum(float(t.net_amount or 0) for t in tb if t.std_code in chart and chart[t.std_code].category == "Sales")
    # Balance sheet total = gross assets: debit balances on asset codes (below 5000 in the firm chart)
    assets = sum(float(t.net_amount or 0) for t in tb
                 if t.std_code in chart and chart[t.std_code].financial_class == "Balance Sheet"
                 and t.std_code < 5000 and float(t.net_amount or 0) > 0)
    pay = db.execute(select(PayrollP32Record).where(PayrollP32Record.engagement_id == eng.id)).scalars().all()
    per_month: Dict[str, set] = {}
    for p in pay:
        per_month.setdefault(p.tax_month_label or "", set()).add((p.employee_name or "").lower())
    employees = round(sum(len(v) for v in per_month.values()) / len(per_month), 1) if per_month else None
    earlier = [e for e in db.execute(select(ClientEngagement).where(
                   ClientEngagement.id != eng.id, ClientEngagement.owner_user_id == eng.owner_user_id)).scalars()
               if company_key(e.client_name) == company_key(eng.client_name) and e.period_end_date < eng.period_end_date]
    from backend.app.services.cis.codes import cis_sides
    sales = {k for k, c in chart.items() if c.category == "Sales"}
    from backend.app.services.tax.ct_computation import RENTAL_INCOME_CODES
    rent = -sum(float(t.net_amount or 0) for t in tb if t.std_code in RENTAL_INCOME_CODES)
    return {"turnover": round(turnover, 2), "assets": round(assets, 2), "employees": employees, "rent": round(rent, 2),
            "earlier_year": max((e.period_end_date for e in earlier), default=None),
            "cis": cis_sides(tb, sales).as_dict()}


def _start_date(period: Dict[str, Any]) -> Optional[date]:
    try:
        return date.fromisoformat(str(period.get("start"))[:10])
    except (TypeError, ValueError):
        return None


def period_of(eng: ClientEngagement) -> Dict[str, str]:
    end = eng.period_end_date
    if eng.prior_period_end_date:
        start = eng.prior_period_end_date + timedelta(days=1)
    else:
        start = (end.replace(year=end.year - 1) if not (end.month == 2 and end.day == 29) else date(end.year - 1, 2, 28)) \
                + timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat()}


# ---------------------------------------------------------------------------------------------------------------
# The client context record and the suggestions
# ---------------------------------------------------------------------------------------------------------------
def build_record(eng: ClientEngagement, profile: ClientProfile, db: Session) -> Dict[str, Any]:
    confirmed = set(json.loads(profile.confirmed_fields or "[]"))
    setup = json.loads(profile.setup or "{}") if getattr(profile, "setup", None) else {}
    register = json.loads(profile.companies_house or "{}") if getattr(profile, "companies_house", None) else {}
    tax_inputs = json.loads(profile.tax_inputs or "{}")
    answered = lambda f, v: v if f in confirmed else None     # an answer only once the accountant saved it
    s = lambda part, k, default=None: (setup.get(part) or {}).get(k, default)

    figures = data_figures(eng, db)
    period = s("client", "period") or period_of(eng)
    turnover = s("client", "turnover", figures["turnover"])
    assets = s("client", "balance_sheet_total", figures["assets"])
    employees = s("client", "employees", figures["employees"])

    # The Directors box is the master list of names; each name's details (shares %, loan account, on payroll) are
    # kept by name in setup.people.director_details, and Companies House adds appointed / resigned / roles
    by_name = {p["name"].lower(): p for p in register.get("people", [])}
    details = s("people", "director_details", {}) or {}
    directors = [{"name": n, "appointed": (by_name.get(n.lower()) or {}).get("from"),
                  "resigned": (by_name.get(n.lower()) or {}).get("to"),
                  "roles": (by_name.get(n.lower()) or {}).get("roles", []),
                  "shares": (details.get(n) or {}).get("shares"), "dla": (details.get(n) or {}).get("dla"),
                  "on_payroll": (details.get(n) or {}).get("on_payroll")}
                 for n in json.loads(profile.directors or "[]")]
    overall = s("materiality", "overall") or (float(profile.materiality_threshold or 0) if "materiality_threshold" in confirmed else None)

    from backend.app.services.review.setup_checks import firm_depreciation_settings
    firm = firm_depreciation_settings(db)
    return {
        "client": {
            "name": eng.client_name, "company_number": s("client", "company_number") or register.get("company_number"),
            "period": period, "period_start": period.get("start"),
            "framework": answered("accounting_framework", profile.accounting_framework),
            "size": size_band(turnover, assets, employees, _start_date(period)), "turnover": turnover,
            "balance_sheet_total": assets,
            "employees": employees, "accounts_type": s("client", "accounts_type"),
            "prior_year_accounts": s("client", "prior_year_accounts"), "prior_year_tb_gl": s("client", "prior_year_tb_gl"),
        },
        "industry": {"code": answered("industry_code", profile.industry_code),
                     "name": INDUSTRY_NAMES.get(profile.industry_code or "", profile.industry_code) if "industry_code" in confirmed else None,
                     "models": s("industry", "models", []), "answers": s("industry", "answers", {})},
        "vat": {"registered": answered("is_vat_registered", bool(profile.is_vat_registered)),
                "scheme": (profile.vat_scheme if profile.is_vat_registered else None) if "is_vat_registered" in confirmed else None,
                "number": s("vat", "number"), "registration_date": s("vat", "registration_date"),
                "frequency": s("vat", "frequency"), "quarter_pattern": s("vat", "quarter_pattern"),
                "features": s("vat", "features", [])},
        "payroll": {"registered": answered("has_payroll", bool(profile.has_payroll)), "reference": s("payroll", "reference"),
                    "frequency": s("payroll", "frequency"), "features": s("payroll", "features", []),
                    "allowance_claimed": s("payroll", "allowance_claimed")},
        # CIS: the module is on when an account is mapped to 4421 / 5321; then these answers are required
        "cis": {"status": answered("cis_status", profile.cis_status or "NONE"), "subcontractors": s("cis", "subcontractors"),
                "gross_payment_status": s("cis", "gross_payment_status"), "gross_payment_from": s("cis", "gross_payment_from"),
                "registered": s("cis", "registered"), "utr": s("cis", "utr"), "scheme_reference": s("cis", "scheme_reference"),
                # CIS on invoices unpaid at the year start, from last year's CIS working (the cash basis starts from them)
                "opening_unpaid_suffered": s("cis", "opening_unpaid_suffered"),
                "opening_unpaid_deducted": s("cis", "opening_unpaid_deducted"),
                "module": figures["cis"]},
        "ct": {"associated_companies": tax_inputs.get("associated_companies"), "group_75": s("ct", "group_75"),
               "losses_bf": tax_inputs.get("losses_bf"), "rd_expected": s("ct", "rd_expected"),
               # Rent: a letting business (property income, its costs against it) or part of the trade
               "rent": figures["rent"], "rent_basis": s("ct", "rent_basis"), "property_costs": s("ct", "property_costs")},
        "policies": {"capitalisation": float(profile.capitalisation_threshold or 0) if "capitalisation_threshold" in confirmed else None,
                     "prepayment_threshold": s("policies", "prepayment_threshold"),
                     "accrual_threshold": s("policies", "accrual_threshold"),
                     "stock_method": s("policies", "stock_method"), "revenue_policy": s("policies", "revenue_policy"),
                     "closing_stock": s("policies", "closing_stock"),
                     "additions_from": s("policies", "additions_from"),
                     "depreciation": s("policies", "depreciation", {}),
                     "depreciation_default": firm["classes"],
                     "additions_from_default": firm["additions_from"],
                     "thresholds_entered": any(x is not None for x in (
                         s("policies", "prepayment_threshold"), s("policies", "accrual_threshold"),
                         float(profile.capitalisation_threshold or 0) if "capitalisation_threshold" in confirmed else None)),
                     "depreciation_entered": bool(s("policies", "depreciation"))},
        "people": {"directors": directors, "shareholders": s("people", "shareholders", []),
                   "related_companies": s("people", "related_companies", []),
                   "names": [d["name"] for d in directors] + [x.get("name") for x in s("people", "shareholders", []) if x.get("name")],
                   "any_dla": (any(d.get("dla") for d in directors) if any(d.get("dla") is not None for d in directors) else None)},
        "materiality": {"benchmark": s("materiality", "benchmark"), "pct": s("materiality", "pct"), "overall": overall,
                        "performance": s("materiality", "performance") or (round(overall * PERFORMANCE_PCT, 2) if overall else None),
                        "trivial": s("materiality", "trivial") or (round(overall * TRIVIAL_PCT, 2) if overall else None)},
        "prior_year": {"issues": s("prior_year", "issues", []), "notes": s("prior_year", "notes", "")},
    }


def _confirm_company(signals: Dict[str, Any]) -> str:
    """What to do for the SIC code: confirm the closest Companies House match, or look the company up."""
    choices = signals.get("ch_choices") or []
    if choices:
        return (f"Its SIC code decides once the company is confirmed under People: is it "
                f"{choices[0].get('company_name')} ({choices[0].get('company_number')})?")
    return "Look the company up under People for its SIC code, or pick the industry yourself."


def suggestions(eng: ClientEngagement, profile: ClientProfile, record: Dict[str, Any], db: Session) -> Dict[str, Dict[str, Any]]:
    """What the data, Companies House and last year suggest for answers still open: {field: {value, reason}}."""
    out: Dict[str, Dict[str, Any]] = {}
    figures = data_figures(eng, db)
    signals = json.loads(profile.detection_signals or "{}") if profile.detection_signals else {}
    register = json.loads(profile.companies_house or "{}") if getattr(profile, "companies_house", None) else {}
    from backend.app.services.setup.companies_house import sic_industry
    by_sic = sic_industry(register)
    sic = ", ".join(register.get("sic_codes", []))
    if record["industry"]["code"] is None and by_sic:
        out["industry_code"] = {"value": by_sic, "reason": (
            f"Companies House SIC code {sic}: {INDUSTRY_NAMES.get(by_sic, by_sic)}" if by_sic != "UNIV" else
            f"Companies House SIC code {sic} has no industry pack: general checks only")}
    elif record["industry"]["code"] is None and signals.get("industry_unsure"):
        leans = ", ".join(INDUSTRY_NAMES.get(i, i) for i in signals["industry_unsure"])
        out["industry_code"] = {"value": "UNIV", "reason": (
            f"Not clear from the books (they lean to {leans}): general checks until you choose the industry. "
            f"{_confirm_company(signals)}")}
    elif record["industry"]["code"] is None and profile.industry_code:
        out["industry_code"] = {"value": profile.industry_code, "reason": (
            f"Guessed from the ledger words: {INDUSTRY_NAMES.get(profile.industry_code, profile.industry_code)}. "
            f"{_confirm_company(signals)}")}
    if record["vat"]["registered"] is None:
        out["is_vat_registered"] = {"value": bool(profile.is_vat_registered),
                                    "reason": "VAT account / VAT on ledger lines found" if profile.is_vat_registered else "No VAT in the books"}
    if record["payroll"]["registered"] is None:
        out["has_payroll"] = {"value": bool(profile.has_payroll),
                              "reason": "Wages / PAYE accounts in the books" if profile.has_payroll else "No wages or PAYE accounts"}
    if record["cis"]["status"] is None:
        module = record["cis"]["module"]
        found = module["suffered"] + module["deducted"]
        out["cis_status"] = {"value": module["role"],
                             "reason": f"CIS accounts in the books: {', '.join(found[:3])}" if found else "No CIS tax accounts (4421 / 5321)"}
    band = record["client"]["size"]
    if record["client"]["framework"] is None:
        out["accounting_framework"] = {"value": "FRS102_1A", "reason": (f"Size indication: {band}. FRS 102 1A suits small companies"
                                                                        + ("; FRS 105 is also allowed for a micro-entity" if band == "Micro" else "")) if band else "Size not known yet"}
    if record["client"]["prior_year_tb_gl"] is None:
        earlier = figures["earlier_year"]
        out["prior_year_tb_gl"] = {"value": bool(earlier), "reason": f"Last year ({earlier:%d/%m/%Y}) is in the app" if earlier else "No earlier year in the app"}
    if record["materiality"]["overall"] is None and figures["turnover"] > 0:
        pct = float(tax_parameters().get("P-MAT", 0.01))
        overall = round(max(figures["turnover"] * pct, 1000.0), 2)
        out["materiality"] = {"value": {"benchmark": "Turnover", "pct": pct, "overall": overall,
                                        "performance": round(overall * PERFORMANCE_PCT, 2), "trivial": round(overall * TRIVIAL_PCT, 2)},
                              "reason": f"{pct:.0%} of turnover £{figures['turnover']:,.0f} (firm parameter P-MAT); performance 75%, trivial 5%"}
    if not record["people"]["directors"]:
        out["directors"] = {"value": None, "reason": "Use 'Get from Companies House' to fill the directors"}
    # What the books say about the industry questions still open (suggestions beside each question)
    from backend.app.services.setup.industry_evidence import industry_evidence
    evidence = industry_evidence(eng, profile, record, db)
    if evidence:
        out["industry_answers"] = {"value": evidence, "reason": "From the books"}
    if signals:
        out["_signals"] = {"value": signals, "reason": "What the detection found in the books"}
    return out


# ---------------------------------------------------------------------------------------------------------------
# Rules switched on, blocking gaps, warnings
# ---------------------------------------------------------------------------------------------------------------
def _value(record: Dict[str, Any], path: str):
    cur: Any = record
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _test(record: Dict[str, Any], cond) -> Optional[bool]:
    """True / False, or None when a field it needs has not been answered."""
    if cond == "always":
        return True
    if "all" in cond or "any" in cond:
        results = [_test(record, c) for c in cond.get("all") or cond.get("any")]
        if "all" in cond:
            return False if False in results else (None if None in results else True)
        return True if True in results else (None if None in results else False)
    v = _value(record, cond["field"])
    if v is None or v == "":
        return None
    if "eq" in cond:
        return v == cond["eq"]
    if "in" in cond:
        return v in cond["in"]
    if "gt" in cond:
        return float(v or 0) > cond["gt"]
    if "gte" in cond:
        return str(v) >= str(cond["gte"])
    if "set" in cond:
        return bool(v) == cond["set"]
    if "nonempty" in cond:
        return bool(v) == cond["nonempty"]
    return None


def _fill(text: str, record: Dict[str, Any]) -> str:
    def sub(m):
        v = _value(record, m.group(1))
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return f"{v:,.0f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
    return re.sub(r"\{([a-z_.]+)\}", sub, text)


def catalogue() -> Dict[str, Any]:
    """Industries (business models, questions with the query each switches on) and last year's issues: data, not code."""
    from backend.app.services.shared import rules_store
    return rules_store.load("industry_setup")


def _answered_yes(answer) -> Optional[bool]:
    if answer in (None, "", [], {}):
        return None                      # not answered: the query stays on
    if answer in ("N", False, 0, "0"):
        return False
    return True


def industry_checks(record: Dict[str, Any], data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each industry question answered yes switches on the query named beside it; unanswered ones stay on."""
    ind = data["industries"].get(record["industry"]["code"] or "")
    if not ind:
        return []
    answers = record["industry"].get("answers") or {}
    out = []
    for q in ind["questions"]:
        yes = _answered_yes(answers.get(q["id"]))
        if yes is False:
            continue
        shown = answers.get(q["id"])
        out.append({"id": f"IQ-{q['id']}", "engine": f"{ind['name']}: {q['label']}", "rules": q["rules"],
                    "reason": ("Answered: " + (", ".join(shown) if isinstance(shown, list) else ("yes" if shown == "Y" else str(shown))))
                    if yes else "Not answered yet: kept on until it is",
                    "state": "on" if yes else "unknown"})
    return out


def activated(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    from backend.app.services.shared import rules_store
    rules = rules_store.load("engagement_rules")["rules"]
    data = catalogue()
    py_rules = {p["label"]: p["rules"] for p in data["prior_year_issues"]}
    record = {**record, "industry": {**record["industry"], "models_text": ", ".join(record["industry"].get("models") or []) or "not chosen yet"},
              "prior_year": {**record["prior_year"],
                             "rules_text": " · ".join(py_rules.get(i, i) for i in record["prior_year"].get("issues") or [])}}
    out = []
    for r in rules:
        result = _test(record, r["when"])
        if result is None and r.get("blank_off"):
            result = False                       # optional entry left blank: the firm default applies
        if result is False:
            continue
        out.append({"id": r["id"], "engine": r["engine"], "rules": _fill(r["rules"], record),
                    "reason": _fill(r["reason"], record) if result else "Not answered yet: kept on until it is",
                    "state": "on" if result else "unknown"})
        if r["id"] == "R07":
            out.extend(industry_checks(record, data))
    return out


def gaps_and_warnings(record: Dict[str, Any]) -> Dict[str, List[str]]:
    c, gaps, warnings = record["client"], [], []
    if not c["name"] or not (c["period"] or {}).get("end"):
        gaps.append("Client name or period end missing")
    if not c["framework"]:
        gaps.append("Framework not chosen")
    if not record["industry"]["code"]:
        gaps.append("Industry not chosen")
    if record["vat"]["registered"] is None or record["payroll"]["registered"] is None:
        gaps.append("VAT status or PAYE status not answered")
    if not record["people"]["directors"]:
        gaps.append("No director entered")
    if not record["materiality"]["overall"]:
        gaps.append("Overall materiality not set")
    cis = record["cis"]
    if cis["module"]["on"] and cis["status"] is None:
        gaps.append("CIS accounts in the books: CIS role not answered")
    if cis["status"] in ("CONTRACTOR", "SUBCONTRACTOR", "BOTH"):
        missing = [label for key, label in (("utr", "UTR"), ("registered", "CIS registration"),
                                            ("gross_payment_status", "gross payment status"),
                                            ("scheme_reference", "PAYE / CIS scheme reference")) if cis.get(key) in (None, "")]
        if missing:
            gaps.append(f"CIS: {', '.join(missing)} not answered")

    params = tax_parameters()
    band, fw, turnover = c["size"], c["framework"], c["turnover"] or 0
    if band and fw:
        if fw == "FRS105" and band != "Micro":
            warnings.append(f"FRS 105 chosen, but the size indication is {band}, not micro")
        if fw == "FRS102_1A" and band in ("Medium", "Large"):
            warnings.append(f"FRS 102 1A chosen, but the size indication is {band}")
        if fw == "FULL_FRS102" and band == "Micro":
            warnings.append("Full FRS 102 chosen for a micro-entity (allowed)")
    construction = record["industry"]["code"] == "CON"
    if construction and record["vat"]["registered"] and "construction reverse charge" not in [f.lower() for f in record["vat"]["features"]]:
        warnings.append("Construction and VAT registered, but construction reverse charge is not ticked")
    if construction and record["cis"]["status"] == "NONE":
        warnings.append("Construction but not in CIS")
    if record["vat"]["registered"] is False and turnover > float(params.get("P-VAT-REG", 90000)):
        warnings.append(f"Not VAT registered and turnover £{turnover:,.0f} is above £{float(params.get('P-VAT-REG', 90000)):,.0f}")
    if record["vat"]["scheme"] in ("FLAT_RATE", "FLAT_RATE_CASH") and turnover > float(params.get("P-VAT-FRS-LEAVE", 230000)):
        warnings.append(f"Flat rate scheme and turnover £{turnover:,.0f} is above £{float(params.get('P-VAT-FRS-LEAVE', 230000)):,.0f}")
    p = c["period"] or {}
    if p.get("start") and p.get("end") and (date.fromisoformat(p["end"]) - date.fromisoformat(p["start"])).days > 366:
        warnings.append("Period longer than 12 months: two CT returns will be needed")
    shares = [float(d.get("shares") or 0) for d in record["people"]["directors"]] + \
             [float(x.get("shares") or 0) for x in record["people"]["shareholders"]]
    if any(shares) and abs(sum(shares) - 100) > 0.5:
        warnings.append(f"Directors' and shareholders' shares add to {sum(shares):g}%, not 100%")
    if band:
        warnings.append(f"Size indication {band}: one year only, the legal test needs two consecutive years")
    return {"gaps": gaps, "warnings": warnings}


def setup_status(eng: ClientEngagement, profile: ClientProfile, db: Session) -> Dict[str, Any]:
    record = build_record(eng, profile, db)
    record["activated"] = activated(record)
    gw = gaps_and_warnings(record)
    return {"record": record, "activated": record["activated"], "gaps": gw["gaps"], "warnings": gw["warnings"],
            "suggestions": suggestions(eng, profile, record, db), "catalogue": catalogue()}


def preview_profile(saved: ClientProfile, changes: Dict[str, Any]) -> ClientProfile:
    """The saved profile with unsaved edits applied, as if saved (for the live panel). Never added to the session."""
    from backend.app.services.setup.profile_service import SETUP_FIELDS
    p = ClientProfile()
    for col in ClientProfile.__table__.columns.keys():
        setattr(p, col, getattr(saved, col))
    confirmed = set(json.loads(saved.confirmed_fields or "[]"))
    for key, value in changes.items():
        if not hasattr(p, key) or key in ("id", "engagement_id", "confirmed_fields") or value is None:
            continue
        setattr(p, key, json.dumps(value) if isinstance(value, (list, dict)) else value)
        if key in SETUP_FIELDS:
            confirmed.add(key)
    p.confirmed_fields = json.dumps(sorted(confirmed))
    return p
