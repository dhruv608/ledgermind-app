"""The return's figures by form and box, to enter in TaxCalc. Box
numbers are HMRC's 2025-26 forms (SA100 2026, SA102 2026, SA103S 2026, SA103F 2026, SA105 2026, all HMRC 12/25).

  SA102    a page for each employment: pay (1), tax taken off (2), PAYE reference (4), employer (5)
  SA103S   turnover under £90,000: turnover (9), other income (10), trading allowance (10.1), the costs in boxes 11 to
           19 and their total (20; under £90,000 the total alone may be given), net profit or loss (21 / 22), capital
           allowances (25), balancing charges (26), profit for tax (28), loss brought forward used (29), taxable
           profit (31), loss (32), loss carried forward (35), CIS deductions (38)
  SA103F   £90,000 or more: boxes 15 to 30 as the headings, the disallowed part of each in 32 to 45, total
           disallowed (46), net profit or loss (47 / 48), capital allowances (57), balancing charge (59), loss brought
           forward (74), taxable profit (76), loss carried forward (80), CIS (81)
  SA105    the person's share of all UK properties together (one property business): rents (20), property allowance
           (20.1), boxes 24 to 29, adjusted profit or loss (38 / 41), loss brought forward used (39), taxable profit
           (40), loss carried forward (43), residential finance costs (44) and last year's unused (45)
  SA100    TR3: interest (2), UK dividends (4), State Pension (8), other pensions (11) and their tax (12),
           Jobseeker's Allowance (15), other taxable benefits (16); TR4: relief at source pension payments with the
           basic rate tax (1, grossed up), Gift Aid as paid (5); TR5: student loans (1 X, 2 and 3 taken by employers),
           Child Benefit charge (1 to 3, only for the one with the higher income), Marriage Allowance (only the one
           who gives it names the spouse)

Simplified expenses go in with the costs they replace: mileage in car, van and travel; use of home in rent, rates,
power and insurance. Pence are kept: TaxCalc rounds as it enters them."""

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

# SA103S boxes for each SA103F heading (the short page has fewer cost boxes)
SHORT_BOX = {"TURNOVER": "9", "OTHER_INCOME": "10", "COST_OF_SALES": "11", "SUBCONTRACTORS": "13", "STAFF": "13",
             "TRAVEL": "12", "PREMISES": "14", "REPAIRS": "15", "OFFICE": "18", "ADVERTISING": "19",
             "LOAN_INTEREST": "17", "FINANCE": "17", "BAD_DEBTS": "19", "PROFESSIONAL": "16", "DEPRECIATION": None,
             "OTHER": "19"}
SHORT_LABEL = {"11": "Costs of goods bought for resale or goods used", "12": "Car, van and travel expenses",
               "13": "Wages, salaries and other staff costs", "14": "Rent, rates, power and insurance costs",
               "15": "Repairs and maintenance of property and equipment",
               "16": "Accountancy, legal and other professional fees",
               "17": "Interest and bank and credit card financial charges",
               "18": "Phone, fax, stationery and other office costs", "19": "Other allowable business expenses"}


CA_LABEL_S = {"23": "Annual Investment Allowance", "24": "Allowance for small balance of unrelieved expenditure",
              "24.1": "Zero-emission car allowance", "25": "Other capital allowances",
              "25.1": "The Structures and Buildings Allowance"}
CA_LABEL_F = {"49": "Annual Investment Allowance", "50": "Capital allowances at 18% on equipment, including cars",
              "51": "Capital allowances at 6% on equipment, including cars", "52.1": "Zero-emission car allowance",
              "53": "The Structures and Buildings Allowance", "55": "100% and other enhanced capital allowances",
              "56": "Allowances on sale or cessation of business use"}


def allowance_boxes(lines, page):
    from backend.app.sa.allowances import boxes as ca_boxes
    return ca_boxes(lines, page)


def _row(box: str, label: str, value, note: str = "", doc_id: Optional[int] = None) -> Dict:
    return {"box": box, "label": label, "value": value, "note": note, "doc_id": doc_id}


def _money(v) -> float:
    return round(float(v or 0), 2)


