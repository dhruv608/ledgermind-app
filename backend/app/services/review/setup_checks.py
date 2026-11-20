"""
The review reads the Engagement Setup: what the accountant answered on the setup screen
changes what the review raises.

  - Materiality: points under 'clearly trivial' are logged (cleared with a note), not sent to the client; points at or
    above performance / overall materiality are raised in severity.
  - Policies: the client's prepayment and accrual thresholds replace the firm's (capitalisation already did).
  - Industry: each industry question answered Yes raises the query named beside it, No leaves it out, unanswered keeps
    it on; the industry's reference column follows the framework (FRS 105 or FRS 102).
  - Depreciation: rates entered per asset class are recalculated against the charge in the books.
  - Last year: each issue ticked is raised again to be retested this year.
"""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ClientProfile, ProposedJournal, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM
from backend.app.services.ingestion.client_identity import company_key

TRIVIAL_NOTE = "Below clearly trivial"      # start of the note on points the review logged rather than raised
SUSPENSE_CODE = 9999


def setup_of(profile: Optional[ClientProfile]) -> Dict[str, Any]:
    try:
        return json.loads(profile.setup or "{}") if profile is not None and getattr(profile, "setup", None) else {}
    except (TypeError, ValueError):
        return {}


def policy_threshold(profile: Optional[ClientProfile], key: str) -> Optional[float]:
    """The client's prepayment_threshold / accrual_threshold from the setup, or None for the firm default."""
    value = (setup_of(profile).get("policies") or {}).get(key)
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------------------------
# Industry queries, narrowed by the setup answers
# ---------------------------------------------------------------------------------------------------------------
def industry_points(engagement: ClientEngagement, profile: ClientProfile, industry_code: str,
                    sector_rules: List[Dict[str, Any]], record: Optional[Dict[str, Any]]) -> List[AuditFinding]:
    from backend.app.services.setup.engagement_setup import _answered_yes, catalogue
    industry = catalogue()["industries"].get(industry_code.upper()) or {}
    answers = (setup_of(profile).get("industry") or {}).get("answers") or {}
    asked: Dict[str, Tuple[str, Any]] = {}          # query id -> (question, answer)
    for q in industry.get("questions", []):
        for rule in str(q["rules"]).split(","):
            asked[rule.strip()] = (q["label"], answers.get(q["id"]))
    frs105 = bool(record and record["client"]["framework"] == "FRS105")
    models = (setup_of(profile).get("industry") or {}).get("models") or []

    # A query with a trigger is checked against the books instead (query_triggers): raised only when it applies
    from backend.app.services.review.query_triggers import triggers
    triggered = set(triggers())
    sector_rules = [q for q in sector_rules if q.get("Query_ID") not in triggered]
    chosen = []
    unasked = [q for q in sector_rules if q.get("Query_ID") not in asked][:3]    # the library's first general queries
    for q in sector_rules:
        q_id = q.get("Query_ID", "IND-01")
        if q_id in asked:
            label, answer = asked[q_id]
            yes = _answered_yes(answer)
            if yes is False:
                continue
            why = (f"Setup: '{label}' answered {', '.join(answer) if isinstance(answer, list) else 'yes' if answer == 'Y' else answer}."
                   if yes else f"Setup question '{label}' not answered yet: the query stays on until it is.")
            chosen.append((q, why))
        elif q in unasked:
            chosen.append((q, None))

    from backend.app.services.queries.placeholders import fill
    out = []
    for q, why in chosen:
        # No trigger found figures for these, so a template sentence with a blank ('[x]', '[supplier]') is left out
        question = fill(q.get("Query to Client", ""))
        if not question:
            continue
        area = q.get("Account_Area", "Industry Review")
        severity = str(q.get("Severity", "Medium")).upper()
        if severity not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            severity = "MEDIUM"
        ref = (q.get("FRS 105 Ref") if frs105 else None) or q.get("FRS 102 Ref") or "FRS 102"
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref=q.get("Query_ID", "IND-01"),
            procedure_name=f"Sector Audit ({industry_code.upper()}): {area}", severity=severity, source_row_ref=area,
            finding_title=f"{industry_code.upper()} Sector Procedure: {area}",
            finding_details=(f"{question}\n\nEvidence Required: {fill(q.get('Evidence Required', 'Audit schedule'))}. "
                             f"Technical Ref: {ref}." + (f"\n{why}" if why else "")
                             + (f" Business model: {', '.join(models)}." if models else "")),
            quantified_amount=0.0, status="OPEN",
        ))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Depreciation recalculated from the rates on the setup
