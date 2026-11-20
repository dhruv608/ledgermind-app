"""One director's loan control per director, each with its ledger. The director's loan accounts in the TB (5400, 5401,
5402, 5800) are put to their director by the name in the account ('Director Loan account J Smith', 'Directors Loan -
John') or the directors on the client details; an account naming no one stays 'Not named'. With two or more directors
a tab per director (G3.D1, G3.D2 ...) follows the G3 lead: balance b/f, each type of entry on its own line, balance
c/fwd checked to the TB, and the ledger with its running balance (the highest balance in the year). One director: G3
alone. The G3 lead gets a table by director adding up to its own c/fwd."""

import json
import re
from typing import Dict, List, Optional, Set

DLA_CODES = {5400, 5401, 5402, 5800}
NOT_NAMED = "Not named"
# Words of a director's loan account name that are not the person ('Directors loan account (Current liabilities -
# creditors < 1 year) - drawings')
NOT_PERSON = re.compile(r"\([^)]*\)|\b(?:directors?'?s?|loans?|accounts?|a/c|dla|current|long term|liabilit\w*|"
                        r"creditors?|drawings?|capital|introduced|interest|shareholders?|owners?|personal|due|to|from|"
                        r"the|and|of|year|within|after|one|mr|mrs|ms|miss|dr)\b|\d+|[^A-Za-z' ]", re.I)


def person_of(name: str) -> Optional[str]:
    """The person a director's loan account is named for ('J Smith', 'John'), or None."""
    words = [w for w in re.sub(r"\s+", " ", NOT_PERSON.sub(" ", name or "")).split() if w]
    if not 1 <= len(words) <= 3 or not all(w[0].isupper() for w in words):
        return None
    return " ".join(words)


def _same(person: str, director: str) -> bool:
    p = [w.lower() for w in re.findall(r"[A-Za-z']+", person)]
    q = [w.lower() for w in re.findall(r"[A-Za-z']+", director)]
    if not p or not q:
        return False
    if len(p) == 1:                     # one name: a first name or a surname of the director
        return p[0] in q
    return p[-1] == q[-1] and p[0][0] == q[0][0]


def director_groups(tb_records, directors: List[str]) -> Dict[str, Set[str]]:
    """{director: the TB account names of their loan}, when two or more directors have one; else {}."""
    groups: Dict[str, Set[str]] = {}
    for t in tb_records:
        if t.std_code not in DLA_CODES:
            continue
        name = t.raw_account_name or ""
        person = person_of(name)
        label = NOT_NAMED
        if person:
            label = next((d for d in directors if _same(person, d)), person)
        groups.setdefault(label, set()).add(name)
    named = [g for g in groups if g != NOT_NAMED]
    return groups if len(named) >= 2 else {}


def _directors(engagement) -> List[str]:
    profile = getattr(engagement, "profile", None)
    try:
        return [d for d in json.loads(getattr(profile, "directors", None) or "[]") if d] if profile else []
    except ValueError:
        return []


