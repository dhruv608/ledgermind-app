"""Leads from the ETB codes, never from fixed template rows alone (which would leave out balances such as other
debtors, a credit card or leases). On the debtors and creditors leads, every
B1-ETB code that no lead row holds (other debtors, accrued income, a credit card, other creditors, pension payable with
no pension schedule, the director's loan after one year) gets its own row from the ETB, inside the lead's total; then
every code of the lead is listed with a red check that the lead's total is all of them (a schedule that does not agree
to the ETB shows there)."""

import re
from typing import Dict, List, Set, Tuple

from openpyxl.styles import Font

from backend.app.services.workbook.balance_tabs.common import _money

ETB = "B1-ETB"
LOANS = "G4 - Loans & HP"
BOLD = Font(name="Calibri", size=11, bold=True)

# The lead, the code ranges it holds (the firm chart's sections) and its sign (+1: debits shown positive)
LEADS: List[Tuple[str, List[Tuple[int, int]], int]] = [
    ("D1 (LEAD)", [(4300, 4310)], 1),                                        # stock and work in progress
    ("E1 (LEAD)", [(4400, 4480), (4500, 4574), (4900, 4952)], 1),           # debtors < and > 1 year, prepayments
    ("G1 (LEAD)", [(5000, 5017), (5100, 5416), (5500, 5816)], -1),          # HP and leases, creditors < and > 1 year
]
# The codes each template row of a lead holds (its schedule's own control code), by the row's label
ROW_CODES: Dict[str, Set[int]] = {
    "trade debtors": {4400}, "prepayments": {4900},
    "trade creditors": {5200}, "dla": {5400}, "net wages": {5330}, "paye liabilities": {5320},
    "pension payable": {5352}, "vat": {5300}, "accruals": {5360}, "corporation tax": {5310},
}
LOAN_ROWS = ("loans due within 1 year", "loans due after 1 year")
OTHER = "Other balances in the books with no schedule (B1-ETB final)"
CHECK = "Check: lead total less every B1-ETB code of this lead (must be nil)"


def _etb_codes(wb) -> List[Tuple[int, str]]:
    from backend.app.services.workbook.etb_rows import data_rows
    ws = wb[ETB]
    out = []
    for r in data_rows(ws):
        code = ws.cell(row=r, column=1).value
        if isinstance(code, (int, float)):
            out.append((int(code), str(ws.cell(row=r, column=2).value or "")))
    return out


def _total_row(ws) -> int:
    """The lead's total: the last row whose column D adds up the rows above it."""
    rows = [r for r in range(1, ws.max_row + 1)
            if isinstance(ws.cell(row=r, column=4).value, str) and ws.cell(row=r, column=4).value.startswith("=SUM(")]
    return rows[-1] if rows else 0


def _loan_codes(wb) -> Set[int]:
    """The codes the loans lead (G4) adds up: its lenders' codes and those its ETB check names."""
    if LOANS not in wb.sheetnames:
        return set()
    ws = wb[LOANS]
    out: Set[int] = set()
    for r in range(7, min(ws.max_row, 60) + 1):
        b = ws.cell(row=r, column=2).value
        if isinstance(b, (int, float)) or (isinstance(b, str) and b.isdigit()):
            out.add(int(b))
        for c in range(4, 8):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str) and "SUMIF" in v:
                out.update(int(x) for x in re.findall(r"\$A:\$A,(\d{4}),", v))
    return out


def _codes_named(ws) -> Set[int]:
    """The ETB codes a schedule tab's formulas look up (its first 40 rows: the control block)."""
    out: Set[int] = set()
    if getattr(ws, "_not_a_schedule", False):      # a T drawn for show, not the codes' schedule (D2 stock)
        return out
    for row in ws.iter_rows(max_row=40):
        for c in row:
            if isinstance(c.value, str) and "$A:$A" in c.value:
                out.update(int(x) for x in re.findall(r"\$A:\$A,\"?(\d{4})\b", c.value))
    return out