# ---------------------------------------------------------------------------------------------------------------
# Per asset class: cost codes (cost, additions, disposals, revaluation), accumulated depreciation codes (b/fwd, charge,
# on disposals, on revaluation), the P&L charge codes and the balance sheet charge code
ASSET_CLASS_CODES = {
    "Freehold property": {"cost": (4100, 4101, 4103, 4102), "acc": (4104, 4105, 4107, 4106), "charge": (3405, 1805), "bs": 4105},
    "Leasehold property": {"cost": (4110, 4111, 4113, 4112), "acc": (4114, 4115, 4117, 4116), "charge": (3406, 1806), "bs": 4115},
    "Plant and machinery": {"cost": (4120, 4121, 4122, 4126), "acc": (4123, 4124, 4125, 4129), "charge": (3401, 1801), "bs": 4124},
    "Motor vehicles": {"cost": (4130, 4131, 4132, 4136), "acc": (4133, 4134, 4135, 4139), "charge": (3402, 1802), "bs": 4134},
    "Fixtures and fittings": {"cost": (4140, 4141, 4142, 4146), "acc": (4143, 4144, 4145, 4149), "charge": (3403, 1803), "bs": 4144},
    "Computers": {"cost": (4150, 4151, 4152, 4156), "acc": (4153, 4154, 4155, 4159), "charge": (3404, 1804), "bs": 4154},
}
# Intangible assets (firm chart 4000-4039): checked register v books only; their amortisation is the accountant's
# policy, so no default rate and no depreciation journal
INTANGIBLE_CLASS_CODES = {
    "Goodwill": {"cost": (4000, 4001, 4006, 4008), "acc": (4002, 4005, 4007, 4009)},
    "Other intangible assets": {"cost": (4010, 4011, 4012, 4016), "acc": (4013, 4014, 4015, 4019)},
    "Development costs": {"cost": (4020, 4021, 4022, 4028), "acc": (4023, 4026, 4027, 4029)},
    "Intellectual property": {"cost": (4030, 4031, 4033, 4032), "acc": (4034, 4037, 4039, 4038)},
}
UNALLOCATED_CHARGE = (3400, 1800)
DEPRECIATION_TOLERANCE = 10.0
FIRM_POLICIES_FILE = Path(__file__).resolve().parents[2] / "rules" / "firm_policies.json"
# Last year's charge read as a rate only when it comes out at one of these (else the firm default)
STANDARD_RATES = (10.0, 12.5, 15.0, 20.0, 25.0, 100 / 3, 50.0)
RATE_MATCH = 0.6                # percentage points


ADDITIONS_RULES = ("FULL_YEAR", "PURCHASE_MONTH", "NEXT_MONTH")


def _starting_depreciation() -> Dict[str, Any]:
    """The starting values (rules/firm_policies.json), until the firm saves its own on the Firm settings page."""
    try:
        from backend.app.services.shared import rules_store
        classes = rules_store.load("firm_policies").get("depreciation") or {}
    except (OSError, ValueError):
        classes = {}
    return {"classes": classes, "additions_from": "FULL_YEAR"}


def firm_depreciation_settings(db: Optional[Session] = None) -> Dict[str, Any]:
    """The firm's depreciation defaults: {"classes": {asset class: {method, rate}}, "additions_from"}, as saved on the
    Firm settings page, else the starting values."""
    if db is not None:
        from backend.app.models.firm_settings import FirmSetting
        row = db.get(FirmSetting, "depreciation")
        if row is not None:
            try:
                saved = json.loads(row.value)
                return {"classes": saved.get("classes") or {}, "additions_from": saved.get("additions_from") or "FULL_YEAR"}
            except ValueError:
                pass
    return _starting_depreciation()