def employment(lines) -> List[Dict]:
    """One SA102 page per employment; a P11D benefit (kind BENEFIT, its box in the note) on its employer's page."""
    pages, by_name = [], {}
    for l in lines:
        if l.source != "EMPLOYMENT" or not l.include or l.kind == "BENEFIT":
            continue
        paye = (l.note or "").replace("PAYE ", "") if (l.note or "").startswith("PAYE ") else ""
        share = float(l.share if l.share is not None else 1)
        page = {"form": "SA102", "title": f"Employment: {l.label}", "rows": [
            _row("1", "Pay from this employment", _money(float(l.amount or 0) * share), doc_id=l.doc_id),
            _row("2", "UK tax taken off pay in box 1", _money(l.tax_paid), doc_id=l.doc_id),
            _row("4", "PAYE tax reference of your employer", paye or None, "" if paye else "Not on the line: from the P60"),
            _row("5", "Your employer's name", l.label),
        ]}
        pages.append(page)
        by_name.setdefault((l.label or "").lower(), page)
    for l in lines:
        if l.source != "EMPLOYMENT" or not l.include or l.kind != "BENEFIT":
            continue
        box, _, what = (l.note or "SA102 box 15: Other benefits").replace("SA102 box ", "").partition(": ")
        page = by_name.get((l.label or "").lower())
        if page is None:
            page = {"form": "SA102", "title": f"Employment: {l.label}", "rows": [_row("5", "Your employer's name", l.label)]}
            pages.append(page)
            by_name[(l.label or "").lower()] = page
        page["rows"].append(_row(box, what or "Benefit", _money(float(l.amount or 0) * float(l.share or 1)), doc_id=l.doc_id))
    return pages


def _short(b: Dict) -> List[Dict]:
    h = b["headings"]
    rows = [_row("9", "Your turnover", _money(h["TURNOVER"]["amount"])),
            _row("10", "Any other business income", _money(h["OTHER_INCOME"]["amount"]))]
    if b["trading_allowance"]:
        rows.append(_row("10.1", "Trading income allowance", _money(b["trading_allowance"]),
                         "Instead of every cost: boxes 11 to 20 left blank"))
    else:
        boxes: Dict[str, float] = {}
        for key, (_, _, kind) in _headings().items():
            box = SHORT_BOX.get(key)
            if kind != "cost" or box is None:
                continue
            boxes[box] = boxes.get(box, 0.0) + h[key]["amount"] - h[key]["disallowed"]
        boxes["12"] = boxes.get("12", 0.0) + b["mileage"]
        boxes["14"] = boxes.get("14", 0.0) + b["use_of_home"]
        for box in sorted(boxes, key=int):
            if round(boxes[box], 2):
                note = ("Includes mileage at the flat rate" if box == "12" and b["mileage"] else
                        "Includes use of home at the flat rate" if box == "14" and b["use_of_home"] else "")
                rows.append(_row(box, SHORT_LABEL[box], _money(boxes[box]), note))
        total = round(sum(boxes.values()), 2)
        rows.append(_row("20", "Total allowable expenses", total, "Under £90,000 the total alone may be given"))
        net = round(b["income"] - total, 2)
        rows.append(_row("21", "Net profit", net) if net >= 0 else _row("22", "Net loss", -net))
        if b.get("allowances"):
            for r in allowance_boxes(b["allowances"], "SA103S"):
                rows.append(_row(r["box"], CA_LABEL_S[r["box"]], r["value"]))
        elif b["capital_allowances"]:
            rows.append(_row("25", "Other capital allowances", _money(b["capital_allowances"]),
                             "Split into box 23 (Annual Investment Allowance) if it is AIA"))
    if b["balancing_charges"]:
        rows.append(_row("26", "Total balancing charges", _money(b["balancing_charges"])))
    adjusted = b["adjusted_profit"]
    if adjusted >= 0:
        rows.append(_row("28", "Net business profit for tax purposes", _money(adjusted)))
    if b["losses_used"]:
        rows.append(_row("29", "Loss brought forward set off against this year's profits", _money(b["losses_used"])))
    if adjusted >= 0:
        rows.append(_row("31", "Total taxable profits from this business", _money(b["taxable_profit"])))
    else:
        rows.append(_row("32", "Net business loss for tax purposes", _money(-adjusted)))
    if b.get("loss_current"):
        rows.append(_row("33", "Loss from this tax year set off against other income", _money(b["loss_current"])))
    if b.get("loss_back"):
        rows.append(_row("34", "Loss to be carried back to previous years and set off against income",
                         _money(b["loss_back"]), "Give the details in 'Any other information'"))
    if b["loss_cf"]:
        rows.append(_row("35", "Total loss to carry forward", _money(b["loss_cf"])))
    rows.extend(_nic_rows(b, "36", "37"))
    if b["cis_deducted"]:
        rows.append(_row("38", "Total CIS deductions taken by contractors", _money(b["cis_deducted"])))
    return rows


