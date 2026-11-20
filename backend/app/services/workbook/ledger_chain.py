"""The ledger chain from the GL tab to the TTB: every ledger line names the client TB account
it belongs to, and the TTB adds the ledger up per client account by formula beside the client's own TB, with the
difference (the GL v TB check, C4).

The General Ledger tab gets a last column, 'TB account': the TB account the line's account is (the ledger's names
often lack the TB's '7100 - ' prefix; a QuickBooks 'Parent:Child' line takes its parent's account when the TB has no
account of its own for it, as the codes do). The TTB gets three columns after its own: the code's name, the account's
movement per the GL (SUMIFS on that column) and the difference. A movement TB is the year's movement, so every account
is compared; a closing TB holds the opening too, so only the P&L accounts (nil at the start of the year) are compared,
and the balance sheet's opening is checked on B1-ETB (column O against last year's filed TB)."""

from typing import Callable, Dict, List, Optional, Tuple

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from backend.app.services.mapping.chart_lookup import account_name_keys
from backend.app.services.workbook.context import GL_TAB, format_std_code

GL_FIRST = 7
TTB_FIRST = 7
NAME_COL, GL_COL, DIFF_COL = 9, 10, 11          # TTB I, J, K: after the client TB's code, name, Dr, Cr, balance
DR_COL, CR_COL = 12, 13                         # TTB L, M: the ledger's gross debits and credits
MONEY = '#,##0.00;(#,##0.00);"-"'


def tb_account_matcher(accounts: List[Tuple[str, str]]) -> Callable[[str, str], Optional[str]]:
    """(ledger account name, the line's firm code) -> the TB account it is (None: none). accounts: (code, TB account
    name). The same keys the codes are matched by (chart_lookup.account_name_keys / sop.common.code_matcher), most
    exact first, then a sub-account's parents; a key two TB accounts share (one name under both Sales and
    Sub-Contractors) goes to the one on the line's own code."""
    owners: Dict[str, List[Tuple[str, str]]] = {}
    for code, name in accounts:
        for key in account_name_keys(name):
            if (code, name) not in owners.setdefault(key, []):
                owners[key].append((code, name))
    seen: Dict[Tuple[str, str], Optional[str]] = {}

    def match(raw: str, code: str = "") -> Optional[str]:
        raw = raw or ""
        if (raw, code) not in seen:
            keys = account_name_keys(raw)
            parts = [p.strip() for p in raw.lower().split(":")]
            if len(parts) > 1:
                keys += [p for p in (":".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)) if p not in keys]
            found = None
            for key in keys:
                names = {n for _c, n in owners.get(key, [])}
                if len(names) > 1:
                    names = {n for c, n in owners[key] if str(c) == str(code)}
                if len(names) == 1:
                    found = names.pop()
                    break
            seen[(raw, code)] = found
        return seen[(raw, code)]
    return match


