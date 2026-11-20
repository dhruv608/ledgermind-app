"""GL scrutiny: the accountant reads the ledger one firm code at a time and decides, line by line, that a line is fine
where it is (OK) or belongs to another code (MOVED: a proposed journal moves it). The decisions are kept in
gl_line_reviews by each line's content key, so they survive the books being uploaded again."""

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, GLTransaction, MasterCOA, ProposedJournal, TBRecord
from backend.app.models.gl_line_reviews import GLLineReview
from backend.app.services.mapping.chart_lookup import ChartLookup

NOT_MATCHED = "none"     # the code key of ledger lines whose account matches no TB account


@dataclass
class Line:
    key: str
    tx: GLTransaction
    code: Optional[int]


def _money(v: Any) -> float:
    return round(float(v or 0.0), 2)


def line_keys(rows: Iterable[GLTransaction]) -> List[str]:
    """A key per ledger line from its own content; the same line twice (same day, text and amount) gets #1, #2."""
    seen: Dict[str, int] = {}
    keys = []
    for tx in rows:
        base = "|".join([(tx.raw_account_name or "").strip().lower(), str(tx.transaction_date or ""),
                         (tx.description or "").strip().lower(), (tx.reference or "").strip().lower(),
                         f"{_money(tx.debit_amount):.2f}", f"{_money(tx.credit_amount):.2f}"])
        seen[base] = seen.get(base, 0) + 1
        keys.append(hashlib.sha1(f"{base}#{seen[base]}".encode("utf-8")).hexdigest())
    return keys


def _ledger(engagement: ClientEngagement, db: Session) -> List[Line]:
    """Every ledger line of the job with the firm code its account is mapped to (None: no TB account matches)."""
    from backend.app.services.sop.common import code_matcher, ledger_rows
    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))
    rows = sorted(ledger_rows(str(engagement.id), db), key=lambda tx: tx.id)
    return [Line(key, tx, code_of(tx.raw_account_name)) for key, tx in zip(line_keys(rows), rows)]


