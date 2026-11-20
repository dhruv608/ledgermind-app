"""The stop rules the other tabs do not already check, each a labelled check cell on its own tab so A0 and the cover list it: red = 'must be nil' (the figures do not tie), amber = an 'unexplained'
difference that needs a reason or a client answer.

  C1 lead: net book value = the ETB's tangible fixed asset codes (red, 'Schedule v ETB')
  J2 reserves: reserves b/f = last year's retained earnings in PY-TB (red, 'Reserves b/f')
  H1 CT control: c/fwd = the ETB's 5310 (red); the tax charge in the accounts v the computation (amber)
  E1 / G1 / F1: balances on the wrong side - debtors in credit, creditors in debit, cash overdrawn (amber with a
  query, 'Negative balances')"""

from typing import List, Optional, Tuple

from backend.app.services.workbook.balance_tabs.common import _money

ETB = "'B1-ETB'"


def _sumifs(ranges: List[Tuple[int, int]], sign: str) -> str:
    """The ETB final of the codes in the ranges whose balance has the given sign ('<0' or '>0')."""
    return "+".join(f"SUMIFS({ETB}!$N:$N,{ETB}!$A:$A,\">={lo}\",{ETB}!$A:$A,\"<={hi}\",{ETB}!$N:$N,\"{sign}\")"
                    for lo, hi in ranges)


def _find(ws, column: int, text: str, first: bool = True) -> Optional[int]:
    rows = [r for r in range(1, ws.max_row + 1) if str(ws.cell(row=r, column=column).value or "").strip().upper()
            .startswith(text.upper())]
    return (rows[0] if first else rows[-1]) if rows else None


def _check(ws, label: str, formula: str, column: int, gap: int = 2) -> None:
    r = ws.max_row + gap
    ws.cell(row=r, column=2, value=label)
    _money(ws.cell(row=r, column=column, value=formula))


def fixed_assets_check(wb) -> bool:
    if "C1 (LEAD)" not in wb.sheetnames:
        return False
    ws = wb["C1 (LEAD)"]
    nbv = _find(ws, 2, "NET BOOK VALUE")
    total = next((c for c in range(3, 20) if str(ws.cell(row=7, column=c).value or "").strip().upper() == "TOTAL"), None)
    if not nbv or not total:
        return False
    col = ws.cell(row=nbv, column=total).column_letter
    _check(ws, "Check: net book value less the B1-ETB tangible fixed asset codes (must be nil)",
           f"=ROUND({col}{nbv}-SUMIFS({ETB}!$N:$N,{ETB}!$A:$A,\">=4100\",{ETB}!$A:$A,\"<=4199\"),2)", total)
    return True


def reserves_check(wb) -> bool:
    py = next((s for s in wb.sheetnames if s.startswith("PY-TB")), None)
    if "J2 - Reserves" not in wb.sheetnames or py is None or wb[py]["G6"].value != "Opens on (B1-ETB)":
        return False
    ref = "'" + py.replace("'", "''") + "'"
    _check(wb["J2 - Reserves"], "Check: reserves b/f (B1-ETB 8000 opening) less last year's retained earnings in "
                                "PY-TB (must be nil)",
           f"=ROUND(SUMIF({ETB}!$A:$A,8000,{ETB}!$F:$F)-SUMIF({ETB}!$A:$A,8000,{ETB}!$G:$G)"
           f"-SUMIFS({ref}!$E:$E,{ref}!$G:$G,8000),2)", 5)
    return True


def ct_checks(wb) -> bool:
    if "H1-Taxation" not in wb.sheetnames:
        return False
    ws = wb["H1-Taxation"]
    if str(ws["B14"].value or "").startswith("Balance C/Fwd"):
        # Row 17: under the box's totals (row 16 adds rows 8-15)
        ws["B17"] = "Check: c/fwd less B1-ETB 5310 corporation tax (must be nil)"
        _money(ws.cell(row=17, column=4, value=f"=ROUND(D14+SUMIF({ETB}!$A:$A,5310,{ETB}!$N:$N),2)"))
    r = _find(ws, 2, "Difference: accounts less computation")
    if r:
        ws.cell(row=r, column=2, value="Check: tax charge in the accounts less the computation: unexplained "
                                       "(must be nil)")
    return True


WRONG_SIDE_FLOOR = 100
WRONG_SIDE = [
    ("E1 (LEAD)", "Check: debtors and prepayments in credit: unexplained (must be nil)",
     [(4400, 4480), (4500, 4574), (4900, 4952)], "<0"),
    # Trade creditors, net wages, pension and other creditors, accruals, loans: a debit there is unusual. VAT, CT and
    # PAYE in debit are refunds due, each with its own control check; the director's loan in debit is the s455 point
    ("G1 (LEAD)", "Check: creditors in debit (trade, wages, pension, accruals, loans): unexplained (must be nil)",
     [(5000, 5017), (5100, 5120), (5200, 5299), (5330, 5399), (5500, 5520), (5600, 5799)], ">0"),
    ("F1 (LEAD)", "Check: bank overdrawn in the books: unexplained, check to the statement (must be nil)",
     [(4800, 4829)], "<0"),
    # Cash in hand below nil cannot happen (red)
    ("F1 (LEAD)", "Check: cash in hand below nil, which cannot happen (must be nil)", [(4830, 4830)], "<0"),
]


def wrong_side_checks(wb) -> int:
    done = 0
    for title, label, ranges, sign in WRONG_SIDE:
        if title in wb.sheetnames:
            # Under the firm's usual £100 floor (AR-04, U-DEB-002) a wrong-side balance is pennies: left out
            total = _sumifs(ranges, sign)
            _check(wb[title], label, f"=ROUND(IF(ABS({total})<{WRONG_SIDE_FLOOR},0,{total}),2)", 4)
            done += 1
    return done


def add_stop_checks(wb) -> None:
    if "B1-ETB" not in wb.sheetnames:
        return
    fixed_assets_check(wb)
    reserves_check(wb)
    ct_checks(wb)
    wrong_side_checks(wb)
