"""
The CT600 (company tax return) from the tax computation, and the CT queries of the firm's CT600 guide
(rules/ct600_rules.json: 36 box mappings, 21 queries).

  ct600_tab     H2 - CT600 boxes: every box the computation fills, in form order, the boxes to complete by hand,
                and the checks the guide asks for (turnover and tax against the accounts, a period of 12 months)
  ct_queries    the 21 queries, each raised only when the books or the setup show what its trigger describes,
                with the guide's question to the client and its reference
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl.styles import Alignment

from backend.app.models.database import AuditFinding, ClientEngagement, TBRecord
from backend.app.services.review.point_figures import amounts
from backend.app.services.workbook.balance_tabs import BOLD, MONEY, TITLE

RULES = Path(__file__).resolve().parents[2] / "rules" / "ct600_rules.json"
RESERVES_BF = 8000              # profit and loss reserve brought forward: a debit is accumulated losses
DEFERRED_TAX_MIN = 500.0       # a deferred tax movement below this is not raised
LOSS_HINT = 1000.0             # a deficit below this (pennies of rounding, a small first-year loss) is not asked about
WRAP = Alignment(wrap_text=True, vertical="top")
SEVERITY = {"High": "HIGH", "Medium": "MEDIUM", "Low": "LOW"}

# Boxes the computation does not fill: completed by hand in the tax software (from the guide's box list)
BY_HAND = [("3", "Tax reference (UTR)"), ("4", "Type of company (usually 0)"),
           ("40 / 45 / 50 / 55", "Repayment due / claim for an earlier period / more than one return / estimated figures"),
           ("75 / 80", "SME exemption / accounts and computation attached (iXBRL)"),
           ("310 / 312", "Group relief"), ("530 / 545", "R&D credits"), ("595 / 600 / 605", "Tax already paid / outstanding / overpaid"),
           ("625 / 630 / 631", "51% group companies / instalment payments"), ("650–685", "R&D and creative claim indicators"),
           ("860–900", "Repayments and surrenders"), ("920–985", "Bank details, payment authority and declaration")]


def _rules() -> Dict[str, Any]:
    return json.loads(RULES.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------------------------
# H2 - CT600 boxes
# ------------------------------------------------------------------------------------------------------------------
def ct600_tab(wb, comp, engagement: ClientEngagement, company_number: Optional[str]) -> str:
    anchor = "H1-Taxation"
    ws = wb.create_sheet("H2 - CT600 boxes", wb.sheetnames.index(anchor) + 1 if anchor in wb.sheetnames else len(wb.sheetnames))
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    ws["E1"] = "H2"
    ws["A4"] = "CT600 - the boxes, from the tax computation (H1)"
    ws["A4"].font = TITLE
    ws["A5"] = ("Copy these into the tax software. A figure changed on H1 or a choice changed in the app (capital "
                "allowances) needs the review run again and the workbook rebuilt.")
    ws["A5"].alignment = WRAP
    ws.merge_cells("A5:D5")
    ws.row_dimensions[5].height = 30
    for c, h in enumerate(["Box", "What", "Figure", "From"], 1):
        ws.cell(row=7, column=c, value=h).font = BOLD
    rows: List[tuple] = [
        ("1", "Company name", engagement.client_name, "Client"),
        ("2", "Company registration number", company_number or "Complete by hand", "Companies House"),
        ("30", "Period from", comp.period_start, "Accounts"),
        ("35", "Period to", comp.period_end, "Accounts"),
    ]
    # A box's figure is the last computation line carrying it: interest (170), property income (190) and donations
    # (305) appear first as an adjustment to the trading profit and then as the figure for the box
    by_box: Dict[str, float] = {}
    label: Dict[str, str] = {}
    for line in comp.lines:
        if line.box:
            by_box[line.box], label[line.box] = line.amount, line.label
    for box in ("145", "155", "160", "165", "170", "190"):
        if box in by_box:
            rows.append((box, label[box].replace("Less: ", "").replace("Add: ", ""), abs(by_box[box]) if box == "160" else by_box[box], "H1"))
    profits_235 = sum(by_box.get(b, 0.0) for b in ("165", "170", "190"))
    rows.append(("235", "Profits before other deductions and reliefs (165 + 170 + 190)", round(profits_235, 2), "H1"))
    for box in ("300", "305", "315"):
        if box in by_box:
            rows.append((box, label[box].replace("Less: ", ""), abs(by_box[box]) if box == "305" else by_box[box], "H1"))
    rows.append(("326", "Associated companies in the period", comp.associated_companies, "Client setup"))
    fy_boxes = [("330", "335", "340", "345"), ("380", "385", "390", "395")]
    for i, sl in enumerate(comp.rate_slices[:2]):
        fy = sl["from"].year if sl["from"].month >= 4 else sl["from"].year - 1
        b_fy, b_profit, b_rate, b_tax = fy_boxes[i]
        rows.append((b_fy, f"Financial year {fy}", fy, "H1"))
        rows.append((b_profit, f"Profits in FY{fy} ({sl['from']:%d/%m/%Y} to {sl['to']:%d/%m/%Y})", sl["profit"], "H1"))
        rows.append((b_rate, "Tax rate", f"{sl['rate']:.0%}", "H1"))
        rows.append((b_tax, "Tax at that rate", sl["tax_at_rate"], "H1"))
    relief = round(sum(sl["marginal_relief"] for sl in comp.rate_slices), 2)
    rows.append(("430", "Corporation tax (before marginal relief)",
                 round(sum(sl["tax_at_rate"] for sl in comp.rate_slices), 2), "H1"))
    if relief:
        rows.append(("435", "Marginal relief", relief, "H1"))
    rows.append(("440", "Corporation tax chargeable", round(by_box.get("440", 0.0), 2), "H1"))
    if "450" in by_box:
        rows.append(("450", "Double taxation relief", abs(by_box["450"]), "H1"))
    if comp.s455_tax:
        rows.append(("480", "Tax payable on loans to participators (s455, from CT600A box A80)", comp.s455_tax, "H1 / G3"))
        rows.append(("485", "CT600A supplementary page attached", "X", ""))
    rows.append(("510", "Tax chargeable", round(by_box.get("510", comp.total_tax), 2), "H1"))
    if "620" in by_box:
        rows.append(("620", "Franked investment income (exempt dividends)", abs(by_box["620"]), "H1"))
    for a in comp.capital_allowances:
        rows.append((a.box, a.label, a.amount, "Capital allowances (Review tab choices)"))
    if "705" in by_box:
        rows.append(("705", "Balancing charges", by_box["705"], "H1"))

    r = 8
    for box, what, value, source in rows:
        ws.cell(row=r, column=1, value=box)
        ws.cell(row=r, column=2, value=what).alignment = WRAP
        cell = ws.cell(row=r, column=3, value=value)
        if isinstance(value, date):
            cell.number_format = "dd/mm/yyyy"
        elif isinstance(value, float):
            cell.number_format = MONEY
        ws.cell(row=r, column=4, value=source)
        r += 1
    tax_row = next(i for i, row in enumerate(rows, 8) if row[0] == "440")
    turnover_row = next((i for i, row in enumerate(rows, 8) if row[0] == "145"), None)

    r += 1
    ws.cell(row=r, column=1, value="Checks (CT600 guide)").font = BOLD
    r += 1
    checks = [("Box 440 less the tax charge in the accounts (ETB 3800): nil before filing",
               f"=ROUND(C{tax_row}-SUMIF('B1-ETB'!$A:$A,3800,'B1-ETB'!$N:$N),2)")]
    if turnover_row:
        checks.append(("Box 145 less turnover in the accounts (ETB sales, codes below 500): nil",
                       f"=ROUND(C{turnover_row}+SUMIF('B1-ETB'!$A:$A,\"<500\",'B1-ETB'!$N:$N),2)"))
    months = (comp.period_end.year - comp.period_start.year) * 12 + comp.period_end.month - comp.period_start.month + \
        (1 if comp.period_end.day >= comp.period_start.day - 1 else 0)
    checks.append(("Period of the return (months)", months))
    for text, value in checks:
        ws.cell(row=r, column=2, value=text).alignment = WRAP
        cell = ws.cell(row=r, column=3, value=value)
        if isinstance(value, str):
            cell.number_format = MONEY
        r += 1
    if comp.days > 366:
        ws.cell(row=r, column=2, value="The accounts cover more than 12 months: two CT600 returns are needed "
                                       "(the first 12 months and the rest).").font = BOLD
        r += 1

    r += 1
    ws.cell(row=r, column=1, value="Complete by hand (the books do not hold these)").font = BOLD
    for box, what in BY_HAND:
        r += 1
        ws.cell(row=r, column=1, value=box)
        ws.cell(row=r, column=2, value=what)
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 64
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 30
    return ws.title


# ------------------------------------------------------------------------------------------------------------------
# The 21 CT queries
# ------------------------------------------------------------------------------------------------------------------
def _names(tb_records: List[TBRecord], pattern: str, codes=None, credit: Optional[bool] = None,
           minimum: float = 0.0) -> List[tuple]:
    rx = re.compile(pattern, re.I)
    out = []
    for t in tb_records:
        v = float(t.net_amount or 0)
        if not rx.search(t.raw_account_name or "") or (codes is not None and t.std_code not in codes):
            continue
        if credit is True and v > -minimum or credit is False and v < minimum or abs(v) < minimum:
            continue
        out.append((t.raw_account_name, round(v, 2)))
    return out


def last_year_wdv(engagement: ClientEngagement) -> Optional[float]:
    """Last year's tax written-down value (pools carried forward, CAA 2001 s59) as its working paper states it, read
    when last year's WP was uploaded (ingestion/last_year_adjustments.tax_wdv_carried_forward); None when not found."""
    import json as _json
    profile = getattr(engagement, "profile", None)
    try:
        inputs = _json.loads(getattr(profile, "tax_inputs", None) or "{}")
    except ValueError:
        return None
    value = (inputs.get("_last_year_wp") or {}).get("wdv_cf")
    return float(value) if isinstance(value, (int, float)) and value >= 1 else None