def add_director_tabs(ctx, g3, cf_cell: str) -> List[str]:
    """The tab per director after G3, and the table by director on G3. Returns the tabs made."""
    from backend.app.services.mapping.chart_lookup import account_name_keys
    from backend.app.services.workbook.balance_tabs.common import BOLD, _money
    from backend.app.services.workbook.context import DLA_TYPE_ORDER, dla_type
    groups = director_groups(ctx.tb_records, _directors(ctx.engagement))
    if not groups:
        return []
    wb = ctx.wb
    made: List[str] = []
    summary = []
    order = sorted(groups, key=lambda g: (g == NOT_NAMED, g))
    position = wb.sheetnames.index(g3.title) + 1
    for n, director in enumerate(order, start=1):
        names = groups[director]
        keys = set().union(*(account_name_keys(a) for a in names))
        recs = [t for t in ctx.tb_records if t.raw_account_name in names]
        closing = round(sum(float(t.net_amount or 0) for t in recs), 2)
        lines = sorted((tx for tx in ctx.tx_rows if tx[1] in {str(c) for c in DLA_CODES}
                        and any(k in keys for k in account_name_keys(tx[3]))),
                       key=lambda tx: (tx[0][6:], tx[0][3:5], tx[0][:2]))
        movement = round(sum(float(tx[7] or 0) - float(tx[8] or 0) for tx in lines), 2)
        opening = round(sum(float(t.opening_amount or 0) for t in recs), 2) if any(
            t.opening_amount is not None for t in recs) else round(closing - movement, 2)
        title = f"G3.D{n} - DLA {director}"[:31]          # G3.D1, G3.D2 ... (G3.1 / G3.2 are taken)
        ws = wb.create_sheet(title, position)
        position += 1
        made.append(title)
        ws["A1"], ws["A2"] = ctx.client_name, ctx.ye_str
        ws["A3"] = f"Director's loan account: {director}"
        ws["A3"].font = BOLD
        ws["A4"] = "Accounts: " + "; ".join(sorted(names))[:250]
        ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 14, 46
        for col in "DEF":
            ws.column_dimensions[col].width = 15
        # The T-account (debit + = owed by the director, as the ETB)
        ws.cell(row=6, column=2, value="Balance b/fwd (debit = overdrawn)")
        _money(ws.cell(row=6, column=4)).value = opening
        r = 7
        by_type: Dict[str, float] = {}
        for tx in lines:
            by_type[dla_type(tx)] = by_type.get(dla_type(tx), 0.0) + float(tx[7] or 0) - float(tx[8] or 0)
        for label in DLA_TYPE_ORDER:
            if abs(by_type.get(label, 0.0)) >= 0.005:
                ws.cell(row=r, column=2, value=label)
                _money(ws.cell(row=r, column=4)).value = round(by_type[label], 2)
                r += 1
        ws.cell(row=r, column=2, value="Balance c/fwd").font = BOLD
        cf = f"D{r}"
        _money(ws[cf], bold=True).value = f"=SUM(D6:D{r - 1})"
        ws.cell(row=r + 1, column=2, value="Per the TB")
        _money(ws.cell(row=r + 1, column=4)).value = closing
        ws.cell(row=r + 2, column=2, value="Difference (must be nil)").font = BOLD
        _money(ws.cell(row=r + 2, column=4), bold=True).value = f"=ROUND({cf}-D{r + 1},2)"
        # The ledger with its running balance
        top = r + 5
        for c, h in enumerate(("Date", "Type", "Description", "Dr", "Cr", "Running balance"), 1):
            ws.cell(row=top, column=c, value=h).font = BOLD
        running, highest = opening, max(opening, 0.0)
        for i, tx in enumerate(lines, start=top + 1):
            dr, cr = float(tx[7] or 0), float(tx[8] or 0)
            running = round(running + dr - cr, 2)
            highest = max(highest, running)
            ws.cell(row=i, column=1, value=tx[0])
            ws.cell(row=i, column=2, value=dla_type(tx))
            ws.cell(row=i, column=3, value=str(tx[5] or tx[3])[:80])
            _money(ws.cell(row=i, column=4)).value = round(dr, 2) if dr else None
            _money(ws.cell(row=i, column=5)).value = round(cr, 2) if cr else None
            _money(ws.cell(row=i, column=6)).value = running
        ws.cell(row=top - 1, column=4, value="Highest overdrawn balance in the year")
        _money(ws.cell(row=top - 1, column=6), bold=True).value = round(highest, 2)
        summary.append((director, opening, movement, f"='{title}'!{cf}", title))
    # The lead's table by director (G3 c/fwd is owed to the directors +: the tabs are debit +)
    top = g3.max_row + 3
    g3.cell(row=top, column=1, value="By director (one tab each, debit = overdrawn)").font = BOLD
    for c, h in enumerate(("Director", "", "Balance b/fwd", "Movement", "Balance c/fwd", "Tab"), 1):
        if h:
            g3.cell(row=top + 1, column=c, value=h).font = BOLD
    for i, (director, opening, movement, cf_ref, title) in enumerate(summary, start=top + 2):
        g3.cell(row=i, column=1, value=director)
        _money(g3.cell(row=i, column=3)).value = opening
        _money(g3.cell(row=i, column=4)).value = movement
        _money(g3.cell(row=i, column=5)).value = cf_ref
        g3.cell(row=i, column=6, value=title)
    end = top + 1 + len(summary)
    total = end + 1
    g3.cell(row=total, column=1, value="Total").font = BOLD
    _money(g3.cell(row=total, column=5), bold=True).value = f"=SUM(E{top + 2}:E{end})"
    g3.cell(row=total + 1, column=1, value="Check: total less the lead's c/fwd (must be nil)").font = BOLD
    _money(g3.cell(row=total + 1, column=5), bold=True).value = f"=ROUND(E{total}+({cf_cell}),2)"
    # For the accounts each director stands alone: owed by a director is a debtor, owed to one a creditor, never set
    # off (SI 2008/409 Sch 1 para 8; s455 per director, U-DLA-010)
    rng = f"E{top + 2}:E{end}"
    g3.cell(row=total + 3, column=1, value="For the accounts (each director on their own, not set off)").font = BOLD
    g3.cell(row=total + 4, column=1, value="Owed to directors: creditors")
    _money(g3.cell(row=total + 4, column=5)).value = f'=-SUMIF({rng},"<0")'
    g3.cell(row=total + 5, column=1, value="Owed by directors (overdrawn): debtors, s455 per director")
    _money(g3.cell(row=total + 5, column=5)).value = f'=SUMIF({rng},">0")'
    return made