def _full(b: Dict) -> List[Dict]:
    h = b["headings"]
    rows = [_row("15", "Your turnover", _money(h["TURNOVER"]["amount"])),
            _row("16", "Any other business income", _money(h["OTHER_INCOME"]["amount"]))]
    if b["trading_allowance"]:
        rows.append(_row("16.1", "Trading income allowance", _money(b["trading_allowance"])))
    else:
        for key, (label, box, kind) in _headings().items():
            if kind != "cost":
                continue
            amount = h[key]["amount"] + (b["mileage"] if key == "TRAVEL" else b["use_of_home"] if key == "PREMISES" else 0)
            if round(amount, 2):
                rows.append(_row(str(box), label, _money(amount)))
            if round(h[key]["disallowed"], 2):
                rows.append(_row(str(box + 15), f"{label}: disallowable", _money(h[key]["disallowed"])))
        total = round(b["costs"] + b["mileage"] + b["use_of_home"], 2)
        rows.append(_row("31", "Total expenses", total))
        if b["disallowed"]:
            rows.append(_row("46", "Total disallowable expenses", _money(b["disallowed"])))
        net = round(b["income"] - total, 2)
        rows.append(_row("47", "Net profit", net) if net >= 0 else _row("48", "Net loss", -net))
        if b.get("allowances"):
            for r in allowance_boxes(b["allowances"], "SA103F"):
                rows.append(_row(r["box"], CA_LABEL_F[r["box"]], r["value"]))
            rows.append(_row("57", "Total capital allowances", _money(b["capital_allowances"])))
        elif b["capital_allowances"]:
            rows.append(_row("57", "Total capital allowances", _money(b["capital_allowances"]),
                             "Split into boxes 49 to 56 by kind"))
    if b["balancing_charges"]:
        rows.append(_row("59", "Balancing charge", _money(b["balancing_charges"])))
    adjusted = b["adjusted_profit"]
    rows.append(_row("64", "Net business profit for tax purposes", _money(adjusted)) if adjusted >= 0
                else _row("65", "Net business loss for tax purposes", _money(-adjusted)))
    if b["losses_used"]:
        rows.append(_row("74", "Loss brought forward set off against this year's profits", _money(b["losses_used"])))
    if adjusted >= 0:
        rows.append(_row("76", "Total taxable profits from this business", _money(b["taxable_profit"])))
    if adjusted < 0:
        rows.append(_row("77", "Adjusted loss for the year", _money(-adjusted)))
    if b.get("loss_current"):
        rows.append(_row("78", "Loss from this tax year set off against other income", _money(b["loss_current"])))
    if b.get("loss_back"):
        rows.append(_row("79", "Loss to be carried back to previous years and set off against income",
                         _money(b["loss_back"]), "Give the details in 'Any other information'"))
    if b["loss_cf"]:
        rows.append(_row("80", "Total loss to carry forward", _money(b["loss_cf"])))
    if b["cis_deducted"]:
        rows.append(_row("81", "Total CIS deductions taken by contractors", _money(b["cis_deducted"])))
    rows.extend(_nic_rows(b, "100", "101"))
    return rows


def _nic_rows(b: Dict, class2_box: str, class4_box: str) -> List[Dict]:
    """The NIC ticks, on the first business's page only (SA103S 36 / 37, SA103F 100 / 101, 2026 forms)."""
    rows = []
    if b.get("class2_voluntary"):
        rows.append(_row(class2_box, "Profits under the small profits threshold: Class 2 paid voluntarily", "X"))
    if b.get("class4_exempt"):
        rows.append(_row(class4_box, "Exempt from paying Class 4 NICs", "X", {
            "PENSION_AGE": "State Pension age reached before 6 April", "UNDER_16": "Under 16 at 6 April",
            "NON_RESIDENT": "Not resident in the UK for the year"}.get(b["class4_exempt"], "")))
    return rows


def _headings():
    from backend.app.sa.trade import HEADINGS
    return HEADINGS


def self_employment(trade: Dict, calc: Optional[Dict] = None) -> List[Dict]:
    if calc and trade["businesses"]:
        first = trade["businesses"][0]
        first["class2_voluntary"] = bool(calc.get("class2"))
        first["class4_exempt"] = calc.get("class4_exempt") or ""
    return [{"form": b["page"], "title": f"Self-employment: {b['name']}",
             "rows": _short(b) if b["page"] == "SA103S" else _full(b)} for b in trade["businesses"]]