def _decisions(engagement: ClientEngagement, db: Session) -> Dict[str, Dict[str, Any]]:
    """Each decided line's state. A move counts only while its journal is there and not rejected; a question to the
    client is kept beside either (status None: only asked)."""
    reviews = list(db.execute(select(GLLineReview).where(GLLineReview.engagement_id == engagement.id)).scalars())
    journal_ids = [r.journal_id for r in reviews if r.journal_id]
    journals = {j.id: j for j in db.execute(select(ProposedJournal).where(ProposedJournal.id.in_(journal_ids))).scalars()} \
        if journal_ids else {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in reviews:
        d: Dict[str, Any] = {"status": None}
        if r.status == "OK":
            d = {"status": "OK"}
        elif r.status == "MOVED":
            j = journals.get(r.journal_id)
            if j is not None:            # its journal was deleted: the line is unchecked again
                d = {"status": "MOVE_REJECTED" if j.status == "REJECTED" else "MOVED", "to_code": r.to_code,
                     "journal_id": j.id, "journal_ref": j.journal_ref, "journal_status": j.status}
        if r.question:
            d["question"] = r.question
        if d["status"] is not None or r.question:
            out[r.line_key] = d
    return out


def _checked(d: Optional[Dict[str, Any]]) -> bool:
    return bool(d) and d["status"] in ("OK", "MOVED")


ROUND_SUM_MIN = 1000.0       # a P&L line of at least this, in whole hundreds, is a round sum
OPPOSITE_SIDE_MIN = 50.0     # ignore small refunds and rounding on the wrong side
TAX_SECTIONS = ("Current tax", "Deferred tax")   # a tax credit is normal there


def _flags(engagement: ClientEngagement, db: Session, ledger: List[Line]) -> Dict[str, List[Dict[str, Any]]]:
    """Lines worth reading first, by line key. The review's own checks find most of them (asset words, unusual
    payments, related parties), so the screen and the review agree; a credit in an expense account (or a debit in
    sales) and a round sum are worked out here. A check that fails leaves its flags out, never the screen."""
    from backend.app.services.sop.capital import capital_review, capitalisation_limit
    from backend.app.services.sop.common import supplier_name
    from backend.app.services.sop.pattern import pattern_review
    from backend.app.services.sop.related_party import related_party_review

    def match_key(when, account, description, amount) -> tuple:
        return (when, (account or "").strip().lower(), (description or "").strip(), round(abs(float(amount or 0)), 2))

    by_match: Dict[tuple, List[str]] = {}
    for ln in ledger:
        tx = ln.tx
        if tx.transaction_date:
            by_match.setdefault(match_key(tx.transaction_date, tx.raw_account_name, tx.description, tx.net_amount),
                                []).append(ln.key)
    out: Dict[str, List[Dict[str, Any]]] = {}

    def add(keys: Iterable[str], kind: str, label: str, text: str, **extra: Any) -> None:
        for k in keys:
            have = out.setdefault(k, [])
            if all(f["kind"] != kind for f in have):
                have.append({"kind": kind, "label": label, "text": text, **extra})

    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    job = str(engagement.id)
    try:
        for f in capital_review(job, tb_records, db, capitalisation_limit(engagement)):
            words = ", ".join(f.keywords)
            add(by_match.get(match_key(f.when, f.account, f.description, f.amount), []), "asset", "Maybe an asset",
                f"Asset words: {words}{' (in the supplier name only)' if f.supplier_only else ''}. A fixed asset "
                f"(lasting more than a year) or a running cost?", suggested_code=f.suggested_code)
    except Exception:
        pass
    try:
        for f in pattern_review(job, engagement.period_end_date, tb_records, db):
            if f.when is not None:
                add(by_match.get(match_key(f.when, f.account, f.description, f.amount), []), "unusual", "Unusual",
                    " ".join(f.reasons))
    except Exception:
        pass
    try:
        for s in related_party_review(engagement, tb_records, db):
            if s.party.source == "Account name":       # every line of the director's own account: not a flag
                continue
            for l in s.lines:
                add(by_match.get(match_key(l.when, l.account, l.description, l.amount), []), "related",
                    "Related party", f"Names {l.party} ({l.match.lower()}).")
    except Exception:
        pass

    chart = ChartLookup(db)
    repeats: Counter = Counter((ln.code, supplier_name(ln.tx.description or ""), round(abs(float(ln.tx.net_amount or 0)), 2))
                               for ln in ledger)
    for ln in ledger:
        if ln.code is None or not chart.is_pl(ln.code):
            continue
        net = float(ln.tx.net_amount or 0.0)
        section = chart.section(ln.code) or ""
        income = chart.is_sales(ln.code) or "income" in section.lower()
        if income and net >= OPPOSITE_SIDE_MIN:
            add([ln.key], "side", "Opposite side", "A debit in an income account: a refund to a customer, or posted "
                                                   "to the wrong account?")
        elif not income and section not in TAX_SECTIONS and net <= -OPPOSITE_SIDE_MIN:
            add([ln.key], "side", "Opposite side", "A credit in a cost account: a refund or credit note, or posted "
                                                   "to the wrong account?")
        # A round cost paid once or twice (the same round fee every month is a regular charge, not a question)
        if not income and abs(net) >= ROUND_SUM_MIN and round(abs(net), 2) % 100 == 0 \
                and repeats[(ln.code, supplier_name(ln.tx.description or ""), round(abs(net), 2))] <= 2:
            add([ln.key], "round", "Round sum", "An exact round amount paid once: an estimate or a transfer? Check "
                                                "the invoice.")
    return out


def accounts(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.sop.common import ledger_read_once
    with ledger_read_once():
        return _accounts(engagement, db)


def _accounts(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    """The account list: each code with ledger lines, its total and how many lines are checked / moved / asked, and
    how many flagged lines are still to check."""
    chart = ChartLookup(db)
    decided = _decisions(engagement, db)
    ledger = _ledger(engagement, db)
    flags = _flags(engagement, db, ledger)
    groups: Dict[Optional[int], Dict[str, Any]] = {}
    for ln in ledger:
        g = groups.setdefault(ln.code, {"lines": 0, "checked": 0, "moved": 0, "asked": 0, "flagged": 0, "total": 0.0,
                                        "accounts": []})
        g["lines"] += 1
        g["total"] += float(ln.tx.net_amount or 0.0)
        d = decided.get(ln.key)
        g["checked"] += _checked(d)
        g["moved"] += bool(d) and d["status"] == "MOVED"
        g["asked"] += bool(d) and bool(d.get("question"))
        g["flagged"] += ln.key in flags and not _checked(d)
        name = (ln.tx.raw_account_name or "").strip()
        if name and name not in g["accounts"]:
            g["accounts"].append(name)
    rows = []
    for code in sorted(groups, key=lambda c: (c is None, c or 0)):
        g = groups[code]
        rows.append({
            "code": code,
            "key": NOT_MATCHED if code is None else str(code),
            "name": "Not matched to an account" if code is None else chart.name(code, f"Account {code}"),
            "pl": bool(code is not None and chart.is_pl(code)),
            "accounts": g["accounts"][:5],
            "lines": g["lines"], "checked": g["checked"], "moved": g["moved"], "asked": g["asked"],
            "flagged": g["flagged"], "total": round(g["total"], 2),
        })
    return {"accounts": rows, "lines": sum(r["lines"] for r in rows), "checked": sum(r["checked"] for r in rows),
            "flagged": sum(r["flagged"] for r in rows)}


def lines(engagement: ClientEngagement, db: Session, code_key: str) -> Dict[str, Any]:
    from backend.app.services.sop.common import ledger_read_once
    with ledger_read_once():
        return _lines(engagement, db, code_key)


def _lines(engagement: ClientEngagement, db: Session, code_key: str) -> Dict[str, Any]:
    """One code's ledger lines, oldest first, each with its decision and its flags."""
    want = None if code_key == NOT_MATCHED else int(code_key)
    chart = ChartLookup(db)
    decided = _decisions(engagement, db)
    ledger = _ledger(engagement, db)
    flags = _flags(engagement, db, ledger)
    picked = [ln for ln in ledger if ln.code == want]
    picked.sort(key=lambda ln: (ln.tx.transaction_date is None, ln.tx.transaction_date or "", ln.tx.id))
    out = []
    for ln in picked:
        tx, d = ln.tx, decided.get(ln.key)
        if d and d.get("to_code") is not None:
            d = {**d, "to_name": chart.name(d["to_code"], f"Account {d['to_code']}")}
        out.append({
            "key": ln.key,
            "date": tx.transaction_date.isoformat() if tx.transaction_date else None,
            "account": tx.raw_account_name or "",
            "description": tx.description or "",
            "reference": tx.reference or "",
            "source": tx.source or "",
            "debit": _money(tx.debit_amount), "credit": _money(tx.credit_amount), "net": _money(tx.net_amount),
            "vat": None if tx.vat_amount is None else _money(tx.vat_amount),
            "label": tx.tracking or "",          # QuickBooks class / location, Xero tracking
            "decision": d,
            "flags": flags.get(ln.key, []),
        })
    return {"code": want, "key": code_key,
            "name": "Not matched to an account" if want is None else chart.name(want, f"Account {want}"),
            "lines": out}


def _review(db: Session, engagement: ClientEngagement, key: str) -> Optional[GLLineReview]:
    return db.execute(select(GLLineReview).where(GLLineReview.engagement_id == engagement.id,
                                                 GLLineReview.line_key == key)).scalar_one_or_none()


def set_ok(engagement: ClientEngagement, db: Session, keys: List[str], ok: bool, user_id: Optional[int]) -> int:
    """Marks lines OK (or takes the OK off). A moved line keeps its move: undo the move first. A line whose move was
    rejected (or whose journal was deleted) can be marked OK."""
    known = {ln.key for ln in _ledger(engagement, db)}
    decided = _decisions(engagement, db)
    changed = 0
    for key in dict.fromkeys(keys):
        if key not in known or (decided.get(key) or {}).get("status") == "MOVED":
            continue
        r = _review(db, engagement, key)
        if ok and (r is None or r.status != "OK"):
            if r is None:
                r = GLLineReview(engagement_id=engagement.id, line_key=key)
                db.add(r)
            r.status, r.to_code, r.journal_id, r.user_id = "OK", None, None, user_id
            changed += 1
        elif not ok and r is not None and r.status == "OK":
            _drop_status(db, r)
            changed += 1
    db.commit()
    return changed


def move(engagement: ClientEngagement, db: Session, key: str, to_code: int, user_id: Optional[int]) -> Dict[str, Any]:
    """Proposes a journal moving one line from its code to another; the line shows as moved until the journal is
    deleted or rejected. Raises ValueError with a message for the screen."""
    from backend.app.api.endpoints.audit import add_manual_journal
    from backend.app.models.schemas import ManualJournalCreateRequest, ManualJournalLineInput

    ln = next((x for x in _ledger(engagement, db) if x.key == key), None)
    if ln is None:
        raise ValueError("This ledger line is no longer in the books")
    if ln.code is None:
        raise ValueError("This line's account has no code yet: give the account a code on the Accounts tab first")
    if to_code == ln.code:
        raise ValueError("The line is already on that code")
    if not db.execute(select(MasterCOA.std_code).where(MasterCOA.std_code == to_code)).first():
        raise ValueError(f"Code {to_code} is not in the firm chart")
    current = _decisions(engagement, db).get(key)
    if current and current["status"] == "MOVED":
        raise ValueError(f"Already moved by journal {current['journal_ref']}: undo that first")
    amount = abs(float(ln.tx.net_amount or 0.0))
    if amount < 0.005:
        raise ValueError("The line has no amount to move")
    tx = ln.tx
    when = tx.transaction_date.strftime("%d/%m/%Y") if tx.transaction_date else "undated"
    text = (tx.description or tx.reference or "ledger line").strip()
    # A debit line moves as Dr new code / Cr old code; a credit line the other way round
    debit_side = float(tx.net_amount or 0.0) > 0
    narrative = f"{when} {text}"[:200]
    lines_in = [ManualJournalLineInput(account_code=to_code if debit_side else ln.code, narrative=narrative, debit=amount),
                ManualJournalLineInput(account_code=ln.code if debit_side else to_code, narrative=narrative, credit=amount)]
    description = f"GL scrutiny: {when} {text[:80]} £{amount:,.2f} moved from {ln.code} to {to_code}"[:255]
    journal = add_manual_journal(db, str(engagement.id), ManualJournalCreateRequest(description=description, lines=lines_in))
    r = _review(db, engagement, key)
    if r is None:
        r = GLLineReview(engagement_id=engagement.id, line_key=key)
        db.add(r)
    r.status, r.to_code, r.journal_id, r.user_id = "MOVED", to_code, journal.id, user_id
    db.commit()
    return {"journal_id": journal.id, "journal_ref": journal.journal_ref}


def undo_move(engagement: ClientEngagement, db: Session, key: str) -> None:
    """Takes a move back: deletes its journal (only while not approved) and the line is unchecked again."""
    r = _review(db, engagement, key)
    if r is None or r.status != "MOVED":
        raise ValueError("This line was not moved")
    j = db.get(ProposedJournal, r.journal_id) if r.journal_id else None
    if j is not None and j.status == "APPROVED":
        raise ValueError(f"Journal {j.journal_ref} is approved: reject it on the Journals tab first")
    if j is not None:
        db.delete(j)
    _drop_status(db, r)
    db.commit()


def _drop_status(db: Session, r: GLLineReview) -> None:
    """Takes the OK or the move off a line; the row stays while the line has a question to the client."""
    if r.question:
        r.status, r.to_code, r.journal_id = None, None, None
    else:
        db.delete(r)


def ask(engagement: ClientEngagement, db: Session, key: str, question: str, user_id: Optional[int]) -> None:
    """Saves a question to the client about one line (a query on the Queries tab); an empty question takes it off."""
    from datetime import datetime
    chart = ChartLookup(db)
    ln = next((x for x in _ledger(engagement, db) if x.key == key), None)
    if ln is None:
        raise ValueError("This ledger line is no longer in the books")
    question = (question or "").strip()
    r = _review(db, engagement, key)
    if not question:
        if r is not None:
            r.question = None
            if not r.status:
                db.delete(r)
            # Its query goes with it: asked again later, it starts unanswered
            from backend.app.models.queries import JobQuery
            db.execute(delete(JobQuery).where(JobQuery.engagement_id == str(engagement.id),
                                              JobQuery.key == f"gl:{key}"))
            db.commit()
        return
    if r is None:
        r = GLLineReview(engagement_id=engagement.id, line_key=key)
        db.add(r)
    tx = ln.tx
    when = tx.transaction_date.strftime("%d/%m/%Y") if tx.transaction_date else "Undated"
    where = "no code yet" if ln.code is None else f"{ln.code} {chart.name(ln.code, '')}".strip()
    r.line_label = f"{when} {(tx.description or tx.reference or 'ledger line').strip()} ({where})"[:300]
    r.amount = round(float(tx.net_amount or 0.0), 2)
    r.question, r.asked_at, r.user_id = question[:2000], datetime.utcnow(), user_id
    db.commit()


def delete_for(db: Session, engagement_ids: List[str]) -> None:
    db.execute(delete(GLLineReview).where(GLLineReview.engagement_id.in_(engagement_ids)))


def report(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    """Everything the workbook's GL scrutiny sheet shows: the account summary, the lines moved (the error report),
    the lines asked about (with the client's answer from the Queries tab) and the flagged lines not checked yet."""
    from backend.app.models.queries import JobQuery
    chart = ChartLookup(db)
    decided = _decisions(engagement, db)
    ledger = _ledger(engagement, db)
    flags = _flags(engagement, db, ledger)
    answers = {q.key: q for q in db.execute(select(JobQuery).where(JobQuery.engagement_id == str(engagement.id),
                                                                   JobQuery.key.like("gl:%"))).scalars()}
    moved, asked, flagged = [], [], []
    for ln in sorted(ledger, key=lambda x: (x.code is None, x.code or 0, x.tx.transaction_date is None,
                                             x.tx.transaction_date or "", x.tx.id)):
        tx, d = ln.tx, decided.get(ln.key) or {}
        row = {"date": tx.transaction_date, "description": (tx.description or tx.reference or "").strip(),
               "amount": _money(tx.net_amount), "code": ln.code,
               "account": "No code" if ln.code is None else chart.name(ln.code, f"Account {ln.code}")}
        if d.get("status") in ("MOVED", "MOVE_REJECTED"):
            moved.append({**row, "to_code": d["to_code"], "to_account": chart.name(d["to_code"], ""),
                          "journal": d["journal_ref"], "journal_status": d["journal_status"]})
        if d.get("question"):
            q = answers.get(f"gl:{ln.key}")
            asked.append({**row, "question": d["question"], "answer": (q.answer if q else "") or "",
                          "status": q.status if q else "OPEN"})
        if ln.key in flags and not _checked(d):
            flagged.append({**row, "flags": "; ".join(f"{f['label']}: {f['text']}" for f in flags[ln.key])})
    return {"accounts": accounts(engagement, db)["accounts"], "moved": moved, "asked": asked, "flagged": flagged}