def firm_depreciation(db: Optional[Session] = None) -> Dict[str, Dict[str, Any]]:
    """The firm's default depreciation per asset class."""
    return firm_depreciation_settings(db)["classes"]


def last_year_rates(engagement: ClientEngagement, db: Session) -> Dict[str, Dict[str, Any]]:
    """Each asset class's rate as last year's figures show it: last year's charge over last year's cost (straight
    line) or over the cost less the depreciation brought forward (reducing balance), kept when it is a standard rate.
    From last year's client in the app (with its approved journals), else last year's TB when it has the P&L."""
    from backend.app.services.review.last_year import _from_files
    from backend.app.services.tax.ct_computation import final_balances
    balances: Dict[int, float] = {}
    last = _last_year(engagement, db)
    if last is not None:
        tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == last.id)).scalars())
        balances = final_balances(last.id, tb, db)
    else:
        try:
            _, lines = _from_files(engagement, db)
        except Exception:
            lines = []
        for l in lines:
            if l.code is not None:
                balances[l.code] = balances.get(l.code, 0.0) + l.amount
    out: Dict[str, Dict[str, Any]] = {}
    for cls, codes in ASSET_CLASS_CODES.items():
        charge = sum(balances.get(c, 0.0) for c in codes["charge"])
        if charge < 1:
            # the class's own 'charge in year' account when the P&L charge is not split by class
            charge = -balances.get(codes["acc"][1], 0.0)
        cost = sum(balances.get(c, 0.0) for c in codes["cost"])
        acc_cf = -sum(balances.get(c, 0.0) for c in codes["acc"])
        if charge < 1 or cost < 1:
            continue
        for method, base in (("REDUCING_BALANCE", cost - (acc_cf - charge)), ("STRAIGHT_LINE", cost)):
            if base < 1:
                continue
            rate = charge / base * 100
            near = min(STANDARD_RATES, key=lambda r: abs(r - rate))
            if abs(near - rate) <= RATE_MATCH:
                out[cls] = {"method": method, "rate": round(near, 2)}
                break
    return out


def class_rates(engagement: ClientEngagement, profile: Optional[ClientProfile], db: Optional[Session]
                ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], Dict[str, Dict[str, Any]]]:
    """Each asset class's depreciation {method, rate} and where it comes from: the client setup's, else last year's
    (from last year's figures), else the firm default. Also last year's rates. Used by the depreciation points and the
    C1-2 rates tab, so the two always agree."""
    setup_rates = (setup_of(profile).get("policies") or {}).get("depreciation") or {}
    firm = firm_depreciation(db)
    previous = last_year_rates(engagement, db) if db is not None else {}
    # The policy note of last year's accounts filed at Companies House (FRS 102: the same policy each year)
    from backend.app.services.setup.filed_policies import filed_depreciation
    from backend.app.services.review.frs102_checks import period_start
    filed = filed_depreciation(profile, period_start(engagement)) if engagement is not None else {}
    if profile is not None and getattr(profile, "id", None) is not None and "filed_policy" in (profile.companies_house or ""):
        # Kept on the client's record so Companies House is asked once, through its own session (the review's own
        # work is not committed half way)
        from backend.app.core.database import SessionLocal
        own = SessionLocal()
        try:
            row = own.get(ClientProfile, profile.id)
            if row is not None and row.companies_house != profile.companies_house:
                row.companies_house = profile.companies_house
                own.commit()
        except Exception:
            own.rollback()
        finally:
            own.close()
    filed_classes = filed.get("classes") or {}
    rates: Dict[str, Dict[str, Any]] = {}
    source: Dict[str, str] = {}
    for cls in ASSET_CLASS_CODES:
        r = setup_rates.get(cls) or {}
        if r.get("method") == "NONE" or (r.get("method") and r.get("rate")):
            rates[cls], source[cls] = r, "the client setup"
        elif cls in filed_classes:
            rates[cls] = filed_classes[cls]
            source[cls] = f"last year's filed accounts (made up to {filed.get('made_up_to') or 'last year'})"
        elif cls in previous:
            rates[cls], source[cls] = previous[cls], "last year's rate"
        elif cls in firm:
            rates[cls], source[cls] = firm[cls], "the firm default"
    return rates, source, previous


