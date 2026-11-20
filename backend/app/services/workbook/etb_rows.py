"""The ETB's account rows: from row 8 down, with one blank row between the P&L codes and the balance sheet codes, so a
reader steps over a single blank row and stops at two."""

from typing import Any, List

FIRST_ROW = 8
PL_LAST_CODE = 3999


def is_pl(code: Any) -> bool:
    return isinstance(code, int) and code <= PL_LAST_CODE


def code_rows(codes: List[Any]) -> List[int]:
    """The row of each code in order: one blank row after the last P&L code when balance sheet codes follow."""
    rows, r = [], FIRST_ROW
    for i, code in enumerate(codes):
        if i and is_pl(codes[i - 1]) and not is_pl(code):
            r += 1
        rows.append(r)
        r += 1
    return rows


def data_rows(ws) -> List[int]:
    """The rows holding an account (column A filled), stepping over the one blank row between P&L and balance sheet."""
    out, r = [], FIRST_ROW
    while True:
        if ws.cell(row=r, column=1).value not in (None, ""):
            out.append(r)
        elif ws.cell(row=r + 1, column=1).value in (None, ""):
            return out
        r += 1
