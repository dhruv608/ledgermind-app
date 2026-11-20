"""Fixed assets: C1 lead and C1-1 detail (one column / row per asset class the client uses, from the firm chart's
groups of ten codes), C1.2 capital review (Revenue vs Capital SOP) and C1.3 property review (Rental Property SOP)."""

import re
from copy import copy
from typing import Dict, List, Tuple

from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from backend.app.services.setup.profile_service import confirmed_industry
from backend.app.services.sop.capital import CAPITAL_QUESTION, capital_review, capitalisation_limit
from backend.app.services.sop.property import property_review
from backend.app.services.workbook.context import BuildContext, format_std_code
from backend.app.services.workbook.depreciation_rates import add_rates_tab


def add_fixed_asset_tabs(ctx: BuildContext) -> None:
    wb, engagement, db, tb_records, journals = ctx.wb, ctx.engagement, ctx.db, ctx.tb_records, ctx.journals
    tb_account_list, tb_codes_present, etb_codes = ctx.tb_account_list, ctx.tb_codes_present, ctx.etb_codes
    chart_names, report_notes, bold_font = ctx.chart_names, ctx.report_notes, ctx.bold_font
    remove_sheet = ctx.remove_sheet

    # 1. Tangible Fixed Assets (Section C) - one row per asset class the client uses.
    # The firm chart keeps each class in a group of ten codes (cost, additions, disposals,
    # depreciation b/fwd, charge, ...); the role of each code is read from its chart name.
    fa_codes = sorted({int(c) for c in (etb_codes or tb_codes_present) if str(c).isdigit() and 4100 <= int(c) <= 4199})
    intangible_codes = sorted({int(c) for c in (etb_codes or tb_codes_present) if str(c).isdigit() and 4000 <= int(c) <= 4099})
    if intangible_codes:
        report_notes.append(f"Intangible assets (codes {', '.join(map(str, intangible_codes))}) are not on the C1 fixed assets lead")
    if not fa_codes:
        for s in ["C", "C1 (LEAD)", "C1-1-FA detail"]:
            remove_sheet(s)
    else:
        movement_tb = any(getattr(t, "opening_amount", None) is not None for t in tb_records)
        opening: Dict[int, float] = {}
        tb_net: Dict[int, float] = {}
        for t in tb_records:
            code = int(format_std_code(t.std_code)) if format_std_code(t.std_code).isdigit() else None
            if code is None:
                continue
            if getattr(t, "opening_amount", None) is not None:
                opening[code] = opening.get(code, 0.0) + float(t.opening_amount)
        books_net: Dict[int, float] = {}            # the books' closing balance (a movement TB's opening added)
        for t in tb_records:
            if format_std_code(t.std_code).isdigit():
                code = int(format_std_code(t.std_code))
                books_net[code] = books_net.get(code, 0.0) + float(t.net_amount or 0.0)
        for c, _, deb, cred in tb_account_list:
            if c.isdigit():
                tb_net[int(c)] = tb_net.get(int(c), 0.0) + deb - cred
        jnl_net: Dict[int, float] = {}
        for j in journals:
            c = format_std_code(j.get("code"))
            if c.isdigit():
                jnl_net[int(c)] = jnl_net.get(int(c), 0.0) + float(j.get("debit") or 0) - float(j.get("credit") or 0)

        def fa_role(code: int) -> str:
            name = chart_names.get(code, "").lower()
            dep = re.search(r"depreciation|amortisation", name)
            if re.search(r"b/ ?fwd", name):
                return "DEP_BF" if dep else "COST"
            if dep and re.search(r"disposal|revaluation", name):
                return "DEP_DISP"
            if dep or "impairment" in name:
                return "CHARGE"
            if "disposal" in name:
                return "DISP"
            if "addition" in name or "revaluation" in name:
                return "ADD"
            return "COST"

        def etb(code: int, dr: str, cr: str) -> str:
            return f"(SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!${dr}:${dr})-SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!${cr}:${cr}))"

        classes: List[Tuple[int, str, Dict[str, float], Dict[str, List[str]]]] = []
        for base in sorted({c // 10 * 10 for c in fa_codes}):
            cls_name = re.sub(r"\s*-\s*cost$", "", chart_names.get(base, f"Fixed assets {base}"), flags=re.IGNORECASE)
            v = {k: 0.0 for k in ("D", "E", "F", "H", "K", "L")}
            # The same figures as formulas on B1-ETB (opening F-G, TB H-I, journals J-K), so C1-1 follows the ETB
            f: Dict[str, List[str]] = {k: [] for k in v}
            for code in range(base, base + 10):
                if code not in fa_codes:
                    continue
                role = fa_role(code)
                if ctx.tb_kind:
                    # The ETB reads the ledger: b/fwd is last year's filed TB and the opening adjustment, the
                    # movement the ledger's (and any of the TB it does not explain) and the journals
                    bf = ctx.opening_by_code.get(str(code), 0.0)
                    mv = books_net.get(code, 0.0) - bf + jnl_net.get(code, 0.0)
                    fbf = f"({etb(code, 'F', 'G')}+{etb(code, 'O', 'P')})"
                    fmv = f"{etb(code, 'H', 'I')}+SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!$S:$S)+{etb(code, 'J', 'K')}"
                elif movement_tb:
                    bf, mv = opening.get(code, 0.0), tb_net.get(code, 0.0) + jnl_net.get(code, 0.0)
                    fbf, fmv = etb(code, "F", "G"), f"{etb(code, 'H', 'I')}+{etb(code, 'J', 'K')}"
                elif role in ("COST", "DEP_BF"):
                    bf, mv = tb_net.get(code, 0.0), jnl_net.get(code, 0.0)
                    fbf, fmv = etb(code, "H", "I"), etb(code, "J", "K")
                else:
                    bf, mv = 0.0, tb_net.get(code, 0.0) + jnl_net.get(code, 0.0)
                    fbf, fmv = None, f"{etb(code, 'H', 'I')}+{etb(code, 'J', 'K')}"
                if role in ("COST", "ADD", "DISP"):
                    v["D"] += bf
                    v["E" if role != "DISP" else "F"] += mv if role != "DISP" else -mv
                    if fbf:
                        f["D"].append(f"+{fbf}")
                    f["E" if role != "DISP" else "F"].append(f"+({fmv})" if role != "DISP" else f"-({fmv})")
                else:
                    v["H"] -= bf
                    if fbf:
                        f["H"].append(f"-{fbf}")
                    if role == "DEP_DISP":
                        v["L"] += mv
                        f["L"].append(f"+({fmv})")
                    else:
                        v["K"] -= mv
                        f["K"].append(f"-({fmv})")
            classes.append((base, cls_name, v, f))

        detail = "C1-1-FA detail"
        if detail in wb.sheetnames:
            ws_c1_1 = wb[detail]
            ws_c1_1["A1"] = "=A!B2"
            ws_c1_1["A2"] = "='Notes & Queries'!A2"
            ws_c1_1["B6"] = "Tangible fixed assets by class"
            for r in range(11, 38):
                for c in range(1, 18):
                    ws_c1_1.cell(row=r, column=c).value = None
            ws_c1_1["P8"] = "Check"
            ws_c1_1["P9"] = "NBV per ETB"
            ws_c1_1["Q9"] = "Difference"
            # Each class's rate and method as the depreciation works it (client setup, else last year's, else the
            # firm default: setup_checks.class_rates), so SLM / RBM is on the tab as in the accounting policy
            from backend.app.services.review.setup_checks import ASSET_CLASS_CODES as _CLASSES, class_rates
            try:
                rates_by_class = class_rates(engagement, getattr(engagement, "profile", None), db)[0]
            except Exception:
                rates_by_class = {}
            rate_of = {codes["cost"][0]: rates_by_class.get(cls) for cls, codes in _CLASSES.items()}
            short = {"STRAIGHT_LINE": "SLM", "REDUCING_BALANCE": "RBM", "NONE": "Not depreciated"}
            for r, (base, cls_name, v, f) in enumerate(classes, 11):
                ws_c1_1.cell(row=r, column=1, value=f"{base}-{base + 9}")
                ws_c1_1.cell(row=r, column=2, value=cls_name)
                policy = rate_of.get(base) or {}
                if policy.get("method"):
                    if policy.get("rate") and policy["method"] != "NONE":
                        ws_c1_1.cell(row=r, column=9, value=float(policy["rate"]) / 100).number_format = "0%"
                    ws_c1_1.cell(row=r, column=10, value=short.get(policy["method"], policy["method"]))
                for col, key in ((4, "D"), (5, "E"), (6, "F"), (8, "H"), (11, "K"), (12, "L")):
                    ws_c1_1.cell(row=r, column=col, value=f"=ROUND({''.join(f[key])},2)" if f[key] else 0)
                ws_c1_1.cell(row=r, column=7, value=f"=D{r}+E{r}-F{r}")
                ws_c1_1.cell(row=r, column=13, value=f"=H{r}+K{r}-L{r}")
                ws_c1_1.cell(row=r, column=14, value=f"=G{r}-M{r}")
                ws_c1_1.cell(row=r, column=15, value=f"=D{r}-H{r}")
                ws_c1_1.cell(row=r, column=16, value=f"=SUMIFS('B1-ETB'!$N:$N,'B1-ETB'!$A:$A,\">={base}\",'B1-ETB'!$A:$A,\"<={base + 9}\")")
                ws_c1_1.cell(row=r, column=17, value=f"=ROUND(N{r}-P{r},2)")
            ws_c1_1.cell(row=38, column=2, value="Total")
            for col in (4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 16, 17):
                letter = get_column_letter(col)
                ws_c1_1.cell(row=38, column=col, value=f"=SUM({letter}11:{letter}37)")
            _asset_lines(ws_c1_1, db, engagement, bold_font)
            # C1-1 is the asset codes' schedule: B1-ETB's Schedule column and the journals tab (B2) link them here
            from backend.app.services.workbook.balance_tabs.leads import note_schedule
            note_schedule(ws_c1_1, fa_codes)
            # C1-2: the depreciation rates for the accountant to confirm
            add_rates_tab(wb, engagement, db, tb_records, bold_font, after=detail)

        lead = "C1 (LEAD)"
        if lead in wb.sheetnames:
            ws_c1 = wb[lead]
            lead_rows = {12: "D", 14: "E", 16: "-F", 26: "H", 28: "K", 30: "-L"}
            sum_rows = {19: "SUM({c}11:{c}18)", 33: "SUM({c}25:{c}30)", 35: "{c}19-{c}33", 37: "+{c}12-{c}26"}
            styles = {r: copy(ws_c1.cell(row=r, column=4)._style) for r in range(7, 38)}
            width = ws_c1.column_dimensions["D"].width
            total_col = 4 + len(classes)
            for c in range(4, total_col + 2):
                for r in range(7, 38):
                    ws_c1.cell(row=r, column=c).value = None
            for i, (_, cls_name, _, _) in enumerate(classes):
                col, detail_row = 4 + i, 11 + i
                letter = get_column_letter(col)
                ws_c1.column_dimensions[letter].width = width
                ws_c1.cell(row=7, column=col, value=cls_name)
                for r, src in lead_rows.items():
                    sign = "-" if src.startswith("-") else "+"
                    ws_c1.cell(row=r, column=col, value=f"={sign}'{detail}'!{src.lstrip('-')}{detail_row}")
                for r, f in sum_rows.items():
                    ws_c1.cell(row=r, column=col, value="=" + f.format(c=letter))
            total_letter = get_column_letter(total_col)
            last_letter = get_column_letter(total_col - 1)
            ws_c1.column_dimensions[total_letter].width = width
            ws_c1.cell(row=7, column=total_col, value="TOTAL")
            ws_c1.cell(row=8, column=total_col, value="Tangible")
            for r in list(lead_rows) + list(sum_rows):
                ws_c1.cell(row=r, column=total_col, value=f"=SUM(D{r}:{last_letter}{r})")
            for c in range(4, total_col + 1):
                for r, st in styles.items():
                    if c > 4:
                        ws_c1.cell(row=r, column=c)._style = copy(st)
                ws_c1.cell(row=7, column=c).alignment = Alignment(wrap_text=True, horizontal="center")
            if ws_c1["E1"].value == "C1" and total_col != 5:
                ws_c1["E1"] = None
                ws_c1.cell(row=1, column=total_col, value="C1")

    # Revenue vs Capital SOP (C1.2): P&L expenses at or above the capitalisation limit with asset words.
    # Shown even when the client has no fixed assets: an asset expensed by mistake is exactly the case to catch.
    if db is not None:
        limit = capitalisation_limit(engagement)
        cap_flags = capital_review(str(engagement.id), tb_records, db, limit)
        after = next((n for n in ("C1-1-FA detail", "C1 (LEAD)", "C") if n in wb.sheetnames), None)
        ws = wb.create_sheet("C1.2 - Capital review",
                             wb.sheetnames.index(after) + 1 if after else
                             (wb.sheetnames.index("D") if "D" in wb.sheetnames else len(wb.sheetnames)))
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        ws["A4"] = "Capital vs revenue review"
        ws["A4"].font = Font(name="Calibri", size=12, bold=True)
        ws["A5"] = (f"P&L expenses of £{limit:,.0f} or more whose description or supplier contains asset-related words. "
                    f"Review only: nothing is posted. Supplier-name matches are an indicator, not proof.")
        heads = ["Date", "Account", "Code", "Description", "Amount", "Matched words", "Match type",
                 "Suggested asset class", "Question for the client"]
        for c, text in enumerate(heads, 1):
            ws.cell(row=7, column=c, value=text).font = bold_font
        for r, f in enumerate(cap_flags, 8):
            suggested = f"{f.suggested_code} {chart_names.get(f.suggested_code, '')}".strip() if f.suggested_code else ""
            values = [f.when, f.account, f.code, f.description[:250], f.amount, ", ".join(f.keywords),
                      "Supplier name only" if f.supplier_only else "Keywords", suggested, CAPITAL_QUESTION]
            for c, v in enumerate(values, 1):
                cell = ws.cell(row=r, column=c, value=v)
                if c == 1:
                    cell.number_format = "dd/mm/yyyy"
                elif c == 5:
                    cell.number_format = "#,##0.00"
        if cap_flags:
            total_row = 8 + len(cap_flags) + 1
            ws.cell(row=total_row, column=4, value="Total").font = bold_font
            cell = ws.cell(row=total_row, column=5, value=f"=SUM(E8:E{total_row - 2})")
            cell.font = bold_font
            cell.number_format = "#,##0.00"
            strong = sum(1 for f in cap_flags if not f.supplier_only)
            if strong:
                report_notes.append(f"{strong} expense(s) may be fixed assets: capital review (C1.2)")
        else:
            ws["A8"] = f"No P&L expense of £{limit:,.0f} or more looks like a fixed asset."
        ws.column_dimensions["B"].width = 30
        ws.column_dimensions["D"].width = 50

    # Rental Property SOP (C1.3): one block per property on the client setup
    if db is not None:
        summaries = property_review(str(engagement.id), engagement.period_end_date, tb_records, db,
                                    getattr(engagement, "profile", None), capitalisation_limit(engagement))
        if summaries or confirmed_industry(getattr(engagement, "profile", None)) == "PRP":
            after = next((n for n in ("C1.2 - Capital review", "C1-1-FA detail", "C1 (LEAD)", "C") if n in wb.sheetnames), None)
            ws = wb.create_sheet("C1.3 - Property review",
                                 wb.sheetnames.index(after) + 1 if after else len(wb.sheetnames))
            ws["A1"] = "=A!B2"
            ws["A2"] = "='Notes & Queries'!A2"
            ws["A4"] = "Property review"
            ws["A4"].font = Font(name="Calibri", size=12, bold=True)
            ws["A5"] = ("Each property is classified on the client setup: held to earn rent (fixed asset) or to sell "
                        "(stock). Property costs are checked against that. Review only: nothing is posted.")
            row = 7
            if not summaries:
                ws.cell(row=row, column=1, value="No properties entered on the client setup screen yet.")
            for s in summaries:
                ws.cell(row=row, column=1, value=f"{s.entry.name} - {s.entry.model.title()}").font = bold_font
                ws.cell(row=row + 1, column=1, value="Rent start")
                ws.cell(row=row + 1, column=2, value=s.rent_start).number_format = "dd/mm/yyyy"
                ws.cell(row=row + 1, column=3, value=s.rent_start_source)
                ws.cell(row=row + 2, column=1, value="Rent received this year")
                ws.cell(row=row + 2, column=2, value=s.rent_income).number_format = "#,##0.00"
                ws.cell(row=row + 3, column=1, value="Ledger lines for this property")
                ws.cell(row=row + 3, column=2, value=s.lines)
                row += 5
                for c, text in enumerate(["Rule", "Date", "Account", "Description", "Amount", "Reason for flag",
                                          "Question for the client"], 1):
                    ws.cell(row=row, column=c, value=text).font = bold_font
                row += 1
                for f in s.flags:
                    for c, v in enumerate([f.rule, f.when, f.account, f.description[:250], f.amount, f.reason, f.question], 1):
                        cell = ws.cell(row=row, column=c, value=v)
                        if c == 2 and v is not None:
                            cell.number_format = "dd/mm/yyyy"
                        elif c == 5:
                            cell.number_format = "#,##0.00"
                    row += 1
                if not s.flags:
                    ws.cell(row=row, column=1, value="No property recognition issues found.")
                    row += 1
                row += 2
            flagged = sum(len(s.flags) for s in summaries)
            if flagged:
                report_notes.append(f"{flagged} property item(s) to review: property review (C1.3)")
            ws.column_dimensions["A"].width = 30
            ws.column_dimensions["C"].width = 30
            ws.column_dimensions["D"].width = 50
            ws.column_dimensions["F"].width = 60
            ws.column_dimensions["G"].width = 50


ASSET_TOP = 42              # the register's lines under the class lines (rows 11 to 38, read by the C1 lead)


def _rate_parts(text: str) -> Tuple[float, str]:
    """'20% RBM' -> (0.2, 'RBM'); '25% SL' -> (0.25, 'SLM'); nothing -> (0.0, '')."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text or "")
    method = "SLM" if re.search(r"\bs\.?l|straight", text or "", re.I) else ("RBM" if re.search(r"\br\.?b|reducing", text or "", re.I) else "")
    return (float(m.group(1)) / 100 if m else 0.0), method


def _asset_lines(ws, db, engagement, bold_font) -> None:
    """The register asset by asset (C1-1-FA detail): particulars,
    date of purchase, cost b/fwd, additions, disposals, cost c/fwd, depreciation b/fwd, rate, method, the charge per
    asset as a formula (RBM: cost less depreciation b/fwd times the rate; SLM: cost times the rate, never more than the
    net book value), depreciation c/fwd and the NBVs, a subtotal per class. The register is the client's uploaded one
    or last year's final WP rolled forward (ingestion/supplementary_parser.py)."""
    if db is None:
        return
    from backend.app.models.database import FixedAssetRecord
    assets = db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement.id).all()
    r = ASSET_TOP
    ws.cell(row=r, column=2, value="Asset register (one row per asset)").font = bold_font
    if not assets:
        ws.cell(row=r + 1, column=2, value=("No asset register uploaded: upload last year's final working paper (its "
                                            "C1-1-FA detail tab) or the client's register, one row per asset."))
        # What last year's TB brings forward with no register behind it shows as unanalysed
        _unanalysed(ws, r + 2, "Unanalysed - query: cost and depreciation b/fwd with no asset register (must be nil)",
                    "=ROUND(D38,2)", "=ROUND(H38,2)")
        return
    heads = {2: "Particulars", 3: "Date of purchase", 4: "Cost b/fwd", 5: "Additions", 6: "Disposals", 7: "Cost c/fwd",
             8: "Depn b/fwd", 9: "Rate", 10: "SLM/RBM", 11: "Charge for the year", 12: "Depn on disposal",
             13: "Depn c/fwd", 14: "NBV this year", 15: "NBV last year"}
    r += 1
    for col, text in heads.items():
        ws.cell(row=r, column=col, value=text).font = bold_font
    money = "#,##0.00;(#,##0.00);\"-\""
    by_class: Dict[str, List] = {}
    for a in assets:
        by_class.setdefault(a.category or "Fixed assets", []).append(a)
    subtotals = []
    for cls, items in by_class.items():
        r += 2
        ws.cell(row=r, column=2, value=cls).font = bold_font
        first = r + 1
        for a in sorted(items, key=lambda a: (a.acquisition_date is None, a.acquisition_date or 0)):
            r += 1
            rate, method = _rate_parts(a.depr_rate_method)
            ws.cell(row=r, column=2, value=a.description)
            if a.acquisition_date:
                ws.cell(row=r, column=3, value=a.acquisition_date).number_format = "dd/mm/yyyy"
            for col, v in ((4, a.cost_bwd), (5, a.additions), (6, a.disposals), (8, a.depr_bwd), (12, a.depr_disposals)):
                ws.cell(row=r, column=col, value=round(float(v or 0), 2)).number_format = money
            ws.cell(row=r, column=7, value=f"=D{r}+E{r}-F{r}").number_format = money
            ws.cell(row=r, column=9, value=rate or None).number_format = "0%"
            ws.cell(row=r, column=10, value=method or None)
            # Nothing on an asset sold in the year; never below nil; not rounded per asset (the class total is)
            charge = (f"=IF(F{r}>0,0,IF(J{r}=\"SLM\",MIN(G{r}*I{r},G{r}-H{r}),(G{r}-H{r})*I{r}))"
                      if rate else round(float(a.depr_charge or 0), 2))
            ws.cell(row=r, column=11, value=charge).number_format = money
            ws.cell(row=r, column=13, value=f"=H{r}+K{r}-L{r}").number_format = money
            ws.cell(row=r, column=14, value=f"=G{r}-M{r}").number_format = money
            ws.cell(row=r, column=15, value=f"=D{r}-H{r}").number_format = money
        r += 1
        ws.cell(row=r, column=2, value=f"Total {cls}").font = bold_font
        for col in (4, 5, 6, 7, 8, 11, 12, 13, 14, 15):
            letter = get_column_letter(col)
            cell = ws.cell(row=r, column=col, value=f"=SUM({letter}{first}:{letter}{r - 1})")
            cell.number_format, cell.font = money, bold_font
        subtotals.append(r)
    r += 2
    ws.cell(row=r, column=2, value="Total per register").font = bold_font
    for col in (4, 5, 6, 7, 8, 11, 12, 13, 14, 15):
        letter = get_column_letter(col)
        cell = ws.cell(row=r, column=col, value="=" + "+".join(f"{letter}{s}" for s in subtotals))
        cell.number_format, cell.font = money, bold_font
    ws.cell(row=r + 1, column=2, value="Check: register cost c/fwd less the class lines above (must be nil)")
    ws.cell(row=r + 1, column=7, value=f"=ROUND(G{r}-G38,2)").number_format = money
    # The class lines' b/fwd (last year's TB) not in the register, cost and depreciation
    _unanalysed(ws, r + 2, "Unanalysed - query: last year's TB b/fwd not in the register (must be nil)",
                f"=ROUND(D38-D{r},2)", f"=ROUND(H38-H{r},2)")


def _unanalysed(ws, row: int, label: str, cost: str, depreciation: str) -> None:
    """The 'Unanalysed - query' line in red: cost b/fwd in D, depreciation b/fwd in H."""
    red = Font(bold=True, color="FFC00000")
    ws.cell(row=row, column=2, value=label).font = red
    for col, formula in ((4, cost), (8, depreciation)):
        cell = ws.cell(row=row, column=col, value=formula)
        cell.number_format, cell.font = "#,##0.00;(#,##0.00);\"-\"", red
