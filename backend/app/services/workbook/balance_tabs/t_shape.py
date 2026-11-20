"""A control account as one T, the way the screen shows it: a single T (not a list with a T beside it), each line
named rather than one 'movement from TB' line.

    Details                              | Ref                        | Debit £ | Credit £
    Opening balance b/f                  | last year's filed TB       |         |
    Opening adjustment                   | books v last year's TB     |         |   (a ledger-read ETB only)
    Bank receipts / Bank payments / ...  | GL: n lines                |         |   (the GL tab's 'T line' column)
    TB not in the ledger                 | TB less the ledger         |         |   (a ledger-read ETB only)
    Journal 3: ... (each by name)        | B2                         |         |
    Balance c/d                          |                            |         |   (the balancing figure)
    Total                                |                            |         |
    Check: c/d v B1-ETB final balance (must be nil)
    Check: the named lines v B1-ETB movement (must be nil)

Every figure is a formula: the b/f, adjustment and TB lines from B1-ETB, the named lines by SUMIFS on the GL tab by code
and T line, the journals from B2 by number. A named line shows its net on one side (one figure a line, as on the
screen). The c/d is the balancing figure, so the T always adds up; the checks tie it to the ETB.

Returns the cells other tabs link to, as formula terms ('debit +' nets): bf, adj, jnl, cf."""

from typing import Dict, List

from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from backend.app.services.workbook.balance_tabs.common import BOLD, CHECK_FILL, _etb, _money, period_start_formula
from backend.app.services.workbook.balance_tabs.leads import _journals_on, note_schedule
from backend.app.services.workbook.context import GL_TAB

HEAD = ("Details", "Ref", "Debit £", "Credit £")
OLD_HEADS = {"£", "Debit", "Credit", "Debit £", "Credit £", "Amount £", "Amount"}
PLAIN = Font(name="Calibri", size=10)
FORMULA_LIMIT = 7500           # under Excel's 8,192 characters, with room for the ROUND / MAX around it
T_LINE_HEAD = "T line"            # the GL tab's column (core_gl_k)


def gl_column(wb, head: str) -> str:
    """The GL tab's column letter for a heading on its row 6 ('' when the tab or the column is not there)."""
    if GL_TAB not in wb.sheetnames:
        return ""
    ws = wb[GL_TAB]
    for c in range(1, ws.max_column + 1):
        if ws.cell(row=6, column=c).value == head:
            return get_column_letter(c)
    return ""


def named_lines(ctx, codes) -> List[tuple]:
    """(name, number of GL lines) on these codes as the GL tab's T line column names them, the biggest net first and
    nil ones left out (the screen's order, services/papers/rollforward.py)."""
    tline = gl_column(ctx.wb, T_LINE_HEAD)
    if not tline:
        return []
    wanted = {str(c) for c in _codes(codes)}
    ws = ctx.wb[GL_TAB]
    col = ws[tline][0].column
    groups: Dict[str, list] = {}
    for row in ws.iter_rows(min_row=7, values_only=True):
        if row[0] is None or str(row[0]) not in wanted:
            continue
        g = groups.setdefault(row[col - 1] or "", [0, 0.0])
        g[0] += 1
        g[1] += float(row[6] or 0) - float(row[7] or 0)
    return [(name, n) for name, (n, net) in sorted(groups.items(), key=lambda x: -abs(x[1][1])) if abs(net) >= 0.005]


def account_lines(ctx, accounts) -> List[tuple]:
    """The T's named lines for ledger accounts read by name, not code (a lender's loan accounts, which may share a
    code with other lenders): [(label, ref, debit formula, credit formula, "mv")] by SUMIFS on the GL tab's account
    name (B) and T line columns, the biggest net first, nil ones left out. [] when the GL tab has no T line column."""
    tline = gl_column(ctx.wb, T_LINE_HEAD)
    wanted = {str(a) for a in accounts if a}
    # A name SUMIFS would read as a pattern or a comparison ('*', '?', '~', '<', '>', '='): the one movement line
    if not tline or not wanted or any(ch in a for a in wanted for ch in "*?~<>="):
        return []
    ws = ctx.wb[GL_TAB]
    col = ws[tline][0].column
    groups: Dict[str, list] = {}
    for row in ws.iter_rows(min_row=7, values_only=True):
        if row[0] is None or str(row[1] or "") not in wanted:
            continue
        g = groups.setdefault(row[col - 1] or "", [0, 0.0])
        g[0] += 1
        g[1] += float(row[6] or 0) - float(row[7] or 0)
    out = []
    for name, (n, net) in sorted(groups.items(), key=lambda x: -abs(x[1][1])):
        if abs(net) < 0.005:
            continue
        crit = name.replace('"', '""')

        def side(c: str) -> str:
            return "+".join(f"SUMIFS('{GL_TAB}'!${c}:${c},'{GL_TAB}'!$B:$B,\"{a.replace(chr(34), chr(34) * 2)}\","
                            f"'{GL_TAB}'!${tline}:${tline},\"{crit}\")" for a in sorted(wanted))
        dr, cr = side("G"), side("H")
        out.append((name, f"GL: {n} line{'s' if n != 1 else ''}", f"=MAX(0,{dr}-({cr}))", f"=MAX(0,{cr}-({dr}))", "mv"))
    # Excel takes a formula of at most 8,192 characters (a longer one and it repairs the file, dropping the figures):
    # with very many accounts the T keeps its one movement line instead
    if any(len(r[2]) > FORMULA_LIMIT or len(r[3]) > FORMULA_LIMIT for r in out):
        return []
    return out