def depreciation_points(engagement: ClientEngagement, profile: ClientProfile, tb_records: List[TBRecord],
                        chart: ChartLookup, journal_counter: List[int],
                        after: Optional[Dict[int, float]] = None,
                        db: Optional[Session] = None, only: Optional[set] = None
                        ) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    """Expected charge = closing cost x rate (straight line, a full year) or (cost - depreciation brought forward) x rate
    (reducing balance), against the charge in the books. A difference on a class with its own charge account proposes a
    journal; a charge posted to the general depreciation account is compared in total.

    The rate per class: the client setup's, else last year's (from last year's figures), else the firm default
    (rules/firm_policies.json: 20% reducing balance), so a client with no asset register and no setup rate is still
    charged."""
    rates, source, previous = class_rates(engagement, profile, db)
    # A rate or method on the setup that differs from last year's (amber: a change of accounting
    # estimate, FRS 102 s10.15-10.18: applied from this year on, disclosed if material; never a prior year restatement)
    method_name_ = {"STRAIGHT_LINE": "straight line", "REDUCING_BALANCE": "reducing balance", "NONE": "not depreciated"}
    change_points: List[AuditFinding] = []
    for cls, r in rates.items():
        before = previous.get(cls)
        if source.get(cls) != "the client setup" or not before:
            continue
        if r.get("method") == before.get("method") and abs(float(r.get("rate") or 0) - float(before.get("rate") or 0)) < 0.01:
            continue
        said = lambda x: (f"{float(x.get('rate') or 0):g}% {method_name_.get(x.get('method'), x.get('method'))}"
                          if x.get("method") != "NONE" else "not depreciated")
        change_points.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-FA-010",
            procedure_name="Depreciation: change of rate", severity="MEDIUM", source_row_ref=f"Depreciation {cls}",
            finding_title=f"{cls}: depreciation {said(r)} this year, {said(before)} last year",
            finding_details=(f"The client setup charges {cls.lower()} at {said(r)}; last year's figures show "
                             f"{said(before)}. A change of depreciation rate or method is a change of accounting "
                             f"estimate (FRS 102 s10.15-10.18): applied from this year, with no change to last year, and "
                             f"disclosed if material. Confirm the change is intended and why (a new useful life), or set "
                             f"the setup back to last year's rate."),
            quantified_amount=0.0, status="OPEN"))
    # Balances after the journals already approved (after: code -> balance), so an approved depreciation journal is
    # not proposed again on the next run
    def bal(*codes: int) -> float:
        if after is None:
            return chart.balance(tb_records, *codes)
        return round(sum(after.get(c, 0.0) for c in codes), 2)
    # A depreciation account still unmapped: that class's depreciation brought forward is not known, so no default
    # rate for it; an unmapped account whose name does not say its class stops them all
    from backend.app.services.review.yearend_journals import FAR_CLASS
    unmapped_classes = {next((c for pattern, c in FAR_CLASS if pattern.search(t.raw_account_name or "")), None)
                        for t in tb_records
                        if t.std_code in (None, 9999) and "deprec" in (t.raw_account_name or "").lower()}
    unmapped = lambda cls: None in unmapped_classes or cls in unmapped_classes
    # This year's additions charged for the months held when the client's or the firm's rule says so (Firm settings:
    # 'from the month of purchase'), dated by their ledger lines on the additions account, as the register path does
    rule = (setup_of(profile).get("policies") or {}).get("additions_from") or \
        firm_depreciation_settings(db)["additions_from"]
    dated: Dict[int, List[Tuple[date, float]]] = {}
    if rule != "FULL_YEAR" and db is not None:
        from backend.app.services.review.payroll_journals import _lines
        add_codes = {codes["cost"][1] for codes in ASSET_CLASS_CODES.values()}
        for code, g in _lines(engagement, tb_records, chart, db):
            if code in add_codes and g.transaction_date and float(g.net_amount or 0) > 0:
                dated.setdefault(code, []).append((g.transaction_date, float(g.net_amount)))
    rows = []
    for cls, codes in ASSET_CLASS_CODES.items():
        if only is not None and cls not in only:
            continue                     # (the asset register gives this class's charge)
        r = rates.get(cls) or {}
        method, rate = r.get("method"), r.get("rate")
        if unmapped(cls) and source.get(cls) != "the client setup":
            continue
        if method in (None, "", "NONE") or not rate:
            continue
        cost = bal(*codes["cost"])
        if abs(cost) < 0.01:
            continue
        booked = bal(*codes["charge"])
        # Depreciation brought forward (a credit, as a positive): the opening balances when the TB has them, else the
        # b/fwd account when the charge sits on its own account, else the closing balance less this year's charge
        acc_rows = [t for t in tb_records if t.std_code in codes["acc"]]
        bfwd, charge_acc = codes["acc"][0], codes["acc"][1]
        if acc_rows and all(t.opening_amount is not None for t in acc_rows):
            acc_bf = -sum(float(t.opening_amount) for t in acc_rows)
            # Less the depreciation taken off for assets sold this year (a net debit on the accounts other than this
            # year's charge; a transfer between them, last year's charge into b/fwd, nets to nil): the cost is after
            # the disposal, so its depreciation must be too (FRS 102 s17)
            acc_bf -= max(0.0, sum(float(t.net_amount or 0) - float(t.opening_amount) for t in acc_rows
                                   if t.std_code != charge_acc))
        elif any(t.std_code == bfwd for t in acc_rows) and any(t.std_code == charge_acc for t in acc_rows):
            acc_bf = -chart.balance(tb_records, bfwd)
        else:
            acc_bf = -bal(*codes["acc"]) - booked
        if after is not None and acc_rows and all(t.opening_amount is not None for t in acc_rows):
            # Depreciation brought forward restored by a journal (the opening balances one): on the b/f account
            journaled = after.get(bfwd, 0.0) - sum(float(t.net_amount or 0) for t in acc_rows if t.std_code == bfwd)
            acc_bf -= journaled
        acc_bf = max(acc_bf, 0.0)
        base = cost if method == "STRAIGHT_LINE" else max(cost - acc_bf, 0.0)
        expected = round(base * float(rate) / 100, 2)
        part_year = ""
        lines = dated.get(codes["cost"][1]) or []
        additions = bal(codes["cost"][1])
        if lines and additions > 0:
            from backend.app.services.review.yearend_journals import _months_held
            total = sum(amt for _, amt in lines)
            # The additions' charge for the months each was held instead of a full year
            unheld = sum(additions * (amt / total) * float(rate) / 100 * (12 - _months_held(d, engagement.period_end_date, rule)) / 12
                         for d, amt in lines)
            expected = round(max(expected - unheld, 0.0), 2)
            held = sorted({_months_held(d, engagement.period_end_date, rule) for d, _ in lines})
            part_year = f"; additions £{additions:,.2f} for {', '.join(str(m) for m in held)} month(s) held"
        rows.append({"cls": cls, "codes": codes, "method": method, "rate": float(rate), "cost": cost, "acc_bf": acc_bf,
                     "base": base, "expected": min(expected, max(cost - acc_bf, 0.0)), "booked": booked,
                     "source": source.get(cls, "the client setup") + part_year})
    if not rows:
        return change_points, []

    unallocated = bal(*UNALLOCATED_CHARGE)
    method_name = {"STRAIGHT_LINE": "straight line", "REDUCING_BALANCE": "reducing balance"}
    working = "; ".join(
        f"{r['cls']}: {r['rate']:g}% {method_name.get(r['method'], r['method'])} ({r['source']}) on £{r['base']:,.2f} = "
        f"£{r['expected']:,.2f}, books £{r['booked']:,.2f}" for r in rows)
    check = ("" if {r["source"] for r in rows} == {"the client setup"} else
             " No asset register: the rate is last year's, or the firm's standard rate where there is none, so please "
             "check it (set the client's own rate on the setup, Policies, to change it).")
    findings, journals = [], []
    if abs(unallocated) >= 0.01:
        # The client's books already charge depreciation (on the general account): compared only at the client's own
        # setup rates, never at a default
        rows = [r for r in rows if r["source"] == "the client setup"]
        if not rows:
            return change_points + findings, journals
        working = "; ".join(f"{r['cls']}: {r['rate']:g}% {method_name.get(r['method'], r['method'])} on £{r['base']:,.2f} = "
                            f"£{r['expected']:,.2f}, books £{r['booked']:,.2f}" for r in rows)
        expected = round(sum(r["expected"] for r in rows), 2)
        booked = round(sum(r["booked"] for r in rows) + unallocated, 2)
        diff = round(expected - booked, 2)
        if abs(diff) > DEPRECIATION_TOLERANCE:
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-FA-004",
                procedure_name="Depreciation recalculated",
                severity="HIGH" if abs(diff) >= 1000 else "MEDIUM", source_row_ref="Depreciation",
                finding_title=f"Depreciation in the books £{booked:,.2f} vs £{expected:,.2f} at the rates used",
                finding_details=(f"Recalculated ({working}). £{unallocated:,.2f} is on the general depreciation account, "
                                 f"so the classes are compared in total: difference £{diff:,.2f}. A full year's charge is "
                                 f"assumed (no time apportioning of additions).{check}"),
                quantified_amount=abs(diff), status="OPEN",
            ))
        return change_points + findings, journals

    for r in rows:
        diff = round(r["expected"] - r["booked"], 2)
        if abs(diff) <= DEPRECIATION_TOLERANCE:
            continue
        if r["source"] != "the client setup" and abs(r["booked"]) >= 1:
            # The client's books already charge depreciation at their own rate: not overwritten by a default
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-FA-004",
                procedure_name="Depreciation recalculated", severity="LOW", source_row_ref=f"Depreciation {r['cls']}",
                finding_title=f"{r['cls']}: depreciation £{r['booked']:,.2f} in the books; £{r['expected']:,.2f} at {r['rate']:g}% ({r['source']})",
                finding_details=(f"The books already charge £{r['booked']:,.2f}. At {r['rate']:g}% "
                                 f"{method_name.get(r['method'], r['method'])} ({r['source']}) on £{r['base']:,.2f} it would "
                                 f"be £{r['expected']:,.2f}. No journal is proposed: the client's own charge is kept. If the "
                                 f"firm's rate should apply, set it on the client setup (Policies) and run the review again."),
                quantified_amount=abs(diff), status="OPEN", figures=_depreciation_figures(r, method_name)))
            continue
        if r["method"] == "STRAIGHT_LINE":
            # Straight line is worked per asset: assets already written off stop being charged, which a class total
            # cannot see, so this is a point to check against the asset register, not a journal
            findings.append(AuditFinding(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-FA-004",
                procedure_name="Depreciation recalculated",
                severity="MEDIUM", source_row_ref=f"Depreciation {r['cls']}",
                finding_title=f"{r['cls']}: depreciation £{r['booked']:,.2f} in the books; up to £{r['expected']:,.2f} at {r['rate']:g}% straight line",
                finding_details=(f"{r['rate']:g}% straight line ({r['source']}) on the closing cost £{r['cost']:,.2f} gives up to £{r['expected']:,.2f} "
                                 f"(depreciation brought forward £{r['acc_bf']:,.2f}); the books show £{r['booked']:,.2f}. Assets "
                                 f"already fully written off are not charged, so work the charge asset by asset from the fixed "
                                 f"asset register (C1-1) before posting."),
                quantified_amount=abs(diff), status="OPEN", figures=_depreciation_figures(r, method_name, on=r["cost"]),
            ))
            continue
        # The P&L side on the firm's general depreciation code (3400: the firm's grouping, not the most specific
        # code), unless the client's own books already charge
        # this class on its class code. A re-run then compares the classes in total (the general account above), so
        # the charge is never proposed twice
        pl = r["codes"]["charge"][0] if abs(r["booked"]) >= 0.01 else UNALLOCATED_CHARGE[0]
        bs = r["codes"]["bs"]
        dr, cr = (pl, bs) if diff > 0 else (bs, pl)
        entry = f"Dr {dr} {chart.name(dr)} (£{abs(diff):,.2f}) / Cr {cr} {chart.name(cr)} (£{abs(diff):,.2f})"
        f = AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-FA-004",
            procedure_name="Depreciation recalculated",
            severity="HIGH" if abs(diff) >= 1000 else "MEDIUM", source_row_ref=f"Depreciation {r['cls']}",
            finding_title=f"{r['cls']}: depreciation £{r['booked']:,.2f} in the books, £{r['expected']:,.2f} at {r['rate']:g}%",
            finding_details=(f"{r['rate']:g}% {method_name.get(r['method'], r['method'])} ({r['source']}) on £{r['base']:,.2f} "
                             f"(cost £{r['cost']:,.2f}, depreciation brought forward £{r['acc_bf']:,.2f}) gives £{r['expected']:,.2f}; "
                             f"the books show £{r['booked']:,.2f}. A full year's charge is assumed (no time apportioning of "
                             f"additions). A journal is proposed (Journals tab): {entry}."
                             + ("" if r["source"] == "the client setup" else
                                " No asset register and no rate on the client setup: please check the rate (set the "
                                "client's own on the setup, Policies, to change it).")),
            quantified_amount=abs(diff), suggested_journal=entry, status="OPEN",
            figures=_depreciation_figures(r, method_name),
        )
        j = ProposedJournal(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{journal_counter[0]:02d}",
            description=f"Depreciation of {r['cls'].lower()} at {r['rate']:g}% ({r['source']})", debit_code=dr, debit_name=chart.name(dr),
            credit_code=cr, credit_name=chart.name(cr), amount=abs(diff), status="PROPOSED",
        )
        journal_counter[0] += 1
        j._point = f
        findings.append(f)
        journals.append(j)
    return change_points + findings, journals


