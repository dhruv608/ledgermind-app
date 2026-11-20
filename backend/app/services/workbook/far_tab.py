"""C1.1 - Fixed asset register: the detail behind the fixed asset figures, such as the additions.

A. The register asset by asset, grouped by asset class, with each class's totals as formulas and the register against
   the books (B1-ETB) per class, so a difference is on the face of the working paper.
B. Additions this year: every addition in the register and every purchase on the books' additions accounts, matched by
   amount, with where each one came from (register and ledger, register only, ledger only).
C. Disposals in the register: cost, depreciation and net book value of each asset disposed of.
Without a register, B still lists the ledger's additions so the detail behind C1's additions is always there."""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from openpyxl.styles import Font, PatternFill
from sqlalchemy import select

from backend.app.models.database import FixedAssetRecord
from backend.app.services.review.setup_checks import ASSET_CLASS_CODES
from backend.app.services.review.yearend_journals import _far_class
from backend.app.services.tax.ct_computation import final_balances
from backend.app.services.workbook.context import BuildContext

SHEET = "C1.1 - Fixed asset register"
MONEY = '#,##0.00;(#,##0.00);"-"'
HEAD_FILL = PatternFill("solid", fgColor="E2F0EE")
WARN_FILL = PatternFill("solid", fgColor="FFF7E0")
MATCH_TOLERANCE = 1.0


def _etb_sum(codes) -> str:
    """The final balance (B1-ETB column N) of these codes."""
    return "+".join(f"SUMIF('B1-ETB'!$A:$A,{c},'B1-ETB'!$N:$N)" for c in codes) or "0"


