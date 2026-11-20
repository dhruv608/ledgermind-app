"""Work the assistant may prepare but never do: each tool checks what the AI asked for and gives back a card, and the
work is done only when the accountant presses Confirm on it (no module posts a journal on its own; a proposed journal
reaches the ETB only when an accountant approves it). Signing off is never offered here."""

import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, MasterCOA, ProposedJournal

AUDIENCES = ("CLIENT", "ACCOUNTANT", "INTERNAL")
AREAS = ("opening", "bank", "sales", "purchases", "payroll", "vat", "accruals", "fixed", "stock", "loans", "dla",
         "tax", "general")


def _S(desc: str) -> Dict[str, Any]:
    return {"type": "string", "description": desc}


def _N(desc: str) -> Dict[str, Any]:
    return {"type": "number", "description": desc}


def _spec(name: str, description: str, props: Dict[str, Any], required) -> Dict[str, Any]:
    return {"toolSpec": {"name": name, "description": description,
                         "inputSchema": {"json": {"type": "object", "properties": props, "required": list(required)}}}}


_POINT = _N("The point's id from review_points (only for a point on this client)")
SPECS = [
    _spec("propose_journal", "Prepare an adjusting journal for the user to confirm. It is saved as PROPOSED (not "
                             "posted) only when the user presses Confirm; an accountant then approves it on the "
                             "Journals tab. Use firm account codes the tools showed you.",
          {"description": _S("What the journal does, e.g. 'Reclass Shopify fees from sales to bank charges'"),
           "reason": _S("Why, in one line, with the figures that show it"),
           "lines": {"type": "array", "description": "Two or more lines; debits must equal credits",
                     "items": {"type": "object", "properties": {
                         "account_code": {"type": "integer", "description": "Firm account code, e.g. 3351"},
                         "debit": _N("Debit amount, or 0"), "credit": _N("Credit amount, or 0"),
                         "narrative": _S("Line text")}, "required": ["account_code"]}}},
          ["description", "reason", "lines"]),
    _spec("journal_decision", "Prepare approving or rejecting a proposed journal; done only when the user presses "
                              "Confirm (their click is the approval).",
          {"journal_ref": _S("The journal's ref, e.g. MJ02 or B3-01"), "decision": _S("APPROVE or REJECT"),
           "reason": _S("Why, in one line")}, ["journal_ref", "decision"]),
    _spec("clear_point", "Prepare clearing a review point with the reason; done only when the user presses Confirm.",
          {"point_id": _POINT, "reason": _S("Why it can be cleared: the evidence or the answer, with figures")},
          ["point_id", "reason"]),
    _spec("raise_query", "Prepare a query for the job's Queries tab (to the client, the accountant or internal); "
                         "added only when the user presses Confirm.",
          {"title": _S("The question, as it will be sent"), "detail": _S("The figures or lines it is about"),
           "audience": _S("CLIENT, ACCOUNTANT or INTERNAL"), "area": _S(f"The area: {', '.join(AREAS)}"),
           "amount": _N("The amount it is about, or 0"), "point_id": _POINT}, ["title", "audience"]),
    _spec("add_note", "Prepare a note on an area page (or on one of its points), signed with the user's name; added "
                      "only when the user presses Confirm.",
          {"area": _S(f"The area: {', '.join(AREAS)}"), "text": _S("The note"), "point_id": _POINT},
          ["area", "text"]),
]
NAMES = {s["toolSpec"]["name"] for s in SPECS}
LABELS = {"propose_journal": "Preparing a journal", "journal_decision": "Preparing a journal decision",
          "clear_point": "Preparing to clear a point", "raise_query": "Preparing a query", "add_note": "Preparing a note"}
TELL = ("A card is shown to the user with Confirm and Cancel. NOTHING has been done yet: say in one line what the card "
        "will do and ask them to check it and press Confirm. Never say it is done, saved or posted.")


def _point(db: Session, eng: ClientEngagement, point_id) -> AuditFinding:
    try:
        f = db.get(AuditFinding, int(point_id))
    except (TypeError, ValueError):
        f = None
    if f is None or str(f.engagement_id) != str(eng.id):
        raise ValueError("No point with that id on this client: read review_points for the id")
    return f