# ---------------------------------------------------------------------------------------------------------------
# Last year's issues, retested
# ---------------------------------------------------------------------------------------------------------------
def _depreciation_figures(r: Dict[str, Any], method_name: Dict[str, str], on: Optional[float] = None) -> Optional[str]:
    """A depreciation point's figures: cost, depreciation brought forward, the figure the rate is charged on, the charge
    worked out, the charge in the books, the difference."""
    from backend.app.services.review.point_figures import amounts
    return amounts([("Cost", r["cost"]), ("Depreciation brought forward", r["acc_bf"]),
                    (f"Charged on ({r['rate']:g}% {method_name.get(r['method'], r['method'])})", r["base"] if on is None else on),
                    ("Depreciation worked out", r["expected"]), ("Depreciation in the books", r["booked"]),
                    ("Difference", r["expected"] - r["booked"], True)])


def _last_year(engagement: ClientEngagement, db: Session) -> Optional[ClientEngagement]:
    earlier = [e for e in db.execute(select(ClientEngagement).where(
                   ClientEngagement.id != engagement.id, ClientEngagement.owner_user_id == engagement.owner_user_id)).scalars()
               if company_key(e.client_name) == company_key(engagement.client_name)
               and e.period_end_date < engagement.period_end_date]
    return max(earlier, key=lambda e: e.period_end_date, default=None)