def deferred_tax_working(engagement: ClientEngagement, comp, balances: Dict[int, float],
                         chart: Dict[int, Any]) -> Optional[Dict[str, float]]:
    """Deferred tax on fixed assets whose book value is above their tax value (allowances given faster than
    depreciation: 100% AIA / FYA). FRS 102 s29 (T-002): (net book value less tax written-down value) x the rate expected
    when it reverses (T-005: the marginal rate), never discounted. None for a micro-entity (FRS 105 para 24.7: no
    deferred tax) or with no fixed assets. For FRS 102 the journal is proposed and the accountant decides whether to
    post it; a rejected proposal is common. {"nbv", "wdv", "rate", "needed", "provided"}."""
    # Land and property (4100-4119) get no capital allowances: their depreciation is never deductible, a permanent
    # difference, so no deferred tax on it (FRS 102 29.8: tax allowances on a fixed asset v its depreciation; 29.10:
    # none on permanent differences). Only the classes that get allowances count
    nbv = round(sum(v for code, v in balances.items() if 4120 <= code <= 4199), 2)
    if nbv < 1:
        return None
    # With no pools brought forward entered: last year's tax written-down value from its working paper when it states
    # one (the pools are carried forward, CAA 2001 s59), else nil (every asset taken as given 100% AIA or FYA), and
    # said so
    from_wp = last_year_wdv(engagement) if comp.pools_missing else None
    wdv = (from_wp if from_wp is not None else 0.0) if comp.pools_missing else round(comp.main_pool_cf + comp.special_pool_cf, 2)
    from backend.app.services.review.frs102_checks import MICRO, NEW_LIMITS_FROM, period_start
    start = period_start(engagement)
    months = max(1, round((engagement.period_end_date - start).days / 30.44))
    lim = MICRO["new" if start >= NEW_LIMITS_FROM else "old"]
    turnover = -sum(v for code, v in balances.items() if code in chart and chart[code].category == "Sales") * 12 / months
    assets = sum(v for code, v in balances.items() if code in chart and chart[code].financial_class == "Balance Sheet"
                 and v > 0 and chart[code].category not in ("Profit and loss account", "Share capital"))
    # Micro is two of the three limits (turnover, balance sheet total, employees: CA 2006 s384A), as the F-002 size
    # check; the framework the accountant confirmed on the setup decides first (FRS 105: none; FRS 102: s29 applies)
    import json as _json
    from sqlalchemy.orm import object_session
    from backend.app.services.review.frs102_checks import _employees
    profile = getattr(engagement, "profile", None)
    framework = getattr(profile, "accounting_framework", None)
    try:
        chosen = "accounting_framework" in _json.loads(getattr(profile, "confirmed_fields", None) or "[]")
    except ValueError:
        chosen = False
    session = object_session(engagement)
    staff = _employees(engagement, session) if session is not None else None
    over = (turnover > lim[0]) + (assets > lim[1]) + (staff is not None and staff > lim[2])
    if (framework == "FRS105") if chosen else over < 2:
        return None
    profits = comp.profits_chargeable
    rate = 0.25 if profits >= 250000 else 0.19 if profits <= 50000 else 0.265
    provided = round(-sum(v for code, v in balances.items() if 6100 <= code <= 6199), 2)
    needed = round(max(nbv - wdv, 0.0) * rate, 2)
    return {"nbv": nbv, "wdv": wdv, "rate": rate, "needed": needed, "provided": provided,
            "wdv_source": "last_year_wp" if from_wp is not None else ("nil" if comp.pools_missing else "pools")}


