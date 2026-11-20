"""Employment lines from P45s and P11Ds."""

import json
from typing import Dict, Tuple

from sqlalchemy.orm import Session

from backend.app.sa.models import SADocument, SAJob, SALine


def sync_p45_lines(db: Session, job: SAJob) -> None:
    """An employment line for a P45 or final payslip of the year (R-SA102-01), when no P60 from the same employer (its
    PAYE reference, else its name) is on the return: a P45 before a payslip, the latest payslip of an employer."""
    from backend.app.sa.extract.pension import same_payer
    lines = db.query(SALine).filter(SALine.job_id == job.id, SALine.source == "EMPLOYMENT").all()
    have = {l.doc_id for l in lines if l.doc_id is not None}
    docs = {d.id: d for d in db.query(SADocument).filter(SADocument.job_id == job.id).all()}
    def ref_of(l):
        d = docs.get(l.doc_id)
        return (json.loads(d.fields).get("paye_ref") if d is not None and d.fields else None) or (l.note or "").replace("PAYE ", "")
    on_return = [(ref_of(l), l.label) for l in lines]
    picked: Dict[str, Tuple[int, str, SADocument, Dict]] = {}
    for d in docs.values():
        if d.kind not in ("P45", "PAYSLIP") or d.status not in ("READ", "CHECK") or not d.fields or d.id in have:
            continue
        f = json.loads(d.fields)
        if (f.get("pay_this") is None or f.get("other_person") or f.get("one_reader")
                or (d.kind == "PAYSLIP" and not f.get("final"))):
            continue
        key = (f.get("paye_ref") or f.get("employer") or str(d.id)).upper()
        rank = (0 if d.kind == "P45" else 1, -(int((f.get("pay_date") or "0").replace("-", "")) if d.kind == "PAYSLIP" else 0))
        if key not in picked or rank < picked[key][0]:
            picked[key] = (rank, key, d, f)
    for _rank, key, d, f in picked.values():
        if any((ref and f.get("paye_ref") and ref.upper() == f["paye_ref"].upper()) or same_payer(label, f.get("employer") or "")
               for ref, label in on_return):
            continue                       # a P60 (or another document) gives this employment already
        db.add(SALine(job_id=job.id, source="EMPLOYMENT", kind="P60", label=f.get("employer") or "Employer",
                      amount=f["pay_this"], tax_paid=f.get("tax_this") or 0, doc_id=d.id, auto=1,
                      note=f"PAYE {f['paye_ref']}" if f.get("paye_ref") else None))
    db.commit()


def sync_p11d_lines(db: Session, job: SAJob) -> None:
    """Each P11D benefit as an employment line under its SA102 box (R-SA102-03), the employer's name as its label; a
    benefit taxed through the payroll is already in the P60's pay and is not added (R-SA102-07)."""
    from backend.app.sa.extract.p11d import BOXES, LABELS
    have = {d for (d,) in db.query(SALine.doc_id).filter(SALine.job_id == job.id, SALine.doc_id.isnot(None)).all()}
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "P11D",
                                           SADocument.status.in_(("READ", "CHECK"))).all():
        f = json.loads(doc.fields) if doc.fields else {}
        if doc.id in have or f.get("other_person"):
            continue
        for b in f.get("benefits") or []:
            if b.get("payrolled"):
                continue
            db.add(SALine(job_id=job.id, source="EMPLOYMENT", kind="BENEFIT", label=(f.get("employer") or "Employer")[:255],
                          amount=b["amount"], doc_id=doc.id, auto=1,
                          note=f"SA102 box {BOXES[b['kind']]}: {b.get('description') or LABELS[b['kind']]}"[:500]))
    db.commit()