def property_page(prop: Dict) -> List[Dict]:
    if not prop["properties"]:
        return []
    bx = prop["boxes"]
    rows = [_row("1", "Number of properties rented out", str(len([p for p in prop["properties"] if p.get("in_pool", True) or p["profit"]])))]
    if bx.get("RENT_A_ROOM_ONLY"):
        rows.append(_row("4", "Claiming Rent-a-Room relief and the rents are £7,500 or less", "X",
                         "Those rents are not entered anywhere else"))
    rows += [
            _row("20", "Total rents and other income from property", _money(bx["RENT"]))]
    if prop["allowance"]:
        rows.append(_row("20.1", "Property income allowance", _money(prop["allowance_used"]),
                         "Instead of every expense: boxes 24 to 29 and 44 left blank"))
    else:
        for key, box, label in (("RATES_INSURANCE", "24", "Rent, rates, insurance and ground rents"),
                                ("REPAIRS", "25", "Property repairs and maintenance"),
                                ("NONRES_FINANCE", "26", "Non-residential property finance costs"),
                                ("PROFESSIONAL", "27", "Legal, management and other professional fees"),
                                ("SERVICES", "28", "Costs of services provided, including wages"),
                                ("OTHER", "29", "Other allowable property expenses")):
            if round(bx[key], 2):
                rows.append(_row(box, label, _money(bx[key])))
        if round(bx["DOMESTIC_ITEMS"], 2):
            rows.append(_row("36", "Costs of replacing domestic items", _money(bx["DOMESTIC_ITEMS"])))
    if bx.get("RENT_A_ROOM"):
        rows.append(_row("37", "Rent a Room exempt amount", _money(bx["RENT_A_ROOM"])))
    before = prop["before_losses"]
    if before >= 0:
        rows.append(_row("38", "Adjusted profit for the year", _money(before)))
        if prop["losses_used"]:
            rows.append(_row("39", "Loss brought forward used against this year's profits", _money(prop["losses_used"])))
        rows.append(_row("40", "Taxable profit for the year", _money(prop["profit"])))
    else:
        rows.append(_row("41", "Adjusted loss for the year", _money(-before)))
    if prop["loss_cf"]:
        rows.append(_row("43", "Loss to carry forward to following year", _money(prop["loss_cf"])))
    if not prop["allowance"]:
        this_year = round(bx["RES_FINANCE"], 2)
        bf = round(prop["finance_costs"] - this_year, 2)
        if this_year:
            rows.append(_row("44", "Residential property finance costs", this_year))
        if bf:
            rows.append(_row("45", "Unused residential property finance costs brought forward", bf))
    note = "; ".join(f"{p['name']} {p['share'] * 100:g}%" for p in prop["properties"] if p["share"] != 1)
    return [{"form": "SA105", "title": "UK property", "note": f"The person's share: {note}" if note else "",
             "rows": rows}]


