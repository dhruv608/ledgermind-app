"""The lead / T-account lines every control tab uses (b/fwd, movement, journals by name, c/fwd, checks)."""

from typing import Dict, List, Optional, Tuple
from openpyxl.utils import get_column_letter

from backend.app.services.workbook.balance_tabs.common import BOLD, CHECK_FILL, _criteria, _etb, _money


def lead_lines(ctx, ws, codes, top: int = 8, col: int = 4, owed: bool = False, nl: Optional[str] = None,
               cf_label: str = "Balance c/fwd", label_col: int = 2, types: Optional[List[str]] = None,
               type_col: int = 14) -> Dict[str, int]:
    """The lead sheet for these codes, one amount column, from row `top`: b/fwd (last
    year's filed TB), opening adjustment, movement per GL (the NL tab's lines when there is one, else B1-ETB H-I),
    closing per books, the TB per software, the two nil checks (books v TB; NL tab v ETB), adjusting journals and the
    c/fwd (the TB and the journals: B1-ETB's final balance), then a check against B1-ETB. owed: shown credit-positive
    (a liability). A workbook whose ETB has no ledger movement keeps b/fwd, movement per TTB, journals and c/fwd.
    Returns {line key: row}; "end" is the last row written."""
    sign = "-" if owed else ""
    c = get_column_letter(col)

    def net(dr: str, cr: str) -> str:
        return f"{sign}(({_etb(codes, dr)})-({_etb(codes, cr)}))"

    # Each adjusting journal on its own line by name, read from B2 by journal
    # number and code, then their total, checked against the ETB's journal columns
    named = _journals_on(ctx, codes)

    def journal_lines() -> None:
        if not named:
            lines.append(("jnl", "Adjusting journals (B2)", f"={net('J', 'K')}"))
            return
        for no, text in named:
            got = "+".join(f"SUMIFS('B2-Journals'!$F:$F,'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{k})"
                           f"-SUMIFS('B2-Journals'!$G:$G,'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{k})"
                           for k in codes)
            lines.append((f"j{no}", f"  Journal {no}: {text}"[:120], f"={sign}({got})"))
        first, last = f"j{named[0][0]}", f"j{named[-1][0]}"
        lines.append(("jnl", "Adjusting journals (B2), total", f"=SUM({{{first}}}:{{{last}}})"))
        lines.append(("chk_jnl", "Check: journals by name v B1-ETB journals (must be nil)",
                      f"=ROUND({{jnl}}-({net('J', 'K')}),2)"))

    lines: List[Tuple[str, str, str]] = []
    if getattr(ctx, "tb_kind", ""):
        lines.append(("bf", "Balance b/fwd (last year's filed TB)", f"={net('F', 'G')}"))
        lines.append(("adj", "Opening adjustment (books v last year's filed TB)", f"={net('O', 'P')}"))
        if nl and types:
            # The movement by type (drawings, money introduced, salary, dividends ... each on its own line), read
            # from the ledger tab's type column, then their total
            col_t = get_column_letter(type_col)
            for i, label in enumerate(types):
                got = "+".join(f"SUMIFS('{nl}'!$H:$H,'{nl}'!$B:$B,{k},'{nl}'!${col_t}:${col_t},{_criteria(label)})"
                               f"-SUMIFS('{nl}'!$I:$I,'{nl}'!$B:$B,{k},'{nl}'!${col_t}:${col_t},{_criteria(label)})"
                               for k in codes)
                lines.append((f"t{i}", f"  {label}", f"={sign}({got})"))
            lines.append(("mv", f"Movement per GL ({nl.split(' ')[0].rstrip('-')}), total",
                          f"=SUM({{t0}}:{{t{len(types) - 1}}})"))
        elif nl:
            ledger = "+".join(f"SUMIF('{nl}'!$B:$B,{k},'{nl}'!$H:$H)-SUMIF('{nl}'!$B:$B,{k},'{nl}'!$I:$I)"
                              for k in codes) or "0"
            lines.append(("mv", f"Movement per GL ({nl.split(' ')[0].rstrip('-')})", f"={sign}({ledger})"))
        else:
            lines.append(("mv", "Movement per GL", f"={net('H', 'I')}"))
        lines.append(("books", "Closing per books", "={bf}+{adj}+{mv}"))
        lines.append(("tb", "TB per software (check)",
                      f"={sign}(({_etb(codes, 'R')})+({_etb(codes, 'S')}))"))
        lines.append(("chk_tb", "Check: books v TB (must be nil)", "=ROUND({books}-{tb},2)"))
        if nl:
            lines.append(("chk_nl", "Check: ledger tab v ETB movement (must be nil)", f"=ROUND({{mv}}-{net('H', 'I')},2)"))
        journal_lines()
        lines.append(("cf", cf_label, "={tb}+{jnl}"))
    else:
        lines.append(("bf", "Balance b/fwd", f"={net('F', 'G')}"))
        lines.append(("mv", "Movement per TTB", f"={net('H', 'I')}"))
        journal_lines()
        lines.append(("cf", cf_label, "={bf}+{mv}+{jnl}"))
    lines.append(("chk_etb", "Check: B1-ETB final balance (must be nil)", f"=ROUND({{cf}}-({sign}({_etb(codes, 'N')})),2)"))
    rows = {key: top + i for i, (key, _l, _f) in enumerate(lines)}
    refs = {key: f"{c}{r}" for key, r in rows.items()}
    note_schedule(ws, codes)
    for key, label, formula in lines:
        r = rows[key]
        ws.cell(row=r, column=label_col, value=label)
        cell = ws.cell(row=r, column=col, value=formula.format(**refs))
        if key in ("books", "cf"):
            ws.cell(row=r, column=label_col).font = BOLD
            _money(cell, bold=True, total=True)
        else:
            _money(cell)
        if key.startswith("chk"):
            cell.fill = CHECK_FILL
    # The date beside the balance brought forward and carried forward, as E2 / G2 have them
    if label_col > 1:
        from backend.app.services.workbook.balance_tabs.common import period_start_formula
        for key, date_formula in (("bf", period_start_formula(ctx)), ("cf", "=YearEnd")):
            date_cell = ws.cell(row=rows[key], column=1)
            if date_cell.value is None and type(date_cell).__name__ != "MergedCell":
                date_cell.value = date_formula
                date_cell.number_format = "dd/mm/yyyy"
    rows["end"] = top + len(lines) - 1
    t_account(ctx, ws, codes, top, col, nl)
    return rows


