"""The pre-release QA gate, and formulas pointing at sheets removed from the template."""

import logging
import re
from typing import Dict, List

import openpyxl

from backend.app.models.database import TBRecord

logger = logging.getLogger(__name__)


def sheet_reference_pattern(sheet_name: str) -> re.Pattern:
    """Matches a reference into a sheet: 'G6 - Net Wages'!N35, TTB!F57, 'X'!E:E, X!A1:B9."""
    name = re.escape(sheet_name)
    cell = r"\$?[A-Z]{1,3}\$?\d*"
    return re.compile(rf"(?:'{name}'|(?<![\w']){name})!{cell}(?::{cell})?")

def zero_references_to_removed_sheets(wb: openpyxl.Workbook, removed_sheets: List[str]) -> int:
    """Replace references to deleted sheets with 0 so the remaining formulas still calculate."""
    if not removed_sheets:
        return 0
    patterns = [sheet_reference_pattern(name) for name in removed_sheets]
    fixed = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, str) and v.startswith("=") and "!" in v:
                    new_v = v
                    for pat in patterns:
                        new_v = pat.sub("0", new_v)
                    if new_v != v:
                        cell.value = new_v
                        fixed += 1
    return fixed

def run_pre_release_qa_check(wb: openpyxl.Workbook, tb_records: List[TBRecord]) -> List[str]:
    """
    Pre-release QA gate. Returns the list of problems found (empty list = pass):
    1. TTB has a TOTAL row and the trial balance balances.
    3. No formulas point at missing sheets or other workbooks (would show #REF!).
    (The Re-analysis tab is not checked for being empty: it lists the journals that move lines. The template is kept
    free of other clients' data by backend/scripts/clean_template_client_data.py, so nothing is blanked here.)
    """
    issues: List[str] = []
    # Check 1: TTB Totals
    if "TTB" in wb.sheetnames:
        ws_ttb = wb["TTB"]
        found_total = False
        for r in range(7, ws_ttb.max_row + 1):
            val = str(ws_ttb.cell(r, 2).value or "").strip()
            if "TOTAL" in val:
                found_total = True
                break
        if not found_total and len(tb_records) > 0:
            issues.append("TTB TOTAL row not found")
    tb_difference = round(sum(float(t.net_amount or 0.0) for t in tb_records), 2)
    if abs(tb_difference) >= 0.01:
        issues.append(f"Trial balance does not balance (difference {tb_difference:,.2f})")

    # Check 3: formulas pointing at sheets that do not exist, other workbooks, or #REF!
    # A quoted name doubles any apostrophe in it ('Directors'' salaries'!A1, Excel's own quoting)
    sheet_ref = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_][\w.\- ]*?))!\$?[A-Z]{1,3}")
    existing = set(wb.sheetnames)
    broken: Dict[str, int] = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                problem = None
                if "#REF!" in v:
                    problem = "#REF!"
                elif re.search(r"\[\d+\]", v):
                    problem = "link to another workbook"
                else:
                    for quoted, bare in sheet_ref.findall(v):
                        target = quoted.replace("''", "'") if quoted else bare
                        if target and target not in existing:
                            problem = f"missing sheet '{target}'"
                            break
                if problem:
                    broken[f"{ws.title}: {problem}"] = broken.get(f"{ws.title}: {problem}", 0) + 1
    for where, count in broken.items():
        issues.append(f"{count} broken formula(s) in {where}")

    for issue in issues:
        logger.warning("Workbook QA: %s", issue)
    return issues
