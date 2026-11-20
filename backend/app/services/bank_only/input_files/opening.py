"""Last year's trial balance: where each balance opens this year, and its names coded."""

from typing import Dict, Optional
import re

from backend.app.services.bank_only.input_files.bank import SUSPENSE_CODE
from backend.app.services.bank_only.input_files.common import OpeningCoder, Problem, RawInput, _amount, _col, _header


def brought_forward_code(code: int) -> int:
    """Where a balance of last year's TB opens this year (firm chart): P&L (codes below 4000) and last year's reserve
    movements (dividends 8010...) in 8000 profit and loss b/fwd; fixed asset additions / disposals in cost, and the
    depreciation charge / on disposals in depreciation b/fwd, of the same asset group; the rest where it is."""
    if code < 4000 or 8000 < code < 8100:
        return 8000
    if 4100 <= code < 4170:
        group, slot = code // 10 * 10, code % 10
        split = 4 if group in (4100, 4110, 4160) else 3      # property groups also have revaluation lines
        return group + (0 if slot < split else split)
    return code


def close_last_year(tb: Dict[int, float]) -> Dict[int, float]:
    """Last year's TB as this year's opening balances (a TB already closed is unchanged)."""
    out: Dict[int, float] = {}
    for code, amount in tb.items():
        to = brought_forward_code(code)
        out[to] = round(out.get(to, 0.0) + amount, 2)
    return {c: a for c, a in out.items() if abs(a) >= 0.005}


def _read_opening_tb(ws, out: RawInput) -> None:
    """Last year's closing trial balance: a firm code, a name, and a debit and credit (or one balance) per account.
    A line with a name and no code ('Bank current account | 2,438.06', the Code column left empty) is kept by its
    name, to be given a code from it (opening_uncoded)."""
    hr, heads = _header(ws, ["debit", "credit"])
    if hr is None:
        hr, heads = _header(ws, ["dr", "cr"])
    c_code = next((i for h, i in heads.items() if h in ("code", "nc", "n/c", "a/c") or re.search(r"\bcode\b|nominal", h)), None)
    c_name = _col({h: i for h, i in heads.items() if i != c_code}, "name", "account", "descr", "decr", "details",
                  "particulars")
    c_dr = _col(heads, "debit") if _col(heads, "debit") is not None else _col(heads, "dr")
    c_cr = _col(heads, "credit") if _col(heads, "credit") is not None else _col(heads, "cr")
    if hr is None or c_dr is None or c_cr is None or (c_code is None and c_name is None):
        out.problems.append(Problem("Opening", "HIGH", "Last year's trial balance was not read: it needs a heading "
                                                       "row with the account (code or name), Debit and Credit."))
        return

    def cell(row, c):
        return row[c] if c is not None and c < len(row) else None

    for row in ws.iter_rows(min_row=hr + 1, values_only=True):
        amount = round(_amount(cell(row, c_dr)) - abs(_amount(cell(row, c_cr))), 2)
        name = str(cell(row, c_name) or "").strip()
        try:
            code = int(str(cell(row, c_code)).strip().split()[0].split(".")[0])
        except (ValueError, IndexError, AttributeError):
            code = None
        if abs(amount) < 0.005:
            continue
        if code is not None:
            out.opening_tb[code] = round(out.opening_tb.get(code, 0.0) + amount, 2)
            if name:
                out.opening_names[code] = name
        elif name and not re.match(r"^(grand\s+)?totals?\b", name, re.I):
            out.opening_uncoded.append((name, amount))


def _code_opening_names(out: RawInput, code_names: Optional[OpeningCoder]) -> None:
    """Last year's TB lines with only a name get their firm code (the same code twice adds up). With no coder (the
    upload screen's first read) they stay uncoded and are said to be given codes later."""
    if not out.opening_uncoded:
        return
    if code_names is None:
        out.problems.append(Problem("Opening", "LOW", f"{len(out.opening_uncoded)} line(s) of last year's trial balance "
                                                      f"have a name but no code: they are given codes from their "
                                                      f"names on the Books tab."))
        return
    given = code_names(out.opening_uncoded)
    for name, amount in out.opening_uncoded:
        code, why, sure = given.get(name) or (None, "", False)
        if code is None:
            code, why, sure = SUSPENSE_CODE, "No code found for the name: in suspense until one is picked.", False
        out.opening_tb[code] = round(out.opening_tb.get(code, 0.0) + amount, 2)
        out.opening_names.setdefault(code, name)
        out.opening_lines.append({"name": name, "amount": amount, "code": code, "why": why, "sure": sure})
    out.opening_uncoded = []
    unsure = [l for l in out.opening_lines if not l["sure"]]
    if unsure:
        out.problems.append(Problem("Opening", "MEDIUM", f"Last year's trial balance had no codes: {len(out.opening_lines)} "
                                                         f"line(s) were given codes from their names, {len(unsure)} to "
                                                         f"check on the Books tab ({', '.join(l['name'] for l in unsure[:4])}"
                                                         f"{' ...' if len(unsure) > 4 else ''})."))
