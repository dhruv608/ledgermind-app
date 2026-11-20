"""C3, the GL read in full: each account in the client's ledger ends with a
total line, QuickBooks 'Total for AMEX' (Debit, Credit and Amount) and Xero 'Total Bank Fees' (Debit / Credit), the
year's movement without the opening. The lines the app saved for that account must add up to it (0.01); when they do
not, lines were missed reading the file.

QuickBooks lines are turned to the TB's side on upload (an account whose balance is a credit is flipped whole), so
the saved lines may agree with the total line with the sign reversed: that is still read in full."""

import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, GLTransaction

TOTAL = re.compile(r"^total(?:\s+for)?\s+(.+?)(\s+with sub-accounts)?$", re.I)
PENNY = 0.01


def _number(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and v != v):
        return None
    try:
        return float(str(v).replace(",", "").replace("£", "").strip())
    except ValueError:
        return None


def total_lines(raw: pd.DataFrame) -> List[Tuple[str, bool, float, Optional[float]]]:
    """(account, with sub-accounts, the year's movement debit + (Amount, else Debit - Credit), Debit - Credit) for
    each total line in the ledger file."""
    rows = raw.values.tolist()
    header = next((i for i, r in enumerate(rows[:15])
                   if {"date", "transaction date"} & {str(v).strip().lower() for v in r}
                   and any(str(v).strip().lower().startswith(("debit", "credit", "amount")) for v in r)), None)
    if header is None:
        return []
    names = [str(v).strip().lower() for v in rows[header]]
    debit = next((j for j, n in enumerate(names) if n.startswith("debit")), None)
    credit = next((j for j, n in enumerate(names) if n.startswith("credit")), None)
    amount = next((j for j, n in enumerate(names) if n == "amount"), None)
    out = []
    for r in rows[header + 1:]:
        found = next((TOTAL.match(str(v).strip()) for v in r[:3] if isinstance(v, str) and TOTAL.match(v.strip())),
                     None)
        if found is None:
            continue
        # QuickBooks gives both, and on a total line they can differ (Debit / Credit can leave out journals,
        # Amount can leave out bank feed lines): either one agreeing is a full read
        dr = _number(r[debit]) if debit is not None and debit < len(r) else None
        cr = _number(r[credit]) if credit is not None and credit < len(r) else None
        sides = round((dr or 0.0) - (cr or 0.0), 2) if dr is not None or cr is not None else None
        value = _number(r[amount]) if amount is not None and amount < len(r) else None
        value = sides if value is None else round(value, 2)
        if value is None:
            continue
        out.append((found.group(1).strip(), bool(found.group(2)), value, sides))
    return out


def gl_read_check(eng: ClientEngagement, db: Session) -> Optional[Tuple[int, List[Tuple[str, float, float]]]]:
    """(accounts checked, [(account, lines read, total line)] that differ), or None when the ledger file has no
    total lines (or is not kept)."""
    from backend.app.services.review.last_year import role_frame
    frame = role_frame(eng, "GL")
    totals = total_lines(frame[1]) if frame else []
    if not totals:
        return None
    read: Dict[str, float] = {
        name: float(net or 0.0) for name, net in db.execute(
            select(GLTransaction.raw_account_name, func.sum(GLTransaction.debit_amount - GLTransaction.credit_amount))
            .where(GLTransaction.engagement_id == eng.id).group_by(GLTransaction.raw_account_name)).all()}
    return sum(1 for t in totals if not t[1]), compare(totals, read)


def compare(totals: List[Tuple[str, bool, float, Optional[float]]],
            read: Dict[str, float]) -> List[Tuple[str, float, float]]:
    """[(account, lines read, total line)] for each total line the saved lines (by account) do not add up to."""

    def segments(name: str) -> List[str]:
        return [s.strip().lower() for s in name.split(":")]

    missed = []
    for i, (account, with_subs, total, sides) in enumerate(totals):
        if with_subs:
            # 'Total for X with sub-accounts' adds up totals checked one by one above it (and QuickBooks' own sum
            # can disagree with them): every line is already under a checked total
            continue
        key = account.lower()
        figures = [t for t in (total, sides) if t is not None]
        # A parent's total may hold its sub-accounts ('Total for Utilities' after 'Water')
        subtree = round(sum(v for n, v in read.items() if key in segments(n)), 2)
        options = [round(v, 2) for n, v in read.items() if n.lower() == key or segments(n)[-1] == key] + [subtree]
        if any(abs(o - t) <= PENNY or abs(o + t) <= PENNY for o in options for t in figures):
            continue
        # A parent's total is its sub-accounts' total lines just above it (each checked on its own), when the saved
        # names do not keep the nesting
        if any(key in segments(n)[:-1] for n in read):
            run = 0.0
            for _, _, above, _ in reversed(totals[max(0, i - 40):i]):
                run += above
                if abs(run - total) <= PENNY:
                    break
            else:
                missed.append((account, options[0], total))
            continue
        missed.append((account, options[0], total))
    return missed