T_WIDTH = 3                     # Detail | Debit | Credit


def t_account(ctx, ws, codes, top: int, col: int, nl: Optional[str] = None) -> Optional[int]:
    """The control account as a T (Detail | Debit | Credit) beside the lead: debits on the left, credits on the right, from B1-ETB's own debit and credit columns (b/fwd F-G,
    opening adjustment O-P, journals J-K), the year's movement as the ledger's gross debits and credits (the NL tab's
    H and I) when there is one, else B1-ETB H-I, and the balance carried forward as the balancing figure, then both
    totals and a check that the c/fwd is B1-ETB's final balance. The lead beside it stays as it is (every link reads
    it). Returns the first column used, or None when the place beside the lead is taken."""
    rows_needed = 10
    start = None
    for first in (col + 2, col + 6, col + 10):
        cells = [ws.cell(row=r, column=c) for r in range(top - 1, top - 1 + rows_needed)
                 for c in range(first, first + T_WIDTH)]
        if all(x.value in (None, "") and type(x).__name__ != "MergedCell" for x in cells):
            start = first
            break
    if start is None:
        return None
    d, k = get_column_letter(start + 1), get_column_letter(start + 2)

    def side(code_col: str) -> str:
        return _etb(codes, code_col)

    if nl:
        mv_dr = "+".join(f"SUMIF('{nl}'!$B:$B,{c},'{nl}'!$H:$H)" for c in codes) or "0"
        mv_cr = "+".join(f"SUMIF('{nl}'!$B:$B,{c},'{nl}'!$I:$I)" for c in codes) or "0"
        mv_label = f"Movement per GL ({nl.split(' ')[0].rstrip('-')})"
    else:
        mv_dr, mv_cr = side("H"), side("I")
        mv_label = "Movement per GL" if getattr(ctx, "tb_kind", "") else "Movement per TTB"
    # Every part of B1-ETB's final balance (N = F-G + O-P + H-I + J-K + S), so the T always agrees to it
    s = side("S")
    lines = [("Balance b/fwd", side("F"), side("G")),
             ("Opening adjustment", side("O"), side("P")),
             (mv_label, mv_dr, mv_cr),
             ("TB not in the ledger", f"MAX(0,{s})", f"MAX(0,-({s}))"),
             ("Adjusting journals (B2)", side("J"), side("K"))]
    head = top - 1
    for c, text in enumerate(("T-account", "Debit £", "Credit £")):
        ws.cell(row=head, column=start + c, value=text).font = BOLD
    for i, (label, dr, cr) in enumerate(lines):
        r = top + i
        ws.cell(row=r, column=start, value=label)
        _money(ws.cell(row=r, column=start + 1, value=f"={dr}"))
        _money(ws.cell(row=r, column=start + 2, value=f"={cr}"))
    first, last = top, top + len(lines) - 1
    cf = last + 1
    tot = cf + 1
    # The balance carried forward balances the account: a debit balance on the credit side, and the other way round
    ws.cell(row=cf, column=start, value="Balance c/fwd").font = BOLD
    _money(ws.cell(row=cf, column=start + 1, value=f"=MAX(0,SUM({k}{first}:{k}{last})-SUM({d}{first}:{d}{last}))"))
    _money(ws.cell(row=cf, column=start + 2, value=f"=MAX(0,SUM({d}{first}:{d}{last})-SUM({k}{first}:{k}{last}))"))
    ws.cell(row=tot, column=start, value="Total").font = BOLD
    _money(ws.cell(row=tot, column=start + 1, value=f"=SUM({d}{first}:{d}{cf})"), bold=True, total=True)
    _money(ws.cell(row=tot, column=start + 2, value=f"=SUM({k}{first}:{k}{cf})"), bold=True, total=True)
    chk = ws.cell(row=tot + 1, column=start, value="Check: T-account c/fwd v B1-ETB final balance (must be nil)")
    cell = ws.cell(row=tot + 1, column=start + 2,
                   value=f"=ROUND(({k}{cf}-{d}{cf})-({_etb(codes, 'N')}),2)")
    _money(cell)
    cell.fill = CHECK_FILL
    chk.font = BOLD
    for c, width in ((start, 34), (start + 1, 14), (start + 2, 14)):
        letter = get_column_letter(c)
        if (ws.column_dimensions[letter].width or 0) < width:
            ws.column_dimensions[letter].width = width
    return start