def _codes(codes) -> List[int]:
    return [codes] if isinstance(codes, int) else list(codes)


def _sumifs(col: str, codes: List[int], crit_col: str, crit: str) -> str:
    return "+".join(f"SUMIFS('{GL_TAB}'!${col}:${col},'{GL_TAB}'!$A:$A,{c},'{GL_TAB}'!${crit_col}:${crit_col},\"{crit}\")"
                    for c in codes)


def signed(term: str, owed: bool) -> str:
    """A debit + term as the account is read: an amount owed (a liability) credit +."""
    return f"-({term})" if owed else term


def t_account(ctx, ws, codes, top: int = 6, owed: bool = False, schedule: bool = True) -> Dict[str, object]:
    """Write the T for these codes from row `top` (its heading row) in columns B-E. owed: a liability, read credit +
    (the tiles at the top of the tab and the "_s" terms). Returns {"bf", "adj", "jnl", "books", "cf": formula terms
    debit +; "bf_s", "cf_s", "books_s", "jnl_s": the same as the account is read; "cf_row", "check_rows", "end"}."""
    codes = _codes(codes)
    if schedule:            # this tab is the codes' schedule (B1-ETB's Schedule column; the leads' 'no schedule' list)
        note_schedule(ws, codes)
    else:
        ws._not_a_schedule = True
    # A template's own headings just above ('£', 'Debit', 'Credit') would sit over the T's own
    for r in range(max(1, top - 3), top):
        for c in range(1, 8):
            above = ws.cell(row=r, column=c)
            if type(above).__name__ != "MergedCell" and str(above.value or "").strip() in OLD_HEADS:
                above.value = None
    for c, text in enumerate(HEAD, 2):
        ws.cell(row=top, column=c, value=text).font = BOLD
    # The named lines add up to B1-ETB's movement only when that movement is the ledger's (a ledger-read ETB); with a
    # TTB movement the T keeps the one line
    tline = gl_column(ctx.wb, T_LINE_HEAD) if ctx.tb_kind else ""
    rows: List[tuple] = []          # (label, ref, debit formula, credit formula, key)

    def etb(col_dr: str, col_cr: str) -> tuple:
        return f"={_etb(codes, col_dr)}", f"={_etb(codes, col_cr)}"

    rows.append(("Opening balance b/f", "last year's filed TB" if ctx.tb_kind else "opening balance", *etb("F", "G"), "bf"))
    if ctx.tb_kind:
        rows.append(("Opening adjustment", "books v last year's filed TB", *etb("O", "P"), "adj"))
    names = named_lines(ctx, codes) if tline else []
    # Very many codes: each named line's formula would pass Excel's limit, so the one movement line instead
    if names and len(_sumifs("G", codes, tline, "x" * max(len(nm) for nm, _ in names))) * 2 > FORMULA_LIMIT:
        names = []
    for name, n in names:
        crit = name.replace('"', '""')
        dr, cr = _sumifs("G", codes, tline, crit), _sumifs("H", codes, tline, crit)
        # One figure a line: the net on its side
        rows.append((name, f"GL: {n} line{'s' if n != 1 else ''}", f"=MAX(0,{dr}-({cr}))", f"=MAX(0,{cr}-({dr}))", "mv"))
    if not names:
        rows.append(("Movement per GL" if ctx.tb_kind else "Movement per TTB", "B1-ETB", *etb("H", "I"), "mv"))
    if ctx.tb_kind:
        s_ = _etb(codes, "S")
        rows.append(("TB not in the ledger", "TB less the ledger", f"=MAX(0,{s_})", f"=MAX(0,-({s_}))", "tb"))
    named = _journals_on(ctx, codes)
    if named:
        for no, text in named:
            net = "+".join(f"SUMIFS('B2-Journals'!$F:$F,'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{c})"
                           f"-SUMIFS('B2-Journals'!$G:$G,'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{c})" for c in codes)
            rows.append((f"Journal {no}: {text}"[:90], "B2", f"=MAX(0,{net})", f"=MAX(0,-({net}))", "jnl"))
    else:
        rows.append(("Adjusting journals", "B2", *etb("J", "K"), "jnl"))


    def checks(closing: str, term) -> List[tuple]:
        out = [("Check: balance c/d v B1-ETB final balance (must be nil)", f"=ROUND({closing}-({_etb(codes, 'N')}),2)")]
        if names:
            mv = f"({_etb(codes, 'H')})-({_etb(codes, 'I')})"
            out.append(("Check: the named lines v B1-ETB movement (must be nil)", f"=ROUND(({term({'mv'})})-({mv}),2)"))
        if ctx.tb_kind:
            # The ledger read against the client's TB: a difference is shown as 'TB not in the ledger' and still stops
            # the workbook as a draft until it is explained (books less TB)
            # books less TB as the account is read: owed + on a liability (the leads' sign), debit + otherwise
            out.append(("Check: books v TB (must be nil)", f"=ROUND({signed(f'-({_etb(codes, chr(83))})', owed)},2)"))
        return out

    return write_t(ctx, ws, rows, top, owed, checks)