def main_return(lines) -> List[Dict]:
    def total(source, kinds, test=None):
        got = [l for l in lines if l.include and l.source == source and l.kind in kinds and (test is None or test(l))]
        return round(sum(float(l.amount or 0) * float(l.share if l.share is not None else 1) for l in got), 2), got

    def jsa(l):
        return "jobseeker" in (l.label or "").lower() or "jsa" in (l.label or "").lower().split()

    tr3, tr4 = [], []
    v, _ = total("SAVINGS", ("INTEREST",))
    if v:
        tr3.append(_row("2", "Untaxed UK interest", v, "Banks and building societies pay interest gross"))
    v, _ = total("DIVIDENDS", ("DIVIDEND",))
    if v:
        tr3.append(_row("4", "Dividends from UK companies", v))
    v, _ = total("PENSIONS", ("STATE_PENSION",))
    if v:
        tr3.append(_row("8", "State Pension", v))
    v, got = total("PENSIONS", ("PENSION",))
    if v:
        tr3.append(_row("11", "Pensions (other than State Pension)", v, "The gross amount"))
        tr3.append(_row("12", "Tax taken off box 11", round(sum(float(l.tax_paid or 0) for l in got), 2)))
    v, _ = total("PENSIONS", ("BENEFIT",), jsa)
    if v:
        tr3.append(_row("15", "Jobseeker's Allowance", v))
    v, _ = total("PENSIONS", ("BENEFIT",), lambda l: not jsa(l))
    if v:
        tr3.append(_row("16", "Total of any other taxable State Pensions and benefits", v))
    v, _ = total("RELIEFS", ("PENSION_RAS",))
    if v:
        tr4.append(_row("1", "Payments to registered pension schemes (relief at source)", round(v / 0.8, 2),
                        f"The payments and basic rate tax: £{v:,.2f} paid ÷ 0.8"))
    v, _ = total("RELIEFS", ("GIFT_AID",))
    if v:
        tr4.append(_row("5", "Gift Aid payments made in the year to 5 April", v, "The amount paid"))
    ai2 = []
    for kind, box, label, note in (("VCT", "1", "Subscriptions for Venture Capital Trust shares", "The amount on which relief is claimed"),
                                   ("EIS", "2", "Subscriptions for Enterprise Investment Scheme shares", "From the EIS3 certificates"),
                                   ("LOAN_INTEREST", "5", "Qualifying loan interest payable in the year", ""),
                                   ("SEIS", "10", "Subscriptions for shares under the Seed Enterprise Investment Scheme", "From the SEIS3 certificates")):
        v, _ = total("RELIEFS", (kind,))
        if v:
            ai2.append(_row(box, label, v, note))
    pages = []
    if ai2:
        pages.append({"form": "SA101 Ai2", "title": "Other tax reliefs", "rows": ai2})
    if tr3:
        pages.append({"form": "SA100 TR3", "title": "Income: interest, dividends, pensions and benefits", "rows": tr3})
    if tr4:
        pages.append({"form": "SA100 TR4", "title": "Tax reliefs", "rows": tr4})
    return pages


def family_page(fam, calc: Dict, tax_year: str) -> List[Dict]:
    """SA100 page TR5: student loans, the Child Benefit charge (only for the one who pays it), Marriage Allowance
    (only for the one who gives it)."""
    if fam is None:
        return []
    from backend.app.sa.engine.calc import rates_for
    from backend.app.sa.family import ME, TRANSFERRED, plans_of
    rows = []
    if (plans_of(fam) or fam.postgraduate) and not fam.studying:
        rows.append(_row("SL 1", "Repayment of an Income Contingent Loan was due before 6 April", "X",
                         ", ".join(p.replace("_", " ").title() for p in plans_of(fam)) + (" and postgraduate" if fam.postgraduate else "")))
        if fam.sl_deducted:
            rows.append(_row("SL 2", "Student Loan repayments deducted by employers", _money(fam.sl_deducted)))
        if fam.pgl_deducted:
            rows.append(_row("SL 3", "Postgraduate Loan repayments deducted by employers", _money(fam.pgl_deducted)))
    if (fam.child_benefit and fam.higher_income == ME
            and calc["adjusted_net_income"] > rates_for(tax_year)["hicbc"]["from"]):
        rows.append(_row("CB 1", "Total Child Benefit you and your partner got for the year", _money(fam.child_benefit)))
        if fam.children is not None:
            rows.append(_row("CB 2", "Number of children Child Benefit was paid for on 5 April", str(fam.children)))
        if fam.cb_stopped:
            rows.append(_row("CB 3", "Date all Child Benefit payments stopped", fam.cb_stopped))
    if fam.marriage == TRANSFERRED:
        first, _, last = (fam.spouse_name or "").partition(" ")
        rows.append(_row("MA 1", "Spouse or civil partner's first name", first or None))
        rows.append(_row("MA 2", "Spouse or civil partner's last name", last or None,
                         "Boxes 3 to 5 (their NI number, date of birth, date of marriage) from the client's file"))
    return [{"form": "SA100 TR5", "title": "Student loans, Child Benefit charge, Marriage Allowance", "rows": rows}] if rows else []


