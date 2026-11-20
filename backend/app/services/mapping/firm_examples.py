"""
The firm's own coding, learnt from its finished working papers: each client account name with the firm code the
accountant gave it (the TTB tab: the client's own account names; else the ETB tab). Two uses:

- examples: the AI is shown the firm's codes for accounts like the one it is coding (past_choices.py), so it follows
  the firm's habits where two codes are both defensible ('Telephone' 3290 or 3291);
- habits: a name the firm has coded the same way on several clients is given that code directly, before the general
  naming rules (it can still be changed on the Accounts tab).
"""

import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models.database import MasterCOA
from backend.app.models.firm_examples import FirmExample

HABIT_CLIENTS = 3          # a habit: the same name coded on at least this many clients...
HABIT_SHARE = 0.8          # ...with the same code at least this often
ETB_SHEETS = ("trial balance", "etb", "extended trial balance")


def name_key(name: str) -> str:
    """'3290 - Telephone & Internet' and 'Telephone & internet' are the same account name."""
    text = re.sub(r"^\s*[\d.]+\s*[-–:]?\s*", "", (name or "").strip().lower())
    # A bank or card number says which account, not what it is: 'Bank Account (6212)' and 'Bank Account (8793)' are
    # one name to the firm's habits
    text = re.sub(r"\(\s*[\d\s\-]+\)|\b\d{4,}\b|\bx{2,}\d*\b", " ", text)
    # How it is written does not change what it is: 'Bank & Cash' / 'Bank and cash', 'Fees - Legal' / 'fees legal',
    # 'Debtors' / 'Debtor'
    text = re.sub(r"[^a-z0-9]+", " ", text.replace("&", " and "))
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in text.split()]
    return " ".join(words)


NAME_HEAD = re.compile(r"^(name|account( name)?|description|discription|details|nominal name)$", re.I)
CODE_HEAD = re.compile(r"^(tc code|taxcalc code|code|final code|firm code)$", re.I)


def _client_names(ws) -> List[Tuple[str, int]]:
    """The TTB tab: each client account in its own name with the firm code given to it ('TC Code | Name', or
    'Account | Account Code | ... | Taxcalc Code' where the client's own code sits beside the firm's)."""
    rows = [list(r) for r in ws.iter_rows(max_row=700, max_col=14, values_only=True)]
    for h, head in enumerate(rows[:20]):
        cells = [str(v).strip() if isinstance(v, str) else "" for v in head]
        names = [j for j, c in enumerate(cells) if NAME_HEAD.match(c)]
        codes = [j for j, c in enumerate(cells) if CODE_HEAD.match(c)]
        if not names or not codes:
            continue
        firm = next((j for j in codes if re.match(r"^(tc|taxcalc|final|firm)", cells[j], re.I)), codes[-1])
        out = []
        for r in rows[h + 1:]:
            code = r[firm] if firm < len(r) else None
            name = r[names[0]] if names[0] < len(r) else None
            if (isinstance(code, (int, float)) and not isinstance(code, bool) and float(code).is_integer()
                    and 0 <= code < 10000 and isinstance(name, str) and name.strip()
                    and not re.match(r"^(total|net movement)", name.strip(), re.I)):
                out.append((name.strip(), int(code)))
        if len(out) >= 5:
            return out
    return []


def from_working_papers(path: str) -> List[Tuple[str, int]]:
    """(account name, firm code) for every account on a working paper: from its TTB tab, where each of the client's
    own accounts stands beside the firm code given to it (the names a new client's books will have); else the ETB tab,
    which mostly shows the chart's own names."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for tab in [s for s in wb.sheetnames if re.search(r"ttb", s, re.I)]:
        got = _client_names(wb[tab])
        if got:
            return got
    sheet = next((s for s in wb.sheetnames if s.strip().lower() in ETB_SHEETS), None)
    if sheet is None:
        return []
    rows = [list(r) for r in wb[sheet].iter_rows(max_row=600, values_only=True)]
    for h, row in enumerate(rows[:25]):
        cells = [str(v).strip().lower() if v is not None else "" for v in row]
        if "code" not in cells:
            continue
        code_col = cells.index("code")
        name_col = next((j for j, c in enumerate(cells) if j != code_col and re.search(r"name|account|description", c)), None)
        if name_col is None:
            return []
        out = []
        for r in rows[h + 1:]:
            code = r[code_col] if code_col < len(r) else None
            name = r[name_col] if name_col < len(r) else None
            if isinstance(code, (int, float)) and isinstance(name, str) and name.strip():
                out.append((name.strip(), int(code)))
        return out
    return []


def load(db: Session, client: str, examples: List[Tuple[str, int]], owner_user_id: Optional[int] = None) -> int:
    """The client's examples, replacing any loaded before for it. Codes not in the firm chart are left out."""
    chart = {c for (c,) in db.execute(select(MasterCOA.std_code))}
    db.execute(delete(FirmExample).where(FirmExample.client == client))
    kept = [(n, c) for n, c in examples if c in chart and name_key(n)]
    for name, code in kept:
        db.add(FirmExample(owner_user_id=owner_user_id, account_name=name[:255], std_code=code, client=client))
    db.commit()
    return len(kept)


def all_examples(db: Session) -> List[Tuple[str, int]]:
    return [(n, c) for n, c in db.execute(select(FirmExample.account_name, FirmExample.std_code))]


def habits(db: Session) -> Dict[str, Tuple[int, int]]:
    """{name key: (code, clients)} for names the firm codes the same way on several clients."""
    votes: Dict[str, Dict[str, int]] = defaultdict(dict)      # name key -> {client: code} (one vote per client)
    for name, code, client in db.execute(select(FirmExample.account_name, FirmExample.std_code, FirmExample.client)):
        key = name_key(name)
        if key:
            votes[key][client or ""] = code
    out = {}
    for key, per_client in votes.items():
        if len(per_client) < HABIT_CLIENTS:
            continue
        code, n = Counter(per_client.values()).most_common(1)[0]
        if n / len(per_client) >= HABIT_SHARE:
            out[key] = (code, n)
    return out