def write_t(ctx, ws, rows: List[tuple], top: int, owed: bool, checks=None) -> Dict[str, object]:
    """Write a T from its lines (label, ref, debit formula, credit formula, key: bf / adj / mv / tb / jnl) under the
    heading on row `top` (columns B-E): the c/d as the balancing figure, the totals, then the checks
    (checks(closing term, term(keys)) -> [(label, formula)]). Returns the terms other tabs link to (see t_account)."""
    if ws.cell(row=top, column=2).value != HEAD[0]:
        for c, text in enumerate(HEAD, 2):
            ws.cell(row=top, column=c, value=text).font = BOLD
    first = top + 1
    for i, (label, ref, dr, cr, _key) in enumerate(rows):
        r = first + i
        # Plain text: a template's own colours on these cells (blue, red, bold) are not the T's
        for c, text in ((2, label), (3, ref)):
            cell = ws.cell(row=r, column=c, value=text)
            cell.font, cell.alignment = PLAIN, Alignment()
        for c, v in ((4, dr), (5, cr)):
            cell = _money(ws.cell(row=r, column=c, value=v))
            cell.font, cell.alignment = PLAIN, Alignment()
    last = first + len(rows) - 1
    cf = last + 1
    tot = cf + 1
    # The balance carried down balances the account: a debit balance on the credit side, and the other way round
    ws.cell(row=cf, column=2, value="Balance c/d").font = BOLD
    for r, when in ((cf, "=YearEnd"), (first, period_start_formula(ctx))):
        cell = ws.cell(row=r, column=1, value=when)
        cell.number_format, cell.font = "dd/mm/yyyy", PLAIN
    _money(ws.cell(row=cf, column=4, value=f"=MAX(0,SUM(E{first}:E{last})-SUM(D{first}:D{last}))"))
    _money(ws.cell(row=cf, column=5, value=f"=MAX(0,SUM(D{first}:D{last})-SUM(E{first}:E{last}))"))
    ws.cell(row=tot, column=2, value="Total").font = BOLD
    _money(ws.cell(row=tot, column=4, value=f"=SUM(D{first}:D{cf})"), bold=True, total=True)
    _money(ws.cell(row=tot, column=5, value=f"=SUM(E{first}:E{cf})"), bold=True, total=True)

    def term(keys) -> str:
        parts = [f"(D{first + i}-E{first + i})" for i, row in enumerate(rows) if row[4] in keys]
        return "+".join(parts) or "0"

    closing = f"(E{cf}-D{cf})"                       # the closing balance, debit +
    rows_out = []
    for label, formula in (checks(closing, term) if checks else []):
        r = (rows_out[-1] if rows_out else tot) + 1
        ws.cell(row=r, column=2, value=label).font = BOLD
        cell = ws.cell(row=r, column=5, value=formula)
        _money(cell)
        cell.fill = CHECK_FILL
        rows_out.append(r)
    checks = rows_out
    for col, width in (("B", 46), ("C", 26), ("D", 15), ("E", 15)):
        if (ws.column_dimensions[col].width or 0) < width:
            ws.column_dimensions[col].width = width
    bf, jnl = term({"bf"}), term({"jnl"})
    books = term({"bf", "adj", "mv", "tb"})          # closing per the books and the TB, before the adjusting journals
    # The tiles at the top of the tab (look/figures): this year and last year as the account is read
    ws._t_tiles = (signed(bf, owed), signed(closing, owed))
    return {"bf": bf, "adj": term({"adj"}), "jnl": jnl, "books": books, "cf": closing,
            "bf_s": signed(bf, owed), "cf_s": signed(closing, owed), "books_s": signed(books, owed),
            "jnl_s": signed(jnl, owed), "cf_row": cf, "check_rows": checks, "end": checks[-1] if checks else tot}
