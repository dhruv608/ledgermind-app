"""C1-2 Depreciation rates: each asset class the client holds, with the method, rate and where the rate comes from,
the year-of-purchase and year-of-sale rules, last year's rate and whether it changed, for the accountant to confirm
before the depreciation journal is approved.

The rate is the one the review uses (review/setup_checks.class_rates: the client setup, else last year's rate, else
the firm default); a class whose assets are in the register is charged asset by asset at the register's rates (C1-1)."""

from typing import Any, Dict, Optional

from openpyxl.styles import Font, PatternFill

from backend.app.services.review.setup_checks import (ASSET_CLASS_CODES, class_rates, firm_depreciation_settings,
                                                     setup_of)
from backend.app.services.review.yearend_journals import _far_class, _rate

TAB = "C1-2 - Depreciation rates"
METHOD = {"STRAIGHT_LINE": "Straight line", "REDUCING_BALANCE": "Reducing balance", "NONE": "Not depreciated"}
PURCHASE_RULE = {"FULL_YEAR": "Full year", "FROM_MONTH": "By month, from the month bought",
                 "NEXT_MONTH": "By month, from the month after"}
AMBER = PatternFill("solid", fgColor="FFFFE699")


def _said(r: Optional[Dict[str, Any]]) -> str:
    if not r:
        return ""
    if r.get("method") == "NONE":
        return "Not depreciated"
    return f"{float(r.get('rate') or 0):g}% {METHOD.get(r.get('method'), r.get('method') or '').lower()}".strip()


def add_rates_tab(wb, engagement, db, tb_records, bold_font, after: str) -> None:
    """The C1-2 tab after C1-1; nothing when the client holds no asset class."""
    held = {cls: sum(abs(float(t.net_amount or 0)) + abs(float(t.opening_amount or 0)) for t in tb_records
                     if t.std_code in codes["cost"]) for cls, codes in ASSET_CLASS_CODES.items()}
    classes = [cls for cls, amount in held.items() if amount >= 0.01]
    if not classes or after not in wb.sheetnames:
        return
    profile = getattr(engagement, "profile", None)
    rates, source, previous = class_rates(engagement, profile, db)
    policies = setup_of(profile).get("policies") or {}
    rule = policies.get("additions_from") or firm_depreciation_settings(db)["additions_from"]
    # The register's rate per class (last year's working paper or the client's register), asset by asset on C1-1
    register: Dict[str, Dict[str, Any]] = {}
    if db is not None:
        from backend.app.models.database import FixedAssetRecord
        for a in db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement.id).all():
            cls = _far_class(a.category, held)
            rate, method = _rate(a.depr_rate_method)
            if cls in held and rate and cls not in register:
                register[cls] = {"rate": rate, "method": method}

    ws = wb.create_sheet(TAB, wb.sheetnames.index(after) + 1)
    ws["A1"], ws["A2"], ws["H1"] = "=A!B2", "='Notes & Queries'!A2", "C1-2"
    ws["A4"] = "Depreciation rates"
    ws["A4"].font = bold_font
    ws["A5"] = ("The rates used for this year's charge: confirm them before the depreciation journal is approved. "
                "A rate or method different from last year's is a change of estimate (FRS 102 s10.15-10.18) and needs "
                "a note.")
    heads = ["Group", "Method", "Rate", "Source", "Year of purchase", "Year of sale", "Last year", "Change"]
    for c, text in enumerate(heads, 1):
        ws.cell(row=7, column=c, value=text).font = bold_font
    for r, cls in enumerate(classes, 8):
        if cls in register:
            used, said_source = register[cls], "Asset register (asset by asset on C1-1)"
        else:
            used = rates.get(cls)
            said_source = (source[cls][0].upper() + source[cls][1:]) if cls in source else \
                "None: set a rate on the client setup (Policies)"
        before = previous.get(cls)
        changed = bool(used and before and (used.get("method") != before.get("method") or
                                            abs(float(used.get("rate") or 0) - float(before.get("rate") or 0)) >= 0.01))
        values = [cls, METHOD.get((used or {}).get("method"), ""),
                  (float(used["rate"]) / 100 if used and used.get("rate") and used.get("method") != "NONE" else None),
                  said_source, PURCHASE_RULE.get(rule, rule), "No charge", _said(before) or "Not known",
                  "Changed: needs a note" if changed else ""]
        for c, v in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=v)
            if c == 3:
                cell.number_format = "0%"
        if changed:
            for c in range(1, len(heads) + 1):
                ws.cell(row=r, column=c).fill = AMBER
            ws.cell(row=r, column=8).font = Font(bold=True, color="FF9C5700")
    for letter, width in zip("ABCDEFGH", (24, 18, 8, 40, 30, 12, 24, 22)):
        ws.column_dimensions[letter].width = width