def _when(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def _charge_formula(a, r: int, year_end: date, months_rule: str) -> Optional[str]:
    """The year's charge for a register line that gives none, as the depreciation journal works it
    (yearend_journals.far_depreciation): nothing on an asset sold in the year; straight line on cost, reducing balance
    on the value brought forward; this year's additions for the months held; never below nil. A live formula on the
    row's own columns (C cost b/f, D additions, G depreciation b/f)."""
    from backend.app.services.review.yearend_journals import _months_held, _rate
    if abs(float(a.depr_charge or 0)) >= 0.005 or float(a.disposals or 0) > 0:
        return None
    rate, method = _rate(a.depr_rate_method)
    if not rate:
        return None
    months = _months_held(a.acquisition_date, year_end, months_rule) if float(a.additions or 0) else 12
    value = f"MAX(0,C{r}-G{r})"
    base = f"C{r}" if method == "STRAIGHT_LINE" else value
    return f"=ROUND(MIN({base}*{rate / 100:g}+D{r}*{rate / 100:g}*{months}/12,{value}+D{r}),2)"


def add_far_tab(ctx: BuildContext) -> None:
    wb, db, eng = ctx.wb, ctx.db, ctx.engagement
    if db is None:
        return
    register = list(db.execute(select(FixedAssetRecord).where(FixedAssetRecord.engagement_id == eng.id)).scalars())
    # The books' additions accounts and the class of each
    addition_codes = {codes["cost"][1]: cls for cls, codes in ASSET_CLASS_CODES.items()}
    start = eng.prior_period_end_date
    ledger_adds, ledger_credits = [], []
    for tx in ctx.tx_rows:
        # (date 'dd/mm/yyyy', code, type, account, source, description, ref, debit, credit)
        if not str(tx[1]).isdigit() or int(tx[1]) not in addition_codes:
            continue
        when = _when(tx[0])
        if start and when and when <= start:
            continue                      # last year's line (an opening balance)
        amount = round(float(tx[7] or 0) - float(tx[8] or 0), 2)
        if amount <= -0.005:
            ledger_credits.append(amount)          # a transfer or reversal out of additions, not a purchase
        elif amount >= 0.005:
            ledger_adds.append({"when": when, "class": addition_codes[int(tx[1])], "description": tx[5] or tx[3],
                                "ref": tx[6] or "", "amount": amount, "code": int(tx[1])})
    if not register and not ledger_adds:
        return

    after = next((n for n in ("C1-1-FA detail", "C1 (LEAD)", "C") if n in wb.sheetnames), None)
    if SHEET in wb.sheetnames:
        del wb[SHEET]
    ws = wb.create_sheet(SHEET, wb.sheetnames.index(after) + 1 if after else None)
    bold = Font(bold=True)
    ws["A1"], ws["A2"] = "=A!B2", "='Notes & Queries'!A2"
    ws["A4"] = "Fixed asset register: each asset, this year's additions and disposals, and the register against the books"
    ws["A4"].font = Font(bold=True, size=12)
    for col, w in zip("ABCDEFGHIJKLM", (12, 40, 14, 13, 13, 14, 14, 13, 13, 14, 14, 12, 34)):
        ws.column_dimensions[col].width = w
    r = 6

    # A. The register, class by class. A heading that fits several classes ('Equipment, fixtures & fittings') goes to
    # the class where the books hold the cost, as the depreciation does
    after_bal = final_balances(str(eng.id), ctx.tb_records, db)
    from backend.app.services.review.setup_checks import firm_depreciation_settings, setup_of
    policies = setup_of(getattr(eng, "profile", None)).get("policies") or {}
    months_rule = policies.get("additions_from") or firm_depreciation_settings(db)["additions_from"]
    held = {cls: sum(abs(after_bal.get(c, 0.0)) for c in codes["cost"]) for cls, codes in ASSET_CLASS_CODES.items()}
    classes: Dict[str, List[FixedAssetRecord]] = {}
    for a in register:
        cls = _far_class(a.category, held) or f"Not matched: {a.category or 'Fixed assets'}"
        classes.setdefault(cls, []).append(a)
    class_totals: Dict[str, int] = {}
    if register:
        ws.cell(row=r, column=1, value="A. The fixed asset register").font = Font(bold=True, size=11)
        r += 1
        heads = ["Date", "Asset", "Cost b/f", "Additions", "Disposals", "Cost c/f", "Depreciation b/f", "Charge",
                 "Eliminated", "Depreciation c/f", "NBV", "Rate"]
        for cls in sorted(classes):
            ws.cell(row=r, column=1, value=cls).font = bold
            for col in range(1, 13):
                ws.cell(row=r, column=col).fill = HEAD_FILL
            r += 1
            for j, h in enumerate(heads, 1):
                ws.cell(row=r, column=j, value=h).font = bold
            r += 1
            first = r
            for a in sorted(classes[cls], key=lambda a: (a.acquisition_date or date.min, a.description or "")):
                ws.cell(row=r, column=1, value=a.acquisition_date).number_format = "dd/mm/yyyy"
                ws.cell(row=r, column=2, value=(a.description or "")[:120])
                dep_fwd = float(a.depr_fwd or 0)
                dep_bf = (dep_fwd - float(a.depr_charge or 0) + float(a.depr_disposals or 0)) if dep_fwd else float(a.depr_bwd or 0)
                for col, v in ((3, a.cost_bwd), (4, a.additions), (5, a.disposals), (7, dep_bf), (8, a.depr_charge),
                               (9, a.depr_disposals)):
                    ws.cell(row=r, column=col, value=round(float(v or 0), 2)).number_format = MONEY
                charge = _charge_formula(a, r, eng.period_end_date, months_rule)
                if charge:
                    # No charge in the register (last year's rolled forward): the asset's own rate, as the
                    # depreciation journal works it, so the total ties to the B2 journal
                    ws.cell(row=r, column=8, value=charge).number_format = MONEY
                ws.cell(row=r, column=6, value=f"=C{r}+D{r}-E{r}").number_format = MONEY
                ws.cell(row=r, column=10, value=f"=G{r}+H{r}-I{r}").number_format = MONEY
                ws.cell(row=r, column=11, value=f"=F{r}-J{r}").number_format = MONEY
                ws.cell(row=r, column=12, value=a.depr_rate_method or None)
                r += 1
            ws.cell(row=r, column=2, value=f"Total {cls.lower()}").font = bold
            for col in range(3, 12):
                letter = "CDEFGHIJK"[col - 3]
                c = ws.cell(row=r, column=col, value=f"=SUM({letter}{first}:{letter}{r - 1})")
                c.number_format, c.font = MONEY, bold
            class_totals[cls] = r
            r += 1
            codes = ASSET_CLASS_CODES.get(cls)
            if codes:
                # The register against the books (B1-ETB final balances) for this class
                ws.cell(row=r, column=2, value="Per the books (B1-ETB)")
                ws.cell(row=r, column=6, value=f"=ROUND({_etb_sum(codes['cost'])},2)").number_format = MONEY
                ws.cell(row=r, column=10, value=f"=ROUND(-({_etb_sum(codes['acc'])}),2)").number_format = MONEY
                ws.cell(row=r, column=11, value=f"=F{r}-J{r}").number_format = MONEY
                r += 1
                ws.cell(row=r, column=2, value="Difference: register less books (should be 0)").font = bold
                for col in (6, 10, 11):
                    letter = "FJK"[(6, 10, 11).index(col)]
                    c = ws.cell(row=r, column=col, value=f"=ROUND({letter}{r - 2}-{letter}{r - 1},2)")
                    c.number_format, c.fill = MONEY, WARN_FILL
                r += 1
            r += 1
        ws.cell(row=r, column=2, value="Total per the register").font = bold
        for col in range(3, 12):
            letter = "CDEFGHIJK"[col - 3]
            c = ws.cell(row=r, column=col, value="=" + "+".join(f"{letter}{row}" for row in class_totals.values()))
            c.number_format, c.font = MONEY, bold
        r += 3

    # B. Additions this year: the register's and the ledger's, matched by amount
    ws.cell(row=r, column=1, value="B. Additions this year").font = Font(bold=True, size=11)
    r += 1
    for j, h in enumerate(["Date", "Description", "Supplier / ref", "Amount", "Class", "Source", "", "", "", "", "", "",
                           "Check"], 1):
        if h:
            ws.cell(row=r, column=j, value=h).font = bold
    r += 1
    reg_adds = [{"when": a.acquisition_date, "description": a.description or "", "amount": round(float(a.additions or 0), 2),
                 "class": _far_class(a.category, held) or (a.category or "")} for a in register if float(a.additions or 0) >= 0.005]
    unmatched_ledger = list(ledger_adds)
    rows: List[Tuple] = []
    for a in reg_adds:
        hit = next((l for l in unmatched_ledger if abs(l["amount"] - a["amount"]) <= MATCH_TOLERANCE), None)
        if hit:
            unmatched_ledger.remove(hit)
            rows.append((a["when"] or hit["when"], a["description"], f"{hit['description']} {hit['ref']}".strip(),
                         a["amount"], a["class"], "Register and ledger", ""))
        else:
            rows.append((a["when"], a["description"], "", a["amount"], a["class"], "Register only",
                         "In the register, not on the books' additions accounts: find where it was posted"))
    for l in unmatched_ledger:
        rows.append((l["when"], l["description"], l["ref"], l["amount"], l["class"], "Ledger only",
                     "On the books' additions accounts, not in the register: add it to the register"))
    first = r
    for row in sorted(rows, key=lambda x: (x[0] or date.min)):
        ws.cell(row=r, column=1, value=row[0]).number_format = "dd/mm/yyyy"
        ws.cell(row=r, column=2, value=(row[1] or "")[:120])
        ws.cell(row=r, column=3, value=(row[2] or "")[:80])
        ws.cell(row=r, column=4, value=row[3]).number_format = MONEY
        ws.cell(row=r, column=5, value=row[4])
        ws.cell(row=r, column=6, value=row[5])
        if row[6]:
            ws.cell(row=r, column=13, value=row[6]).fill = WARN_FILL
        r += 1
    if not rows:
        ws.cell(row=r, column=2, value="No additions this year")
        r += 1
    ws.cell(row=r, column=2, value="Total additions listed").font = bold
    c = ws.cell(row=r, column=4, value=f"=SUM(D{first}:D{r - 1})" if rows else 0)
    c.number_format, c.font = MONEY, bold
    r += 1
    ws.cell(row=r, column=2, value="Additions per the books (B1-ETB)")
    ws.cell(row=r, column=4, value=f"=ROUND({_etb_sum(sorted(addition_codes))},2)").number_format = MONEY
    if ledger_credits:
        r += 1
        ws.cell(row=r, column=2, value=f"Credits on the additions accounts this year ({len(ledger_credits)}: transfers to "
                                       f"cost or reversals, not purchases)")
        ws.cell(row=r, column=4, value=round(sum(ledger_credits), 2)).number_format = MONEY
    r += 3

    # C. Disposals in the register
    disposed = [a for a in register if float(a.disposals or 0) >= 0.005 or float(a.depr_disposals or 0) >= 0.005]
    ws.cell(row=r, column=1, value="C. Disposals this year").font = Font(bold=True, size=11)
    r += 1
    for j, h in enumerate(["Date bought", "Asset", "Class", "Cost", "Depreciation", "NBV at disposal"], 1):
        ws.cell(row=r, column=j, value=h).font = bold
    r += 1
    for a in disposed:
        ws.cell(row=r, column=1, value=a.acquisition_date).number_format = "dd/mm/yyyy"
        ws.cell(row=r, column=2, value=(a.description or "")[:120])
        ws.cell(row=r, column=3, value=_far_class(a.category, held) or a.category)
        ws.cell(row=r, column=4, value=round(float(a.disposals or 0), 2)).number_format = MONEY
        ws.cell(row=r, column=5, value=round(float(a.depr_disposals or 0), 2)).number_format = MONEY
        ws.cell(row=r, column=6, value=f"=D{r}-E{r}").number_format = MONEY
        r += 1
    if not disposed:
        ws.cell(row=r, column=2, value="No disposals in the register" if register else "No register uploaded")
    ws.freeze_panes = "A6"
