"""One account's ledger in five views, the audit trail for re-analysis (Original, Current, Reclassified From,
Reclassified To, Journals):

  original   the client's own ledger lines on the code, as uploaded
  moved_out  lines moved off the code (GL scrutiny, one line at a time; the misposting review, ticked lines)
  moved_in   lines moved onto the code from other codes
  journals   every journal touching the code, with its effect on it (approved and still to decide; rejected left out)
  current    the code as the accounts show it: the original lines, less the ones moved out, plus the ones moved in, plus
             every other approved journal (a journal reaches the ETB only when an accountant approves it)

A move counts in Current only once its journal is approved; until then it shows under Moved out / in as 'to decide'.
"""

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, ProposedJournal
from backend.app.services.mapping.chart_lookup import ChartLookup


def _effect(j: ProposedJournal, code: int) -> float:
    """The journal's net effect on the code (debit +)."""
    if j.lines:
        return round(sum(float(l.debit or 0) - float(l.credit or 0) for l in j.lines if l.account_code == code), 2)
    amount = float(j.amount or 0)
    return round((amount if j.debit_code == code else 0.0) - (amount if j.credit_code == code else 0.0), 2)


def views(engagement: ClientEngagement, db: Session, code: int) -> Dict[str, Any]:
    from backend.app.services.papers import scrutiny
    from backend.app.services.reanalysis import misposting
    from backend.app.services.sop.common import ledger_read_once
    chart = ChartLookup(db)
    name = lambda c: chart.name(c, f"Account {c}")
    journals = {j.id: j for j in db.execute(select(ProposedJournal).where(
        ProposedJournal.engagement_id == engagement.id, ProposedJournal.status != "REJECTED")).scalars()}

    with ledger_read_once():
        original = scrutiny.lines(engagement, db, str(code))["lines"]
        ledger = scrutiny._ledger(engagement, db)
        decided = scrutiny._decisions(engagement, db)
        mis_chart, mis_found = misposting._found(engagement, db)
    row = lambda tx, key, c: {"key": key, "date": tx.transaction_date.isoformat() if tx.transaction_date else None,
                              "account": tx.raw_account_name or "", "description": tx.description or "",
                              "net": round(float(tx.net_amount or 0), 2), "code": c, "type": tx.source or "",
                              "vat": None if tx.vat_amount is None else round(float(tx.vat_amount), 2),
                              "label": tx.tracking or ""}

    moved_out: List[Dict[str, Any]] = []
    moved_in: List[Dict[str, Any]] = []
    move_journals = set()
    # GL scrutiny: one line at a time, each with its own journal
    for ln in ledger:
        d = decided.get(ln.key)
        if not d or d.get("status") != "MOVED":
            continue
        j = journals.get(d["journal_id"])
        if j is None:
            continue
        move_journals.add(j.id)
        entry = {**row(ln.tx, ln.key, ln.code), "to": d["to_code"], "to_name": name(d["to_code"]),
                 "from": ln.code, "from_name": name(ln.code) if ln.code is not None else "",
                 "how": "GL scrutiny", "journal_ref": j.journal_ref, "journal_status": j.status}
        if ln.code == code and d["to_code"] != code:
            moved_out.append(entry)
        elif d["to_code"] == code and ln.code != code:
            moved_in.append(entry)
    # The misposting review: ticked lines of a supplier, one journal per account they leave
    decisions = misposting._decisions(db, engagement.id)
    by_key = {l.key: l for s in mis_found for lines in s.accounts.values() for l in lines}
    for merchant_key, d in decisions.items():
        for m in d.get("moves", []):
            refs = [journals[jid] for jid in m.get("journals", []) if jid in journals]
            move_journals.update(j.id for j in refs)
            status = "APPROVED" if refs and all(j.status == "APPROVED" for j in refs) else "PROPOSED"
            for key in m["lines"]:
                l = by_key.get(key)
                if l is None:
                    continue
                entry = {"key": f"mis:{key}", "date": l.when.isoformat() if l.when else None, "account": l.account,
                         "description": l.description, "net": l.amount, "code": l.code, "to": m["to"],
                         "to_name": name(m["to"]), "from": l.code, "from_name": name(l.code), "how": "Misposting review",
                         "journal_ref": ", ".join(j.journal_ref for j in refs), "journal_status": status,
                         "remark": m.get("remark", "")}
                if l.code == code and m["to"] != code:
                    moved_out.append(entry)
                elif m["to"] == code and l.code != code:
                    moved_in.append(entry)

    touching = []
    for j in journals.values():
        effect = _effect(j, code)
        if abs(effect) >= 0.005:
            touching.append({"id": j.id, "ref": j.journal_ref, "description": j.description or "", "effect": effect,
                             "status": j.status, "source": j.source or "REVIEW", "line_move": j.id in move_journals,
                             "date": j.posted_at.date().isoformat() if j.posted_at else None})
    touching.sort(key=lambda t: (t["ref"] or ""))

    # Current: the lines as the accounts show them (approved moves and approved journals only)
    out_keys = {e["key"] for e in moved_out if e["journal_status"] == "APPROVED" and not e["key"].startswith("mis:")}
    current = []
    for l in original:
        if l["key"] in out_keys:
            continue
        current.append({"key": l["key"], "date": l["date"], "account": l["account"], "description": l["description"],
                        "net": l["net"], "note": "", "type": l.get("source", ""), "vat": l.get("vat"),
                        "label": l.get("label", "")})
    # A misposting move is one journal for its lines: the lines leave as a group (matched by date and amount)
    for e in [e for e in moved_out if e["key"].startswith("mis:") and e["journal_status"] == "APPROVED"]:
        hit = next((c for c in current if not c["note"] and c["date"] == e["date"] and abs(c["net"] - e["net"]) < 0.005
                    and c["description"] == e["description"]), None)
        if hit is not None:
            current.remove(hit)
    for e in moved_in:
        if e["journal_status"] == "APPROVED":
            current.append({"key": e["key"], "date": e["date"], "account": e["account"], "description": e["description"],
                            "net": e["net"], "note": f"moved in from {e['from']} ({e['how']}, {e['journal_ref']})",
                            "type": e.get("type", ""), "vat": e.get("vat"), "label": e.get("label", "")})
    for t in touching:
        if t["status"] == "APPROVED" and not t["line_move"]:
            current.append({"key": f"jnl:{t['id']}", "date": t["date"], "account": "", "description": t["description"],
                            "net": t["effect"], "note": f"journal {t['ref']}", "type": "Journal in the app", "vat": None,
                            "label": ""})
    current.sort(key=lambda c: (c["date"] is None, c["date"] or ""))

    total = lambda rows, f="net": round(sum(r[f] for r in rows), 2)
    approved = round(sum(t["effect"] for t in touching if t["status"] == "APPROVED"), 2)
    return {
        "code": code, "name": name(code),
        "original": original, "moved_out": moved_out, "moved_in": moved_in, "journals": touching, "current": current,
        "totals": {"original": total(original), "approved_journals": approved,
                   "current": round(total(original) + approved, 2), "current_lines": total(current),
                   "to_decide": round(sum(t["effect"] for t in touching if t["status"] == "PROPOSED"), 2)},
    }