def prior_year_points(engagement: ClientEngagement, profile: ClientProfile, tb_records: List[TBRecord],
                      chart: ChartLookup, db: Session) -> List[AuditFinding]:
    from backend.app.services.setup.engagement_setup import catalogue
    py = setup_of(profile).get("prior_year") or {}
    issues = py.get("issues") or []
    if not issues:
        return []
    rules = {p["label"]: p["rules"] for p in catalogue()["prior_year_issues"]}
    notes = (py.get("notes") or "").strip()
    out = []
    for issue in issues:
        now, amount = "", 0.0
        if issue == "Overdrawn DLA / s455":
            dla = chart.balance(tb_records, DIRECTORS_LOAN, DIRECTORS_LOAN_LONG_TERM)
            now = (f"This year the director's loan account is £{dla:,.2f} overdrawn: confirm the s455 position."
                   if dla > 0.01 else "This year the director's loan account is not overdrawn.")
            amount = max(dla, 0.0)
        elif issue == "Unreconciled bank / suspense":
            suspense = chart.balance(tb_records, SUSPENSE_CODE)
            now = (f"Suspense holds £{suspense:,.2f} this year: clear it and reconcile the banks."
                   if abs(suspense) >= 0.01 else "Nothing is on suspense this year; confirm the banks reconcile.")
            amount = abs(suspense)
        elif issue == "Open client queries":
            last = _last_year(engagement, db)
            if last is not None:
                still = [f.finding_title for f in db.query(AuditFinding).filter(
                    AuditFinding.engagement_id == last.id, AuditFinding.status == "OPEN",
                    AuditFinding.procedure_ref != "CT-01").all()]
                now = (f"{len(still)} point(s) were still open last year ({last.period_end_date:%d/%m/%Y}): "
                       + "; ".join(t[:80] for t in still[:8]) + (" and others." if len(still) > 8 else ".")) if still \
                    else f"Last year ({last.period_end_date:%d/%m/%Y}) has no open points in the app."
            else:
                now = "Last year is not in the app: check last year's query list."
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="PY-RETEST",
            procedure_name="Last year's issues retested (client setup)", severity="MEDIUM",
            source_row_ref=f"Last year: {issue}"[:100],
            finding_title=f"Last year: {issue} - confirm it is resolved this year"[:255],
            finding_details=(f"Ticked on the client setup as an issue last year; retest ({rules.get(issue, 'review')}). "
                             + (now + " " if now else "") + (f"Notes from the setup: {notes}" if notes else "")).strip(),
            quantified_amount=round(amount, 2), status="OPEN",
        ))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Materiality: trivial points logged, large ones raised