def _check(db: Session, eng: ClientEngagement, name: str, a: Dict[str, Any]) -> Dict[str, Any]:
    """The card for a request, or ValueError with what is wrong (told to the model, which may try again)."""
    if name == "propose_journal":
        chart = {c.std_code: c.std_name for c in db.execute(select(MasterCOA)).scalars().all()}
        lines = []
        for i, l in enumerate(a.get("lines") or [], start=1):
            try:
                code = int(l.get("account_code"))
                dr, cr = round(float(l.get("debit") or 0), 2), round(float(l.get("credit") or 0), 2)
            except (TypeError, ValueError):
                raise ValueError(f"Line {i}: the code and amounts must be numbers")
            if not dr and not cr:
                continue
            if dr < 0 or cr < 0 or (dr and cr):
                raise ValueError(f"Line {i}: a debit or a credit, as a positive amount")
            if code not in chart:
                raise ValueError(f"Line {i}: {code} is not in the firm's chart of accounts")
            lines.append({"account_code": code, "account_name": chart[code], "debit": dr, "credit": cr,
                          "narrative": str(l.get("narrative") or "")[:200]})
        if len(lines) < 2:
            raise ValueError("A journal needs at least two lines with an amount")
        dr, cr = round(sum(l["debit"] for l in lines), 2), round(sum(l["credit"] for l in lines), 2)
        if dr != cr:
            raise ValueError(f"It does not balance: debits £{dr:,.2f}, credits £{cr:,.2f}")
        description = str(a.get("description") or "").strip()[:300]
        if not description:
            raise ValueError("Give the journal a description")
        return {"title": "Propose a journal", "text": description, "why": str(a.get("reason") or "")[:400],
                "lines": lines, "total": dr, "payload": {"description": description, "lines": lines}}
    if name == "journal_decision":
        decision = str(a.get("decision") or "").upper()
        if decision not in ("APPROVE", "REJECT"):
            raise ValueError("decision must be APPROVE or REJECT")
        ref = str(a.get("journal_ref") or "").strip()
        j = db.execute(select(ProposedJournal).where(ProposedJournal.engagement_id == eng.id,
                                                     ProposedJournal.journal_ref == ref)).scalars().first()
        if j is None:
            raise ValueError(f"No journal {ref} on this client: read journals for the ref")
        if j.status != "PROPOSED":
            raise ValueError(f"{ref} is already {j.status.lower()}")
        lines = [{"account_code": l.account_code, "account_name": l.account_name, "debit": float(l.debit or 0),
                  "credit": float(l.credit or 0), "narrative": l.narrative or ""} for l in j.lines]
        return {"title": f"{'Approve' if decision == 'APPROVE' else 'Reject'} journal {ref}", "text": j.description,
                "why": str(a.get("reason") or "")[:400], "lines": lines, "total": float(j.amount or 0),
                "payload": {"journal_id": j.id, "decision": decision}}
    if name == "clear_point":
        f = _point(db, eng, a.get("point_id"))
        if f.status != "OPEN":
            raise ValueError(f"{f.procedure_ref} is already {f.status.lower()}")
        reason = str(a.get("reason") or "").strip()
        if len(reason) < 10:
            raise ValueError("Give the reason it can be cleared (the evidence or the answer)")
        return {"title": f"Clear point {f.procedure_ref}", "text": f.finding_title, "why": reason[:600],
                "payload": {"point_id": f.id, "reason": reason[:600]}}
    if name == "raise_query":
        title = str(a.get("title") or "").strip()
        audience = str(a.get("audience") or "CLIENT").upper()
        area = str(a.get("area") or "").lower()
        if not title:
            raise ValueError("Write the question")
        if audience not in AUDIENCES:
            raise ValueError("audience must be CLIENT, ACCOUNTANT or INTERNAL")
        if area and area not in AREAS:
            raise ValueError(f"area must be one of {', '.join(AREAS)}")
        f = _point(db, eng, a["point_id"]) if a.get("point_id") else None
        amount = round(float(a.get("amount") or 0), 2)
        return {"title": f"Raise a query ({audience.lower()})", "text": title[:300],
                "why": str(a.get("detail") or "")[:600], **({"point": f.procedure_ref} if f else {}),
                **({"total": amount} if amount else {}),
                "payload": {"title": title[:300], "detail": str(a.get("detail") or "")[:2000], "audience": audience,
                            "area": area, "amount": amount, "point_id": f.id if f else None}}
    if name == "add_note":
        area, text = str(a.get("area") or "").lower(), str(a.get("text") or "").strip()
        if area not in AREAS:
            raise ValueError(f"area must be one of {', '.join(AREAS)}")
        if not text:
            raise ValueError("Write the note")
        f = _point(db, eng, a["point_id"]) if a.get("point_id") else None
        return {"title": f"Add a note ({area})", "text": text[:2000], **({"point": f.procedure_ref} if f else {}),
                "payload": {"area": area, "text": text[:2000], "point_id": f.id if f else None}}
    raise ValueError(f"Unknown action {name}")


