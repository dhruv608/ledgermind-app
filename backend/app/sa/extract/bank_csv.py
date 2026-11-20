"""A bank's transactions exported as a CSV file (online banking 'download', Mettle, Nationwide, NatWest, Lloyds) read
by code, not by a model: the header row names the columns (it may sit under a few lines about the account), so each
line's date, description, money in, money out and balance are taken as printed. The balances are then proved the same
way as a PDF statement's (statement.chain_break), in either order (exports are often newest first).

Not a bank export (no date, no description or no amount column: a sales platform's report, a list of investments)
gives no lines, and the document is left for the accountant."""

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

DATE_COL = re.compile(r"^(transaction |posting |value )?date$|^date$", re.I)
DESC_COL = re.compile(r"description|reference|narrative|details|payee|memo", re.I)
IN_COL = re.compile(r"paid in|money in|credit|deposit|receipts?$", re.I)
OUT_COL = re.compile(r"paid out|money out|debit|withdrawal|payments?$", re.I)
AMOUNT_COL = re.compile(r"^(amount|value)\b|amount in gbp|^amount", re.I)
BALANCE_COL = re.compile(r"balance", re.I)
ACCOUNT_COL = re.compile(r"account (number|no)", re.I)
DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%d-%b-%y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


def _text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _money(v: Any) -> Optional[float]:
    s = re.sub(r"[£$€\s,£]|GBP", "", str(v or ""))
    s = s.replace("�", "")
    if s in ("", "-"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    try:
        x = float(s.strip("()"))
    except ValueError:
        return None
    return round(-x if neg else x, 2)


def _day(v: str) -> Optional[str]:
    s = (v or "").strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _columns(header: List[str]) -> Optional[Dict[str, int]]:
    """Which column holds what, or None when the row is not a bank export's header."""
    col: Dict[str, int] = {}
    for i, h in enumerate(c.strip() for c in header):
        if not h:
            continue
        if "date" not in col and DATE_COL.search(h):
            col["date"] = i
        elif BALANCE_COL.search(h):
            col.setdefault("balance", i)
        elif IN_COL.search(h):
            col.setdefault("in", i)
        elif OUT_COL.search(h):
            col.setdefault("out", i)
        elif AMOUNT_COL.search(h):
            col.setdefault("amount", i)
        elif ACCOUNT_COL.search(h):
            col.setdefault("account", i)
        elif DESC_COL.search(h) and not re.search(r"tax|fee", h, re.I):     # Etsy's 'Tax Details' is not one
            col.setdefault("desc", [])
            col["desc"].append(i)
    if "date" in col and "desc" in col and (("in" in col and "out" in col) or "amount" in col):
        return col
    return None


def looks_like(text: str) -> bool:
    """A CSV whose header (in its first lines) is a bank export's."""
    rows = list(csv.reader(io.StringIO("\n".join((text or "").splitlines()[:12]))))
    return any(_columns(r) for r in rows)


def read(data: bytes, name: str = "") -> Dict[str, Any]:
    """{lines: [(date, description, in, out, balance)], account_last4, account_name}"""
    rows = list(csv.reader(io.StringIO(_text(data))))
    at, col = next(((i, c) for i, r in enumerate(rows[:15]) for c in [_columns(r)] if c), (None, None))
    out: Dict[str, Any] = {"lines": [], "account_last4": None, "account_name": None}
    if col is None:
        return out
    # The account, from a line above the header ('Account Name:, Joint FlexDirect Account ****12345'), its own column,
    # or the file's name ('12345678_20250529.csv')
    for r in rows[:at]:
        joined = " ".join(r)
        if re.search(r"account", joined, re.I):
            m = re.search(r"(\d{4})\D*$", joined)
            out["account_last4"] = out["account_last4"] or (m.group(1) if m else None)
            if len(r) > 1 and re.search(r"account name", r[0], re.I):
                out["account_name"] = re.sub(r"\*+\d+", "", r[1]).strip() or None
    lines: List[Tuple] = []
    for r in rows[at + 1:]:
        if len(r) <= col["date"]:
            continue
        on = _day(r[col["date"]])
        if not on:
            continue
        cell = lambda k: r[col[k]] if k in col and col[k] < len(r) else ""
        if "in" in col and "out" in col:
            i, o = _money(cell("in")) or 0.0, _money(cell("out")) or 0.0
        else:
            a = _money(cell("amount")) or 0.0
            i, o = (a, 0.0) if a > 0 else (0.0, -a)
        if not i and not o:
            continue
        desc = " ".join(dict.fromkeys(r[k].strip() for k in col["desc"] if k < len(r) and r[k].strip()))
        if not out["account_last4"] and "account" in col:
            m = re.search(r"(\d{4})\s*$", cell("account"))
            out["account_last4"] = m.group(1) if m else None
        lines.append((on, desc, abs(i), abs(o), _money(cell("balance")) if "balance" in col else None))
    if not out["account_last4"]:
        m = re.match(r"(\d{6,10})_", (name or "").replace("\\", "/").split("/")[-1])
        out["account_last4"] = m.group(1)[-4:] if m else None
    out["lines"] = _in_order(lines)
    return out


def _in_order(lines: List[Tuple]) -> List[Tuple]:
    """The lines as printed when their balances chain (either way); else each day's lines turned round when that makes
    them chain (NatWest exports the days in order but each day's lines newest first)."""
    from itertools import groupby
    from backend.app.sa.extract.statement import StatementLine, chain_break
    chains = lambda ls: (chain_break([StatementLine(*l) for l in ls], None) is None
                         or chain_break([StatementLine(*l) for l in ls[::-1]], None) is None)
    if not lines or chains(lines):
        return lines
    turned = [l for _, day in groupby(lines, key=lambda l: l[0]) for l in list(day)[::-1]]
    return turned if chains(turned) else lines