def ct_queries(engagement: ClientEngagement, comp, tb_records: List[TBRecord], balances: Dict[int, float],
               chart: Dict[int, Any], lines: List[Any], tax_inputs: Dict[str, Any]) -> List[AuditFinding]:
    queries = {q["Query_ID"]: q for q in _rules()["queries"]}
    found: List[AuditFinding] = []
    bal = lambda code: balances.get(code, 0.0)

    def raise_(qid: str, title: str, evidence: str, amount: float = 0.0, figures: Optional[str] = None) -> None:
        from backend.app.services.queries.placeholders import fill
        q = queries[qid]
        blanks = {"x": f"{abs(amount):,.2f}"} if amount else {}
        found.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_3_CT600", procedure_ref=qid,
            procedure_name=f"CT600: {q['Account_Area']}", severity=SEVERITY.get(q["Severity"], "MEDIUM"),
            source_row_ref="CT600 guide", finding_title=title,
            finding_details=(f"{evidence}\nQuestion: {fill(q['Query to Client'], blanks)}\nEvidence needed: {fill(q['Evidence Required'], blanks)}"
                             f"\nReference: {q['Tax / VAT / HMRC Ref']}"),
            quantified_amount=round(abs(amount), 2), status="OPEN", figures=figures))

    # CT-GEN-001: a period other than 12 months
    if comp.days > 366 or comp.days < 360:
        months = round(comp.days / 30.44, 1)
        raise_("CT-GEN-001", f"The accounts cover about {months:g} months",
               f"Period {comp.period_start:%d/%m/%Y} to {comp.period_end:%d/%m/%Y} ({comp.days} days)."
               + (" Two CT returns are needed: the first 12 months and the rest (CTA 2009 s10), each with its own "
                  "computation, profits split by days (s52) and capital allowances by the date of each purchase. "
                  "No tax journal is proposed on the single computation." if comp.days > 366 else
                  " The CT limits and the annual investment allowance are reduced for a short period."))

    # CT-RATE-001: associated companies not answered, when they would change the tax: the £50,000 / £250,000 limits are
    # divided by the associated companies + 1 (CTA 2010 s18D-E), so one associate already brings the small profits limit
    # to £25,000
    if tax_inputs.get("associated_companies") is None and comp.profits_chargeable > 25000:
        raise_("CT-RATE-001", "Associated companies not confirmed",
               f"Profits chargeable £{comp.profits_chargeable:,.2f}. The £50,000 small profits limit and the £250,000 "
               f"upper limit are divided by the number of associated companies plus one (CTA 2010 s18D-E): with one "
               f"associate the small profits rate stops at £25,000. The setup does not say how many there are.")

    # CT-RATE-002: large company (quarterly instalments). The £1.5m is divided by the 51% group companies, not all
    # associated companies (CTM92520); no instalments when the tax is £10,000 or less, or in the first year over the
    # limit when profits are £10m or less (SI 1998/3175 reg 3, CTM92530)
    group = tax_inputs.get("group_51_companies")
    limit = 1_500_000 / ((int(group) if group is not None else comp.associated_companies) + 1)
    if comp.profits_chargeable > limit and comp.corporation_tax > 10000:
        raise_("CT-RATE-002", "Profits above the large company limit: quarterly instalments",
               f"Profits chargeable £{comp.profits_chargeable:,.2f} exceed £{limit:,.0f}"
               + ("" if group is not None else " (divided by all associated companies: only 51% group companies "
                  "count, so confirm how many there are)")
               + ". Instalments are not due in the first year over the limit if profits are £10m or less and the "
                 "company was not large in the previous 12 months.", comp.profits_chargeable)

    # CT-ADJ-001: costs that may be disallowable and are not on the entertaining code
    adds = _names([t for t in tb_records if t.std_code in chart and chart[t.std_code].financial_class == "Profit and Loss"],
                  r"entertain|hospitality|gift|\bfines?\b|penalt|\bpcn\b|parking (fine|ticket|charge notice)|political",
                  minimum=50)
    adds = [(n, v) for n, v in adds if not re.search(r"staff|employee", n, re.I)]      # staff entertaining is allowable
    if adds:
        raise_("CT-ADJ-001", f"Costs to check for add-back: {len(adds)} account(s)",
               "Accounts: " + "; ".join(f"{n} £{v:,.2f}" for n, v in adds[:8]) + ".", sum(v for _, v in adds),
               figures=amounts([(n, v) for n, v in adds] + [("Total to check", sum(v for _, v in adds), True)]))

    # CT-ADJ-002: accrued bonuses / directors' remuneration at the year end
    accrued = _names(tb_records, r"bonus|remuneration|director'?s? (fee|salar|pay)|salar(y|ies) accru|wages accru",
                     codes={c for c in chart if 5000 <= c < 6000}, credit=True, minimum=500)
    if accrued:
        raise_("CT-ADJ-002", "Remuneration accrued at the year end",
               "Owed at the year end: " + "; ".join(f"{n} £{-v:,.2f}" for n, v in accrued) + ". Allowable only if "
               "paid within 9 months of the year end.", -sum(v for _, v in accrued))

    # CT-ADJ-003: provisions (not depreciation or a specific bad debt)
    provisions = _names(tb_records, r"provision", credit=True, minimum=500)
    # Not the tax accounts (a provision for corporation or deferred tax is the tax itself)
    provisions = [(n, v) for n, v in provisions if not re.search(r"depreciation|amorti|\btax\b|taxation", n, re.I)]
    if provisions:
        raise_("CT-ADJ-003", "Provisions in the accounts",
               "; ".join(f"{n} £{-v:,.2f}" for n, v in provisions) + ". A general provision is not allowable; a "
               "specific one may be.", -sum(v for _, v in provisions))

    # CT-ADJ-004: employer pension owed at the year end (relief only when paid)
    pension = _names(tb_records, r"pension", codes={c for c in chart if 5000 <= c < 6000}, credit=True, minimum=500)
    if pension:
        raise_("CT-ADJ-004", "Pension contributions owed at the year end",
               "; ".join(f"{n} £{-v:,.2f}" for n, v in pension) + ". Employer contributions get relief when paid, "
               "not when accrued.", -sum(v for _, v in pension))

    # CT-CA-001: additions (cars: CO2 and new or used)
    cars = [a for a in comp.ca_assets if a["choice"] in ("SPECIAL", "MAIN", "FYA") and a["group"] == "Motor vehicles"]
    if comp.ca_assets:
        total = sum(a["cost"] for a in comp.ca_assets)
        raise_("CT-CA-001", f"Fixed asset additions of £{total:,.2f}: invoices"
               + (f" and CO2 for {len(cars)} vehicle(s)" if cars else ""),
               "Additions: " + "; ".join(f"{a['description'][:40]} £{a['cost']:,.2f}" for a in comp.ca_assets[:8])
               + ". The treatment of each is on the Review tab (capital allowances).", total,
               figures=amounts([(a["description"][:60], a["cost"]) for a in comp.ca_assets]
                               + [("Total additions", total, True)], "Cost"))

    # CT-CA-002: disposals
    from backend.app.services.tax.ct_computation import DISPOSALS
    disposed = sum(-bal(cost) for cost, _ in DISPOSALS.values() if bal(cost) < 0)
    if disposed >= 1:
        raise_("CT-CA-002", f"Fixed asset disposals: cost £{disposed:,.2f}",
               "Sale proceeds go to the pool (a balancing allowance or charge); the computation estimated them from "
               "the accounts.", disposed)

    # CT-CA-003: pools brought forward not entered, but the company held assets last year
    held_bf = sum(v for code, v in balances.items() if 4120 <= code < 4160 and code % 10 == 0 and v > 0)
    if held_bf >= 1 and not tax_inputs.get("main_pool_bf") and not tax_inputs.get("special_pool_bf"):
        raise_("CT-CA-003", "Capital allowance pools brought forward not entered",
               f"The company holds plant, vehicles or equipment (cost £{held_bf:,.2f}) but the setup has no main or "
               f"special rate pool brought forward, so no writing-down allowance is given on them."
               + (f" Last year's working paper gives a tax written-down value of £{last_year_wdv(engagement):,.2f}: "
                  f"enter it on the tax setup, split into the main pool and the special rate pool (cars over "
                  f"50g/km), as last year's tax computation shows." if last_year_wdv(engagement) else ""))

    # CT-DT-001: deferred tax on fixed assets (deferred_tax_working); its journal is proposed by the review
    dt = deferred_tax_working(engagement, comp, balances, chart)
    if dt is not None and abs(dt["needed"] - dt["provided"]) >= DEFERRED_TAX_MIN:
        nbv, wdv, rate, needed, provided = dt["nbv"], dt["wdv"], dt["rate"], dt["needed"], dt["provided"]
        raise_("CT-DT-001", f"Deferred tax: £{needed:,.2f} on fixed assets ({rate:.1%} of £{nbv - wdv:,.2f}); "
                            f"£{provided:,.2f} in the books",
               f"Fixed assets' net book value £{nbv:,.2f} less their tax value "
               + ("(last year's tax written-down value from its working paper, as no pools are entered; this "
                  "year's allowances are not yet taken off it: enter the pools for the exact figure) "
                  if dt.get("wdv_source") == "last_year_wp" else
                  "(not known: no pools brought forward are entered, so taken as nil, as when every asset had "
                  "100% AIA or FYA; enter the pools to correct it) " if comp.pools_missing
                  else "(pools carried forward) ") + f"£{wdv:,.2f} "
               f"= £{nbv - wdv:,.2f} of allowances given ahead of depreciation. Deferred tax at the rate expected "
               f"when it reverses ({rate:.1%}{', the marginal rate' if rate == 0.265 else ''}) is £{needed:,.2f} "
               f"(FRS 102 s29); the books hold £{provided:,.2f}. A journal for the difference is proposed (Dr 3801 "
               f"Deferred taxation / Cr 6100 Deferred tax): approve it to provide, or reject it; small companies show it "
               f"in the notes (FRS 102 1AC).", abs(needed - provided))

    # CT-IN-001: goodwill amortisation added back, a query every time: relief on goodwill and customer-related assets
    # is restricted (CTA 2009 s816A, s849B, s879A-O)
    if getattr(comp, "goodwill_added_back", 0.0) >= 0.01:
        found.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_3_CT600", procedure_ref="CT-IN-001",
            procedure_name="CT600: intangible assets", severity="MEDIUM", source_row_ref="H1-Taxation",
            finding_title=f"Goodwill amortisation £{comp.goodwill_added_back:,.2f} added back: when and from whom was it "
                          f"bought?",
            finding_details=(f"£{comp.goodwill_added_back:,.2f} of goodwill amortisation / impairment is added back in the "
                             f"computation. Relief is restricted (CTA 2009 Part 8): none for goodwill created before 1 April "
                             f"2002, bought from a related individual (as on incorporation from the director's own "
                             f"business, s849B) or bought from 8 July 2015 to 31 March 2019 (s816A); from 1 April 2019 only "
                             f"6.5% a year of the cost and only when bought with qualifying IP (s879A-s879O).\nQuestion: "
                             f"When was the goodwill bought, from whom, and was it bought with any patents, designs or "
                             f"software?\nEvidence needed: the sale agreement.\nIf relief is due, enter the allowable "
                             f"amount on the client setup (Amortisation confirmed allowable)."),
            quantified_amount=round(comp.goodwill_added_back, 2), status="OPEN"))

    # CT-LOS-001: losses brought forward not entered, but the reserves brought forward are in deficit: the company has
    # made losses, likely trading losses to carry forward (CTA 2010 s45, s45A). Asked, not guessed: a
    # missing input is a query
    deficit = round(bal(RESERVES_BF), 2)
    from_wp = (tax_inputs.get("_last_year_wp") or {}).get("losses_cf")        # read from last year's WP (H1)
    if tax_inputs.get("losses_bf") in (None, "") and not from_wp and deficit >= LOSS_HINT:
        # Asked in a loss year too: last year's losses carried forward still set this year's losses carried forward
        # on the CT600, and once the year's figures are finished (closing stock, accruals) there may be a profit
        effect = (f"the tax of £{comp.corporation_tax:,.2f} is worked out with no losses" if comp.corporation_tax > 0
                  else f"this year shows a loss of £{comp.trading_loss:,.2f}, and the losses carried forward on the "
                       f"CT600 leave out last year's")
        raise_("CT-LOS-001", f"Losses brought forward not entered: reserves brought forward are £{deficit:,.2f} in deficit",
               f"The company has accumulated losses of £{deficit:,.2f} at the start of the year, so it probably has "
               f"trading losses to carry forward against this year's profit (CTA 2010 s45 / s45A), but none are "
               f"entered: {effect}. Enter the losses carried "
               f"forward from last year's CT600 under Corporation tax in the client details.", deficit,
               figures=amounts([("Reserves brought forward (deficit)", deficit), ("Losses brought forward entered", None),
                                ("Corporation tax worked out", comp.corporation_tax, True)]))
    # CT-LOS-001: losses brought forward used
    elif float(tax_inputs.get("losses_bf") or 0) > 0:
        raise_("CT-LOS-001", f"Trading losses brought forward £{float(tax_inputs['losses_bf']):,.2f}",
               f"Used this year £{comp.losses_used:,.2f}; carried forward £{comp.losses_carried_forward:,.2f}. "
               f"Agree the figure to last year's CT600.", float(tax_inputs["losses_bf"]),
               figures=amounts([("Losses brought forward", float(tax_inputs["losses_bf"])),
                                ("Used this year", comp.losses_used),
                                ("Carried forward", comp.losses_carried_forward, True)]))

    # CT-LOS-002: a trading loss this year
    if comp.trading_loss > 1:
        raise_("CT-LOS-002", f"Trading loss of £{comp.trading_loss:,.2f}",
               "Choose the claim: against this year's other profits, carried back 12 months, or carried forward.",
               comp.trading_loss,
               figures=amounts([("Trading loss this year", comp.trading_loss, True),
                                ("Losses carried forward", comp.losses_carried_forward)]))

    # CT-DON-001: charitable donations
    from backend.app.services.tax.ct_computation import CHARITABLE_DONATIONS
    if bal(CHARITABLE_DONATIONS) >= 1:
        raise_("CT-DON-001", f"Charitable donations £{bal(CHARITABLE_DONATIONS):,.2f}",
               "Relieved as qualifying donations (box 305) when paid to a registered charity with no benefit back.",
               bal(CHARITABLE_DONATIONS))

    # CT-A-001 / 002 / 003: the director's loan
    dla = [l for l in lines if 5400 <= l.code < 5410]
    if comp.s455_tax:
        raise_("CT-A-001", f"s455 £{comp.s455_tax:,.2f}: repayments after the year end",
               "The tax is not due on any part repaid within 9 months of the year end (s458): ask what was repaid and when.",
               comp.s455_tax)
        start = comp.period_end - timedelta(days=30)
        repaid = sum(l.credit for l in dla if l.when >= start and l.credit > 0)
        if repaid >= 5000:
            raise_("CT-A-002", f"£{repaid:,.2f} paid into the director's loan in the last 30 days of the year",
                   "If new drawings of £5,000 or more followed within 30 days, the repayment is matched to them (s464C, "
                   "'bed and breakfasting') and the relief is lost.", repaid)
    written = [l for l in dla if l.credit > 0 and re.search(r"write|written|waive|release", l.description or "", re.I)]
    if written:
        raise_("CT-A-003", "Director's loan written off or released",
               "; ".join(f"{l.when:%d/%m/%Y} {l.description[:50]} £{l.credit:,.2f}" for l in written[:5]),
               sum(l.credit for l in written))

    # CT-L-001: research and development
    rd = _names([t for t in tb_records if t.std_code in chart and chart[t.std_code].financial_class == "Profit and Loss"],
                r"research|\br ?& ?d\b|development cost|prototype", credit=False, minimum=1000)   # costs, not income
    if rd:
        raise_("CT-L-001", "Research and development costs", "; ".join(f"{n} £{v:,.2f}" for n, v in rd),
               sum(v for _, v in rd))

    # CT-C-001: group relief (associated companies and a loss)
    if comp.associated_companies and comp.trading_loss > 1:
        raise_("CT-C-001", "Associated companies and a trading loss: group relief?",
               f"{comp.associated_companies} associated companies; trading loss £{comp.trading_loss:,.2f}.")

    # CT-H-001: royalties
    roy = [l for l in lines if l.debit > 0 and re.search(r"royalt", f"{l.account} {l.description}", re.I)]
    if roy:
        raise_("CT-H-001", f"Royalties paid: £{sum(l.debit for l in roy):,.2f}",
               "Check for overseas recipients (withholding tax, CT600H).", sum(l.debit for l in roy))

    # CT-B-001: investments in subsidiaries or overseas
    subs = _names(tb_records, r"subsidiar|overseas|foreign branch", codes={c for c in chart if 4000 <= c < 4400},
                  credit=False, minimum=1)
    if subs:
        raise_("CT-B-001", "Investments in subsidiaries or overseas", "; ".join(f"{n} £{v:,.2f}" for n, v in subs))

    # CT-J-001: tax arrangements (DOTAS)
    dotas = [l for l in lines if re.search(r"\bdotas\b|scheme reference|\bsrn\b|employee benefit trust|\bebt\b|"
                                           r"contractor loan|tax (planning )?scheme", f"{l.account} {l.description}", re.I)]
    if dotas:
        raise_("CT-J-001", "Possible tax arrangement in the ledger",
               "; ".join(f"{l.when:%d/%m/%Y} {l.description[:60]}" for l in dotas[:5]))
    return found