def prepare(db: Session, eng: ClientEngagement, name: str, args: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """(what the model is told, the card for the panel or None)."""
    try:
        card = _check(db, eng, name, args or {})
    except ValueError as e:
        return {"error": str(e)}, None
    card.update(id=uuid.uuid4().hex[:10], kind=name, status="WAITING")
    return {"ok": True, "note": TELL}, card


def run(db: Session, eng: ClientEngagement, card: Dict[str, Any], user) -> str:
    """Does the card's work for the user who pressed Confirm, checked again first (things may have changed since);
    gives back what was done, or ValueError."""
    from datetime import datetime

    from backend.app.services.shared.activity import mark_changed
    kind, p = card["kind"], card["payload"]
    if kind == "propose_journal":
        from backend.app.api.endpoints.audit import add_manual_journal
        from backend.app.models.schemas import ManualJournalCreateRequest
        _check(db, eng, kind, p | {"reason": card.get("why")})
        j = add_manual_journal(db, str(eng.id), ManualJournalCreateRequest(
            description=p["description"],
            lines=[{k: l[k] for k in ("account_code", "debit", "credit", "narrative")} for l in p["lines"]]))
        mark_changed(db, str(eng.id))
        return f"Saved as {j.journal_ref}, proposed. Approve it on the Journals tab."
    if kind == "journal_decision":
        j = db.get(ProposedJournal, p["journal_id"])
        if j is None or str(j.engagement_id) != str(eng.id) or j.status != "PROPOSED":
            raise ValueError("That journal is no longer waiting for a decision")
        if p["decision"] == "APPROVE":
            from backend.app.services.review.journal_guard import approved_twin
            twin = approved_twin(db, j)
            if twin is not None:
                raise ValueError(f"The same journal is already approved as {twin.journal_ref}: it is not posted twice")
        j.status = "APPROVED" if p["decision"] == "APPROVE" else "REJECTED"
        if j.status == "APPROVED":
            j.posted_at = datetime.utcnow()
        db.commit()
        mark_changed(db, str(eng.id))
        return f"{j.journal_ref} {j.status.lower()}."
    if kind == "clear_point":
        f = _point(db, eng, p["point_id"])
        if f.status != "OPEN":
            raise ValueError(f"{f.procedure_ref} is already {f.status.lower()}")
        f.status, f.cleared_at, f.cleared_note = "CLEARED", datetime.utcnow(), p["reason"]
        db.commit()
        return f"{f.procedure_ref} cleared."
    if kind == "raise_query":
        from backend.app.services.queries.query_list import raise_query
        raise_query(db, eng, getattr(user, "id", None), p["title"], p["detail"], p["audience"], p["area"],
                    p["amount"], p["point_id"])
        return "Added to the Queries tab."
    if kind == "add_note":
        from backend.app.api.endpoints.notes import save_note
        save_note(db, str(eng.id), p["area"], p["text"], user, finding_id=p["point_id"])
        return f"Note added on the {p['area']} page."
    raise ValueError(f"Unknown action {kind}")