def add_ledger_chain(ctx) -> None:
    """The TB account on each GL line and the TTB's GL columns (only when the ETB reads its movement from the ledger)."""
    wb, kind = ctx.wb, getattr(ctx, "tb_kind", "") or ""
    rows = getattr(ctx, "tx_rows", None) or []
    accounts = getattr(ctx, "tb_account_list", None) or []
    if kind not in ("movement", "closing") or not rows or not accounts or GL_TAB not in wb.sheetnames \
            or "TTB" not in wb.sheetnames:
        return
    bold = Font(name="Calibri", size=10, bold=True)
    gl = wb[GL_TAB]
    col = 1
    while gl.cell(row=6, column=col).value not in (None, ""):
        col += 1
    gl.cell(row=6, column=col, value="TB account").font = bold
    gl.column_dimensions[get_column_letter(col)].width = 34
    match = tb_account_matcher([(a[0], a[1]) for a in accounts])
    ttb_rows = list(getattr(ctx, "ttb_rows", None) or accounts)    # the TTB's own rows (no nil brought-forward lines)
    tb_names = {name for _c, name, _d, _cr in ttb_rows}
    # Every ledger line has a TTB row (GL > TTB > ETB): a line no TB account takes is summed on a row of
    # its own ledger account, so no money is left out of the TTB
    keys: List[str] = []
    only_gl: Dict[str, str] = {}                    # the ledger-only row's name -> its code
    for tx in rows:
        k = match(tx[3], str(tx[1] or ""))
        if k is None or k not in tb_names:
            name = str(tx[3] or "Unnamed account").strip()
            code = format_std_code(tx[1]) if tx[1] else ""
            k = name if only_gl.get(name, code) == code else f"{name} ({code or 'no code'})"
            if k in tb_names:
                k = f"{k} (GL only)"
            only_gl.setdefault(k, code)
        keys.append(k)
    for r, k in enumerate(keys, GL_FIRST):
        gl.cell(row=r, column=col, value=k)
    last_gl = GL_FIRST + len(rows) - 1
    key = f"'{GL_TAB}'!${get_column_letter(col)}${GL_FIRST}:${get_column_letter(col)}${last_gl}"
    gl_rng = lambda letter: f"'{GL_TAB}'!${letter}${GL_FIRST}:${letter}${last_gl}"
    net, debit, credit = gl_rng("I"), gl_rng("G"), gl_rng("H")

    ws = wb["TTB"]
    name_of = getattr(ctx, "account_name", None)
    heads = ("Code name", "Movement per GL (net, to B1-ETB)", "TB less GL (must be nil)" if kind == "movement"
             else "P&L: TB less GL (must be nil)", "Debits per GL", "Credits per GL")
    for c, head in zip((NAME_COL, GL_COL, DIFF_COL, DR_COL, CR_COL), heads):
        ws.cell(row=6, column=c, value=head).font = bold
        ws.column_dimensions[get_column_letter(c)].width = 30 if c == NAME_COL else 16
    # The TB's total row moves below the ledger-only rows
    old_total = TTB_FIRST + len(ttb_rows)
    for c in range(1, CR_COL + 1):
        ws.cell(row=old_total, column=c).value = None
    for i, (k, code) in enumerate(sorted(only_gl.items(), key=lambda kv: (kv[1], kv[0]))):
        r = old_total + i
        ws.cell(row=r, column=1, value=int(code) if code.isdigit() else (code or None))
        ws.cell(row=r, column=2, value=k)
        ws.cell(row=r, column=3, value="In the GL only (no TB line)")
        ws.cell(row=r, column=8, value=f"=+(F{r}-G{r})")
    all_rows = ttb_rows + [(code, k, 0.0, 0.0) for k, code in sorted(only_gl.items(), key=lambda kv: (kv[1], kv[0]))]
    seen = set()
    code_of: Dict[str, str] = {}                    # the TTB row a ledger line is summed on -> its code
    for i, (code, name, _dr, _cr) in enumerate(all_rows):
        r = TTB_FIRST + i
        if name_of is not None and str(code).isdigit():
            try:
                ws.cell(row=r, column=NAME_COL, value=name_of(int(code)))
            except Exception:
                pass
        if name in seen:            # a name the TB holds twice: the ledger is summed on its first row only
            continue
        seen.add(name)
        code_of[name] = str(code)
        ws.cell(row=r, column=GL_COL, value=f"=SUMIFS({net},{key},$B{r})").number_format = MONEY
        ws.cell(row=r, column=DR_COL, value=f"=SUMIFS({debit},{key},$B{r})").number_format = MONEY
        ws.cell(row=r, column=CR_COL, value=f"=SUMIFS({credit},{key},$B{r})").number_format = MONEY
        # A ledger-only row has no TB line to compare: its money shows on the TB account it missed (and on B1-ETB)
        if name not in only_gl and (kind == "movement" or (str(code).isdigit() and int(code) < 4000)):
            ws.cell(row=r, column=DIFF_COL, value=f"=ROUND(H{r}-J{r},2)").number_format = MONEY
    last = TTB_FIRST + len(all_rows) - 1
    total = last + 1
    ws.cell(row=total, column=2, value="TOTAL").font = bold
    for c in (6, 7, 8, GL_COL, DIFF_COL, DR_COL, CR_COL):
        letter = get_column_letter(c)
        cell = ws.cell(row=total, column=c, value=f"=SUM({letter}{TTB_FIRST}:{letter}{last})")
        cell.font, cell.number_format = bold, MONEY
        if c <= 8 and getattr(ctx, "accounting_total_border", None) is not None:
            cell.border = ctx.accounting_total_border
    # One check for the tab, on A0: every account's difference, so two that offset still show
    ws.cell(row=total + 2, column=2, value="Check: TB less GL, every account (must be nil)").font = bold
    cell = ws.cell(row=total + 2, column=DIFF_COL, value=f"=ROUND(SUMPRODUCT(ABS(K{TTB_FIRST}:K{last})),2)")
    cell.font, cell.number_format = bold, MONEY
    _etb_from_ttb(ctx, rows, keys, code_of)


def _etb_from_ttb(ctx, rows, keys, code_of) -> None:
    """B1-ETB's movement (H / I) as the net per code from the TTB, where the TTB and the ledger agree on the code's
    movement to the penny (they differ only when a ledger line with no code, or another code, belongs to a TB account):
    there the ledger's own figure stays, so the ETB's final balances never change. Counted in the report."""
    if "B1-ETB" not in ctx.wb.sheetnames:
        return
    from backend.app.services.workbook.etb_rows import data_rows
    by_gl: Dict[str, float] = {}
    by_ttb: Dict[str, float] = {}
    for tx, k in zip(rows, keys):
        amount = float(tx[7] or 0) - float(tx[8] or 0)
        if tx[1]:
            c = format_std_code(tx[1])
            by_gl[c] = by_gl.get(c, 0.0) + amount
        c = code_of.get(k, "")
        if c:
            by_ttb[c] = by_ttb.get(c, 0.0) + amount
    ws = ctx.wb["B1-ETB"]
    linked, kept = 0, []
    for r in data_rows(ws):
        code = format_std_code(ws.cell(row=r, column=1).value)
        if abs(by_gl.get(code, 0.0) - by_ttb.get(code, 0.0)) >= 0.005:
            kept.append(code)
            continue
        sumifs = f"ROUND(SUMIFS(TTB!$J:$J,TTB!$A:$A,$A{r}),2)"
        ws.cell(row=r, column=8, value=f"=MAX(0,{sumifs})")
        ws.cell(row=r, column=9, value=f"=MAX(0,-{sumifs})")
        linked += 1
    if linked:
        ws["H6"] = "Movement per TTB (net)" if not kept else "Movement per TTB (net; GL where marked)"
    from openpyxl.comments import Comment
    for r in data_rows(ws):
        if format_std_code(ws.cell(row=r, column=1).value) in kept:
            ws.cell(row=r, column=8).comment = Comment("Movement per GL by code: the TTB has a ledger line with no "
                                                       "code, or another code, on this account", "LedgerMind")
    if kept and getattr(ctx, "report_notes", None) is not None:
        ctx.report_notes.append(f"B1-ETB movement from the TTB on {linked} code(s); from the GL on {len(kept)} where a "
                                f"ledger line belongs to a TB account on another code: {', '.join(kept[:8])}")
