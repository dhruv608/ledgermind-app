"""
The reanalysis area of a job: every cost line of the ledger through the
engine, the moves grouped by merchant, from-code, to-code and reason, and the accountant's decision on each group.

Approving a group posts one journal for it (Dr the new code, Cr the old one, approved, source REANALYSIS so a review
re-run keeps it) and teaches the memory: this client, this merchant, this code. Rejecting teaches the opposite, and
the move is not proposed again for the client. A group is one merchant, so approving it is one decision, never a bulk
approval across merchants; moves that change profit, tax or the balance sheet are approved group by group only.
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, ProposedJournal, TBRecord
from backend.app.models.raw_books import RawBooksChoice
from backend.app.services.reanalysis.engine import WEIGHTS_VERSION, decide
from backend.app.services.reanalysis.memory import Memory, record

REASONS = {
    "R01": "Wrong expense head", "R02": "Personal or director item", "R03": "Payroll clean-up",
    "R04": "Cost of sales v overheads", "R05": "VAT wrongly claimed", "R06": "Suspense cleared",
    "R07": "Income miscoded", "R08": "Revenue item capitalised", "R09": "Business cost on the director's loan",
    "R10": "Capital item expensed", "R11": "VAT split out", "R12": "Loan or intercompany reclassified",
    "R13": "Disallowable for corporation tax",
}
SHOWN = {"propose", "journal", "accountant query", "client query"}
KEY_PREFIX = "reanalysis:"


def _chart(db: Session) -> Dict[int, dict]:
    return {c.std_code: {"std_name": c.std_name, "category": c.category, "financial_class": c.financial_class}
            for c in db.execute(select(MasterCOA)).scalars()}


def _decisions(db: Session, engagement_id: str) -> Dict[str, dict]:
    rows = db.query(RawBooksChoice).filter(RawBooksChoice.engagement_id == str(engagement_id),
                                           RawBooksChoice.key.like(f"{KEY_PREFIX}%")).all()
    return {r.key[len(KEY_PREFIX):]: json.loads(r.value) for r in rows}


def groups(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.sop.common import gl_lines
    chart = _chart(db)
    memory = Memory(engagement, db)
    tb = db.query(TBRecord).filter(TBRecord.engagement_id == engagement.id).all()
    decided = _decisions(db, engagement.id)
    found: Dict[str, dict] = {}
    unclear = scored = 0
    for line in gl_lines(str(engagement.id), tb, db):
        if line.debit <= 0:
            continue
        d = decide(line.description or line.account or "", line.code, memory, chart)
        if d is None:
            continue
        scored += 1
        if d.outcome == "unclear":
            unclear += 1
        if d.outcome not in SHOWN:
            continue
        key = f"{d.merchant.key or d.merchant.name}|{d.current}|{d.proposed}"
        g = found.setdefault(key, {
            "key": key, "merchant": d.merchant.name or (line.description or "")[:40], "category": d.merchant.category,
            "from_code": d.current, "from_name": chart.get(d.current, {}).get("std_name", ""),
            "to_code": d.proposed, "to_name": chart.get(d.proposed, {}).get("std_name", ""),
            "reason": d.reason, "reason_text": REASONS.get(d.reason, ""), "outcome": d.outcome, "band": d.band,
            "confidence": 0.0, "evidence": {k: round(v, 2) for k, v in d.evidence.items()}, "lines": [], "total": 0.0,
            "decision": (decided.get(key) or {}).get("decision"),
        })
        g["lines"].append({"date": line.when.isoformat() if line.when else None, "description": line.description or "",
                           "account": line.account, "amount": round(line.debit, 2)})
        g["total"] = round(g["total"] + line.debit, 2)
        g["confidence"] = max(g["confidence"], d.confidence)
    out = sorted(found.values(), key=lambda g: (g["decision"] is not None, g["outcome"] not in ("propose", "journal"), -g["total"]))
    open_ = [g for g in out if g["decision"] is None]
    return {
        "groups": out,
        "summary": {"moves": sum(1 for g in open_ if g["outcome"] in ("propose", "journal")),
                    "questions": sum(1 for g in open_ if g["outcome"] in ("accountant query", "client query")),
                    "decided": len(out) - len(open_), "unclear_lines": unclear, "lines_read": scored},
        "version": WEIGHTS_VERSION,
    }


def decide_group(engagement: ClientEngagement, db: Session, key: str, action: str, user_id: Optional[int]) -> dict:
    """APPROVE or REJECT one group (as listed by groups())."""
    found = next((g for g in groups(engagement, db)["groups"] if g["key"] == key), None)
    if found is None:
        raise ValueError("That move is no longer proposed")
    merchant_key = key.split("|")[0]
    chart = _chart(db)
    value: Dict[str, Any] = {"decision": "APPROVED" if action == "APPROVE" else "REJECTED", "by": user_id,
                             "at": datetime.utcnow().isoformat()}
    if action == "APPROVE":
        refs = [r[0] for r in db.query(ProposedJournal.journal_ref).filter(ProposedJournal.engagement_id == engagement.id)]
        n = 1 + max((int(r[2:]) for r in refs if r and r.startswith("AJ") and r[2:].isdigit()), default=0)
        j = ProposedJournal(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", journal_ref=f"AJ{n:02d}",
            description=f"Reanalysis {found['reason']}: {found['merchant']} ({len(found['lines'])} line"
                        f"{'s' if len(found['lines']) != 1 else ''}) moved to {found['to_name']}"[:255],
            debit_code=found["to_code"], debit_name=chart.get(found["to_code"], {}).get("std_name", ""),
            credit_code=found["from_code"], credit_name=chart.get(found["from_code"], {}).get("std_name", ""),
            amount=found["total"], status="APPROVED", source="REANALYSIS", posted_at=datetime.utcnow())
        # Never the same journal approved twice (journal_guard): an approved twin is kept
        from backend.app.services.review.journal_guard import approved_twin
        twin = approved_twin(db, j)
        if twin is not None:
            j = twin
        else:
            db.add(j)
            db.flush()
        value["journal_id"] = j.id
        record(db, engagement, merchant_key, found["to_code"], "APPROVED", "reanalysis", user_id)
    else:
        record(db, engagement, merchant_key, found["to_code"], "REJECTED", "reanalysis", user_id)
    row = db.query(RawBooksChoice).filter(RawBooksChoice.engagement_id == str(engagement.id),
                                          RawBooksChoice.key == KEY_PREFIX + key).first()
    if row is None:
        db.add(RawBooksChoice(engagement_id=str(engagement.id), key=KEY_PREFIX + key, value=json.dumps(value), user_id=user_id))
    else:
        row.value = json.dumps(value)
    db.commit()
    from backend.app.services.shared.activity import mark_changed
    mark_changed(db, engagement.id)
    return value