def note_schedule(ws, codes) -> None:
    """Which tab holds each code's schedule (B1-ETB's Schedule column): kept on the workbook, the
    first tab named for a code wins."""
    refs = getattr(ws.parent, "_schedule_refs", None)
    if refs is None:
        refs = {}
        ws.parent._schedule_refs = refs
    for k in codes:
        refs.setdefault(str(k), ws.title)


MAX_NAMED_JOURNALS = 60     # each by name up to this many; beyond it the total alone


def _journals_on(ctx, codes) -> List[Tuple[int, str]]:
    """(journal number, narrative) of each approved journal with a line on these codes, in B2's order."""
    wanted = {str(c) for c in codes}
    seen: Dict[int, str] = {}
    for j in getattr(ctx, "journals", None) or []:
        no = j.get("no")
        if no is None or str(j.get("code")) not in wanted:
            continue
        seen.setdefault(int(no), " ".join(str(j.get("narrative") or "").split()))
    out = sorted(seen.items())
    return out if len(out) <= MAX_NAMED_JOURNALS else []


def named_journals_block(ctx, ws, codes, row: int, col: int, total_ref: str, owed: bool = False) -> int:
    """The adjusting journals on these codes by name (each journal on its own line), in
    a side block from (row, col) for a tab whose own rows are fixed (a loan G4.n, the CT control on H1): each journal
    from B2 by number and code, their total, and a check against the tab's own journal line (total_ref). Nothing when
    no journal touches the codes (or more than MAX_NAMED_JOURNALS). Returns the row after the block."""
    named = _journals_on(ctx, codes)
    if not named:
        return row
    sign = "-" if owed else ""
    amount = get_column_letter(col + 1)
    ws.cell(row=row, column=col, value="Adjusting journals by name (B2)").font = BOLD
    first = row + 1
    for i, (no, text) in enumerate(named):
        r = first + i
        got = "+".join(f"SUMIFS('B2-Journals'!$F:$F,'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{k})"
                       f"-SUMIFS('B2-Journals'!$G:$G,'B2-Journals'!$A:$A,{no},'B2-Journals'!$E:$E,{k})" for k in codes)
        ws.cell(row=r, column=col, value=f"Journal {no}: {text}"[:120])
        _money(ws.cell(row=r, column=col + 1, value=f"={sign}({got})"))
    last = first + len(named) - 1
    ws.cell(row=last + 1, column=col, value="Total").font = BOLD
    _money(ws.cell(row=last + 1, column=col + 1, value=f"=SUM({amount}{first}:{amount}{last})"), bold=True, total=True)
    ws.cell(row=last + 2, column=col, value="Check: journals by name v the journals line (must be nil)")
    chk = ws.cell(row=last + 2, column=col + 1, value=f"=ROUND({amount}{last + 1}-{total_ref},2)")
    _money(chk)
    chk.fill = CHECK_FILL
    ws.column_dimensions[get_column_letter(col)].width = max(ws.column_dimensions[get_column_letter(col)].width or 0, 48)
    ws.column_dimensions[amount].width = max(ws.column_dimensions[amount].width or 0, 14)
    return last + 3