def covered(wb, ws, total: int) -> Set[int]:
    """The codes the lead's own rows hold: a row counts only when it takes its figure from a schedule."""
    out: Set[int] = set()
    for r in range(7, total):
        label = str(ws.cell(row=r, column=2).value or "").strip().lower()
        d = ws.cell(row=r, column=4).value
        # A row added for its code (OTHER DEBTORS with the code as its reference, its figure written in): that code
        ref = ws.cell(row=r, column=3).value
        if d is not None and (isinstance(ref, (int, float)) or (isinstance(ref, str) and ref.strip().isdigit())):
            out.add(int(ref))
        if not (isinstance(d, str) and d.startswith("=") and "!" in d):
            continue
        # The schedule the row reads (E4 deposits on 4420, G8 pension on 5352): the ETB codes its own formulas name
        for tab in re.findall(r"'((?:[^']|'')+)'!|([A-Za-z][\w.\-]*)!", d):
            name = (tab[0] or tab[1]).replace("''", "'")
            if name != ETB and name in wb.sheetnames:
                out |= _codes_named(wb[name])
        for c in (4, 5):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str):
                out.update(int(x) for x in re.findall(r"\$A:\$A,(\d{4}),", v))
        if label in ROW_CODES:
            out |= ROW_CODES[label]
        elif label in LOAN_ROWS:
            out |= _loan_codes(wb)
    return out


def add_lead_codes(wb) -> int:
    """Writes the other balances and the code list under each lead that has a total. Returns how many leads got one."""
    if ETB not in wb.sheetnames:
        return 0
    codes = _etb_codes(wb)
    done = 0
    for title, ranges, sign in LEADS:
        if title not in wb.sheetnames:
            continue
        ws = wb[title]
        total = _total_row(ws)
        if not total:
            continue
        mine = [(c, n) for c, n in codes if any(lo <= c <= hi for lo, hi in ranges)]
        held = covered(wb, ws, total)
        other = [(c, n) for c, n in mine if c not in held]
        neg = "" if sign > 0 else "-"

        def etb_rows(start: int, rows: List[Tuple[int, str]]) -> None:
            for i, (code, name) in enumerate(rows):
                row = start + i
                ws.cell(row=row, column=1, value=code)
                ws.cell(row=row, column=2, value=name)
                _money(ws.cell(row=row, column=4, value=f"={neg}SUMIF('{ETB}'!$A:$A,$A{row},'{ETB}'!$N:$N)"))
                _money(ws.cell(row=row, column=5, value=f"={neg}SUMIF('{ETB}'!$A:$A,$A{row},'{ETB}'!$T:$T)"))

        def total_line(row: int, label: str, first: int, last: int, any_rows: bool) -> None:
            ws.cell(row=row, column=2, value=label).font = BOLD
            for col in ("D", "E"):
                ws[f"{col}{row}"] = f"=SUM({col}{first}:{col}{last})" if any_rows else 0
                _money(ws[f"{col}{row}"], bold=True, total=True)

        r = ws.max_row + 3
        # 1. The balances no row holds, inside the lead's total
        if other:
            ws.cell(row=r, column=2, value=OTHER).font = BOLD
            etb_rows(r + 1, other)
            sub = r + 1 + len(other)
            total_line(sub, "Other balances", r + 1, sub - 1, True)
            for col in ("D", "E"):
                f = ws[f"{col}{total}"].value
                if isinstance(f, str) and f.startswith("="):
                    ws[f"{col}{total}"] = f"{f}+{col}{sub}"
            r = sub + 3
        # 2. Every code of the lead, and the check
        ws.cell(row=r, column=2, value="Every B1-ETB code of this lead (final balance)").font = BOLD
        ws.cell(row=r + 1, column=1, value="Code").font = BOLD
        ws.cell(row=r + 1, column=2, value="Account").font = BOLD
        ws.cell(row=r + 1, column=4, value=ws.cell(row=6, column=4).value)
        ws.cell(row=r + 1, column=5, value=ws.cell(row=6, column=5).value)
        first = r + 2
        etb_rows(first, mine)
        tot = first + len(mine)
        total_line(tot, "Total of the B1-ETB codes", first, tot - 1, bool(mine))
        ws.cell(row=tot + 1, column=2, value=CHECK)
        _money(ws.cell(row=tot + 1, column=4, value=f"=ROUND(D{total}-D{tot},2)"))
        done += 1
    return done