def foreign_property_page(fp: Dict) -> List[Dict]:
    """SA106 pages F4-F5: the overseas property business (all countries together when no foreign tax was paid; with
    foreign tax, a page per country is needed: noted)."""
    if not fp or not fp["properties"]:
        return []
    bx = fp["boxes"]
    expenses = round(sum(bx[k] for k in ("RATES_INSURANCE", "REPAIRS", "NONRES_FINANCE", "PROFESSIONAL", "SERVICES", "OTHER")), 2)
    rows = [_row("14", "Total rents and other receipts", _money(bx["RENT"]))]
    if fp["allowance"]:
        rows.append(_row("14.1", "Property income allowance", _money(fp["allowance_used"])))
    rows.append(_row("15", "Number of overseas let properties", str(len(fp["properties"]))))
    if not fp["allowance"]:
        rows.append(_row("17", "Allowable property expenses", expenses))
        rows.append(_row("18", "Net profit or loss", round(bx["RENT"] - expenses, 2)))
        if bx["DOMESTIC_ITEMS"]:
            rows.append(_row("23", "Costs of replacing domestic items", _money(bx["DOMESTIC_ITEMS"])))
    rows.append(_row("24", "Adjusted profit or loss for the year", _money(fp["before_losses"])))
    if not fp["allowance"]:
        this_year = round(bx["RES_FINANCE"], 2)
        bf = round(fp["finance_costs"] - this_year, 2)
        if this_year:
            rows.append(_row("24.1", "Residential property finance costs", this_year))
        if bf:
            rows.append(_row("24.2", "Unused residential property finance costs brought forward", bf))
    if fp["losses_used"]:
        rows.append(_row("26", "Loss brought forward set off against profits", _money(fp["losses_used"])))
    rows.append(_row("27", "Total taxable profits", _money(fp["profit"])))
    tax = round(sum(c["foreign_tax"] for c in fp["countries"]), 2)
    if tax:
        rows.append(_row("28", "Total foreign tax", tax, "Claiming the credit: a column for each country"))
    if fp["loss_cf"]:
        rows.append(_row("32", "Total loss to carry forward", _money(fp["loss_cf"])))
    countries = ", ".join(sorted({c["country"] for c in fp["countries"]}))
    return [{"form": "SA106 F4-F5", "title": "Land and property abroad", "note": f"Countries: {countries}", "rows": rows}]


def capital_gains_page(cg: Dict) -> List[Dict]:
    """SA108: each section's boxes, then losses (45, 47) and Business Asset Disposal Relief (50)."""
    if not cg or not cg["sections"]:
        return []
    rows = []
    for sec in cg["sections"]:
        for r in sec["rows"]:
            rows.append(_row(r["box"], f"{sec['label']}: {r['label']}", r["value"]))
    s = cg["summary"]
    if s["losses_bf_used"]:
        rows.append(_row("45", "Losses brought forward and used in-year", s["losses_bf_used"]))
    if s["loss_cf"]:
        rows.append(_row("47", "Losses available to be carried forward", s["loss_cf"]))
    if s["badr_gains"]:
        rows.append(_row("50", "Gains qualifying for Business Asset Disposal Relief", s["badr_gains"],
                         "Also in the Other property, assets and gains section"))
    return [{"form": "SA108", "title": "Capital gains", "note": "Send the computation of each gain or loss with the return",
             "rows": rows}]


def result(calc: Dict) -> Dict:
    c = calc["calculation"]
    return {"income_tax_due": c["income_tax_due"], "class4": c["class4"], "class2": c["class2"], "cgt": c.get("cgt", 0.0),
            "liability": c["liability"], "tax_deducted": c["tax_deducted"], "balance": c["balance"],
            "poa_each": c["poa_each"], "due_31_january": c["due_31_january"]}


def boxes(db: Session, job) -> Dict:
    """Every form page with its boxes, and the result the software should agree with."""
    from backend.app.sa.income import calculation
    from backend.app.sa.models import SALine
    lines = db.query(SALine).filter(SALine.job_id == job.id).order_by(SALine.id).all()
    calc = calculation(db, job)
    from backend.app.sa.models import SAFamily
    pages = (employment(lines) + self_employment(calc["trade"], calc["calculation"]) + property_page(calc["property"]) + main_return(lines)
             + family_page(db.get(SAFamily, job.id), calc["calculation"], job.tax_year) + capital_gains_page(calc["cgt"]))
    from backend.app.sa import foreign
    pages += foreign.boxes(calc["foreign"], sum(r["credit"] for r in calc["foreign_property"].get("credits", [])))
    pages += foreign_property_page(calc["foreign_property"])
    left = []
    if any(l.include and l.source == "FOREIGN" for l in lines):
        left.append("Foreign income entered as one figure on an income page: move it to the Foreign page by kind and "
                    "country so it goes on the SA106 with its foreign tax credit.")
    if any(l.include and l.source in ("SELF_EMPLOYMENT", "PROPERTY") and l.kind == "PROFIT" for l in lines):
        left.append("A profit entered as one figure on an income page: enter it on its SA103 or SA105 page by hand.")
    return {"pages": pages, "result": result(calc), "left": left}