# ---------------------------------------------------------------------------------------------------------------
SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
NOT_SCORED = {"CT-01"}          # the tax computation is not a query
# Points whose amount is a total of the transactions listed (patterns, related party dealings), not an error: their size
# does not raise them; related party dealings are disclosed whatever their size, so they are never logged as trivial
TOTALS_ONLY = ("G9", "RP-")
ALWAYS_REPORTED = ("RP-",)


def apply_materiality(findings: List[AuditFinding], journals: List[ProposedJournal],
                      record: Optional[Dict[str, Any]]) -> List[ProposedJournal]:
    """Returns the journals still proposed (none for a point that is clearly trivial)."""
    m = (record or {}).get("materiality") or {}
    overall, performance, trivial = (float(m[k]) if m.get(k) else None for k in ("overall", "performance", "trivial"))
    if not overall:
        return journals
    logged = set()
    for f in findings:
        amount = float(f.quantified_amount or 0)
        if f.procedure_ref in NOT_SCORED or amount <= 0:
            continue
        if trivial and amount < trivial and not f.procedure_ref.startswith(ALWAYS_REPORTED):
            f.status = "CLEARED"
            f.cleared_at = datetime.utcnow()
            f.cleared_note = (f"{TRIVIAL_NOTE} (£{amount:,.2f} under £{trivial:,.2f}): logged, not sent to the client. "
                              f"Re-open it if it matters.")
            logged.add(id(f))
            continue
        floor, why = None, None
        if f.procedure_ref.startswith(TOTALS_ONLY):
            continue
        if amount >= overall:
            floor, why = "CRITICAL", f"at or above overall materiality £{overall:,.2f}"
        elif performance and amount >= performance:
            floor, why = "HIGH", f"at or above performance materiality £{performance:,.2f}"
        if floor and SEVERITY_ORDER.index((f.severity or "LOW").upper()) < SEVERITY_ORDER.index(floor):
            f.severity = floor
            f.finding_details = (f.finding_details or "") + f"\nMateriality: £{amount:,.2f} is {why}."
    return [j for j in journals if id(getattr(j, "_point", None)) not in logged]
