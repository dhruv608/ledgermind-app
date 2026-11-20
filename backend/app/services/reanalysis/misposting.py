"""
Misposting review: a supplier or customer whose ledger lines sit
in more than one profit and loss account. Found by behaviour, not by reading the narration: when one merchant has many
lines in one account and a few in another, the few are probably posted to the wrong account (Gatwick Airport: 46 lines
in travel, 3 in purchases). Each merchant is shown once, with its lines per account; the minority lines are the
suggested move to the merchant's main account.

Recommended (shown first) only when the main account clearly dominates; a merchant that sells many kinds of thing
(a marketplace, a supermarket, a payment platform) or an even split stays under All, since buying different things
from one place is normal. Payroll, VAT, bank and the tax charge are other modules' lines and are never looked at.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from backend.app.services.reanalysis.engine import AMBIGUOUS, GENERIC_MERCHANTS, OWNED_ELSEWHERE
from backend.app.services.reanalysis.merchants import merchant_of

# The main account needs at least this many lines, and the minority at most this share of the main account's lines
MAIN_LINES = 3
MINORITY_SHARE = 0.25
# P&L accounts only (the chart's financial class); suspense is a balance sheet code but its lines are mispostings too
PL_CLASS = "Profit and Loss"
SUSPENSE = 9999


@dataclass
class Line:
    key: str                  # the ledger line's id, to move it
    when: Optional[date]
    code: int
    account: str              # the client's own account name
    amount: float             # debit positive, credit negative
    description: str


@dataclass
class Split:
    merchant: str
    merchant_key: str
    category: Optional[str]
    main_code: int
    accounts: Dict[int, List[Line]] = field(default_factory=dict)
    recommended: bool = False
    reason: str = ""

    def minority(self) -> List[Line]:
        return [l for code, lines in self.accounts.items() if code != self.main_code for l in lines]


# Income accounts: a merchant the client both sells to and buys from (Vinted sales and Vinted fees) is normal, so
# only costs are compared with costs
INCOME = {"Sales", "Other operating income", "Interest receivable and similar income", "Income from shares in group undertakings",
          "Income from other fixed asset investments", "Income from other current asset investments", "Income from participating interests"}


def _looked_at(line: "Line", chart: Dict[int, dict]) -> bool:
    """A cost line (a debit on a P&L cost account), or a payment left in suspense."""
    if line.code in OWNED_ELSEWHERE or line.amount <= 0:
        return False
    if line.code == SUSPENSE:
        return True
    acc = chart.get(line.code) or {}
    return acc.get("financial_class") == PL_CLASS and acc.get("category") not in INCOME


def splits(lines: Iterable[Line], chart: Dict[int, dict]) -> List[Split]:
    """Every merchant whose lines sit in two or more P&L accounts, biggest first."""
    by_merchant: Dict[str, Dict[int, List[Line]]] = defaultdict(lambda: defaultdict(list))
    names: Dict[str, tuple] = {}
    for l in lines:
        if not _looked_at(l, chart):
            continue
        m = merchant_of(l.description or "")
        key = m.key or ""
        if len(key) < 3 or key in GENERIC_MERCHANTS:
            continue
        by_merchant[key][l.code].append(l)
        names.setdefault(key, (m.name, m.category))
    out = []
    for key, accounts in by_merchant.items():
        if len(accounts) < 2:
            continue
        # The main account: most lines, then the larger total
        main = max(accounts, key=lambda c: (len(accounts[c]), sum(abs(l.amount) for l in accounts[c])))
        name, category = names[key]
        s = Split(name, key, category, main, dict(accounts))
        n_main = len(accounts[main])
        n_rest = sum(len(v) for c, v in accounts.items() if c != main)
        if category in AMBIGUOUS:
            s.reason = f"{name} sells many kinds of thing, so lines in different accounts can be right"
        elif main == SUSPENSE:
            s.reason = "Most of this merchant's lines are in suspense"
        elif n_main < MAIN_LINES:
            s.reason = "Too few lines to say which account is usual"
        elif n_rest > MINORITY_SHARE * n_main:
            s.reason = "The lines are spread across the accounts: check whether each is right"
        else:
            s.recommended = True
            s.reason = (f"{n_main} lines in {chart.get(main, {}).get('std_name', main)}, {n_rest} elsewhere: "
                        f"the {n_rest} look misposted")
        out.append(s)
    out.sort(key=lambda s: (not s.recommended, -sum(abs(l.amount) for l in s.minority())))
    return out


# --- The screen: every split merchant, the accountant's moves and ignores (kept on the file) -------------------------
# Every split is highlighted, whatever the amount; the accountant decides. Nothing is moved
# without a remark, and nothing here raises a review point or proposes a journal by itself.

KEY_PREFIX = "misposting:"


def _line_keys(gl) -> List[str]:
    """A key per ledger line that stays the same while the ledger does (identical lines numbered in turn)."""
    seen: Dict[str, int] = {}
    out = []
    for l in gl:
        text = f"{l.when}|{l.code}|{l.account}|{l.debit:.2f}|{l.credit:.2f}|{l.description}"
        base = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return out


def _decisions(db, engagement_id: str) -> Dict[str, dict]:
    from backend.app.models.raw_books import RawBooksChoice
    rows = db.query(RawBooksChoice).filter(RawBooksChoice.engagement_id == str(engagement_id),
                                           RawBooksChoice.key.like(f"{KEY_PREFIX}%")).all()
    return {r.key[len(KEY_PREFIX):]: json.loads(r.value) for r in rows}


def _save(db, engagement_id: str, merchant_key: str, value: Optional[dict], user_id: Optional[int]) -> None:
    from backend.app.models.raw_books import RawBooksChoice
    row = db.query(RawBooksChoice).filter(RawBooksChoice.engagement_id == str(engagement_id),
                                          RawBooksChoice.key == KEY_PREFIX + merchant_key).first()
    if value is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(RawBooksChoice(engagement_id=str(engagement_id), key=KEY_PREFIX + merchant_key, value=json.dumps(value),
                              user_id=user_id))
    else:
        row.value = json.dumps(value)


def _found(engagement, db):
    from backend.app.models.database import TBRecord
    from backend.app.services.reanalysis.run import _chart
    from backend.app.services.sop.common import gl_lines
    chart = _chart(db)
    tb = db.query(TBRecord).filter(TBRecord.engagement_id == engagement.id).all()
    gl = gl_lines(str(engagement.id), tb, db)
    lines = [Line(k, l.when, l.code, l.account, round(l.debit - l.credit, 2), l.description or l.account or "")
             for k, l in zip(_line_keys(gl), gl)]
    return chart, splits(lines, chart)


def review(engagement, db) -> dict:
    """Every merchant split across P&L accounts, with its lines per account, what was moved or ignored, and counts for
    the Recommended / Ignored / All tabs."""
    chart, found = _found(engagement, db)
    decided = _decisions(db, engagement.id)
    groups = []
    for s in found:
        d = decided.get(s.merchant_key) or {}
        moved = {k: m["to"] for m in d.get("moves", []) for k in m["lines"]}
        accounts = []
        for code, lines in sorted(s.accounts.items(), key=lambda kv: (kv[0] != s.main_code, -len(kv[1]))):
            accounts.append({
                "code": code, "name": chart.get(code, {}).get("std_name", ""), "main": code == s.main_code,
                "count": len(lines), "total": round(sum(l.amount for l in lines), 2),
                "lines": [{"key": l.key, "date": l.when.isoformat() if l.when else None, "description": l.description,
                           "account": l.account, "amount": l.amount, "moved_to": moved.get(l.key)} for l in lines],
            })
        left = [l for l in s.minority() if l.key not in moved]
        status = ("IGNORED" if d.get("ignored") else "MOVED" if d.get("moves") and not left
                  else "PART" if d.get("moves") else "OPEN")
        groups.append({
            "key": s.merchant_key, "merchant": s.merchant, "category": s.category, "recommended": s.recommended,
            "reason": s.reason, "main_code": s.main_code, "main_name": chart.get(s.main_code, {}).get("std_name", ""),
            "accounts": accounts, "minority_lines": len(s.minority()),
            "minority_total": round(sum(l.amount for l in s.minority()), 2), "left": len(left),
            "moves": d.get("moves", []), "ignored": d.get("ignored"), "status": status,
        })
    open_ = [g for g in groups if g["status"] in ("OPEN", "PART")]
    return {"groups": groups, "summary": {
        "recommended": sum(1 for g in open_ if g["recommended"]), "open": len(open_),
        "ignored": sum(1 for g in groups if g["status"] == "IGNORED"),
        "moved": sum(1 for g in groups if g["status"] == "MOVED"), "all": len(groups)}}


def decide(engagement, db, merchant_key: str, action: str, user_id: Optional[int], line_keys: Optional[List[str]] = None,
           to_code: Optional[int] = None, remark: str = "") -> dict:
    """MOVE the ticked lines to another account (one journal per account they leave, a remark required), IGNORE the
    merchant (kept on the file, with the reason), or UNDO every move and ignore on it (its journals deleted)."""
    from backend.app.models.database import JournalLine, ProposedJournal
    from backend.app.services.shared.activity import mark_changed
    from backend.app.services.reanalysis.memory import record
    chart, found = _found(engagement, db)
    s = next((x for x in found if x.merchant_key == merchant_key), None)
    decided = _decisions(db, engagement.id).get(merchant_key) or {}
    remark = (remark or "").strip()
    now = datetime.utcnow()
    if action == "UNDO":
        for m in decided.get("moves", []):
            for jid in m.get("journals", []):
                j = db.get(ProposedJournal, jid)
                if j is not None and j.engagement_id == engagement.id and j.source == "MISPOSTING":
                    db.query(JournalLine).filter(JournalLine.journal_id == j.id).delete()
                    db.delete(j)
        _save(db, engagement.id, merchant_key, None, user_id)
    elif s is None:
        raise ValueError("That supplier is no longer split across accounts")
    elif action == "IGNORE":
        decided["ignored"] = {"remark": remark, "by": user_id, "at": now.isoformat()}
        _save(db, engagement.id, merchant_key, decided, user_id)
    elif action == "MOVE":
        if not remark:
            raise ValueError("Write why the lines are moved: the remark is kept with the journal")
        if to_code is None or int(to_code) not in chart:
            raise ValueError("Choose the account to move them to")
        to_code = int(to_code)
        moved = {k for m in decided.get("moves", []) for k in m["lines"]}
        by_key = {l.key: l for lines in s.accounts.values() for l in lines}
        picked = [by_key[k] for k in (line_keys or []) if k in by_key and k not in moved and by_key[k].code != to_code]
        if not picked:
            raise ValueError("Tick the lines to move (not already moved, not already on that account)")
        refs = [r[0] for r in db.query(ProposedJournal.journal_ref).filter(ProposedJournal.engagement_id == engagement.id)]
        n = 1 + max((int(r[2:]) for r in refs if r and r.startswith("AJ") and r[2:].isdigit()), default=0)
        name = lambda c: chart.get(c, {}).get("std_name", str(c))
        journals = []
        by_code: Dict[int, List[Line]] = defaultdict(list)
        for l in picked:
            by_code[l.code].append(l)
        # One journal per account the lines leave, approved: the accountant's own decision
        for frm, lines in sorted(by_code.items()):
            total = round(sum(l.amount for l in lines), 2)
            dr, cr = (to_code, frm) if total >= 0 else (frm, to_code)
            j = ProposedJournal(
                engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{n:02d}",
                description=(f"Misposting: {s.merchant} ({len(lines)} line{'s' if len(lines) != 1 else ''}) moved from "
                             f"{name(frm)} to {name(to_code)}: {remark}")[:255],
                debit_code=dr, debit_name=name(dr), credit_code=cr, credit_name=name(cr),
                amount=abs(total), status="APPROVED", source="MISPOSTING", posted_at=now)
            # Never the same journal approved twice (journal_guard): an approved twin is kept
            from backend.app.services.review.journal_guard import approved_twin
            twin = approved_twin(db, j)
            if twin is not None:
                journals.append(twin.id)
                continue
            db.add(j)
            db.flush()
            journals.append(j.id)
            n += 1
        decided.setdefault("moves", []).append({"lines": [l.key for l in picked], "to": to_code, "remark": remark,
                                                "journals": journals, "by": user_id, "at": now.isoformat(),
                                                "total": round(sum(l.amount for l in picked), 2)})
        decided.pop("ignored", None)
        _save(db, engagement.id, merchant_key, decided, user_id)
        db.commit()
        record(db, engagement, merchant_key, to_code, "APPROVED", "misposting", user_id)
    else:
        raise ValueError("Move, ignore or undo")
    db.commit()
    mark_changed(db, engagement.id)
    return review(engagement, db)
