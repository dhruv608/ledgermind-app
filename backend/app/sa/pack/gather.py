"""The job read into plain figures for the workbook."""

from datetime import datetime
from typing import Dict, List, Optional

from backend.app.sa.pack.style import _money, deadlines, year_end_words
from backend.app.sa.pack.law import law_of
from backend.app.sa.pack.review_sheets import outcome


def _share(l) -> float:
    return float(l.share if l.share is not None else 1)


def gather(db, job, kind: str, version: int, note: Optional[str], counts: Dict) -> Dict:
    import json
    from backend.app.sa import boxes as boxes_mod, lastyear, queries as queries_mod
    from backend.app.sa.income import calculation
    from backend.app.sa.models import SABusiness, SABusinessItem, SADocument, SAExpect, SALine, SAPropertyItem
    from backend.app.sa.overview import overview
    from backend.app.sa.property import HEADINGS as P_HEADINGS
    from backend.app.sa.trade import HEADINGS as T_HEADINGS

    view = overview(db, job)
    calc = calculation(db, job)
    lines = db.query(SALine).filter(SALine.job_id == job.id).order_by(SALine.id).all()
    company = None
    if job.company_engagement_id:
        from backend.app.models.database import ClientEngagement
        eng = db.get(ClientEngagement, job.company_engagement_id)
        company = eng.client_name if eng else None

    def masked(v):
        return ("•" * max(len(v) - 3, 0) + v[-3:]) if v else None

    employments = [{"name": l.label, "ref": (l.note or "")[5:] if (l.note or "").startswith("PAYE ") else None,
                    "pay": round(float(l.amount or 0) * _share(l), 2), "tax": _money(l.tax_paid), "doc_id": l.doc_id,
                    "note": None if (l.note or "").startswith("PAYE ") else l.note}
                   for l in lines if l.source == "EMPLOYMENT" and l.include]
    income = [{"name": l.label or l.kind.title(), "amount": round(float(l.amount or 0) * _share(l), 2),
               "tax": _money(l.tax_paid) if float(l.tax_paid or 0) else None, "doc_id": l.doc_id, "counted": True,
               "note": l.note or "", "law": law_of(l.source, l.kind)} for l in lines if l.source in ("PENSIONS", "FOREIGN") and l.include]
    reliefs = [{"name": l.label or l.kind.replace("_", " ").title(), "amount": _money(l.amount),
                "gross": round(float(l.amount or 0) / 0.8, 2) if l.kind in ("GIFT_AID", "PENSION_RAS") else None,
                "doc_id": l.doc_id, "note": l.note or ("Salary sacrifice: no entry" if l.kind == "SALARY_SACRIFICE" else ""),
                "law": law_of("RELIEFS", l.kind)}
               for l in lines if l.source == "RELIEFS" and l.include]
    savings = [{"name": l.label, "tag": "ISA" if l.kind == "ISA" else ("Joint" if _share(l) != 1 else ""),
                "amount": _money(l.amount), "share": _share(l),
                "taxable": 0.0 if l.kind == "ISA" else round(float(l.amount or 0) * _share(l), 2),
                "note": l.note or ("Not taxable (ISA)" if l.kind == "ISA" else ""), "doc_id": l.doc_id,
                "law": law_of("SAVINGS", l.kind)}
               for l in lines if l.source == "SAVINGS" and l.include]
    dividends = [{"name": l.label, "paid_on": l.paid_on, "amount": _money(l.amount), "share": _share(l),
                  "taxable": round(float(l.amount or 0) * _share(l), 2), "note": l.note or "", "doc_id": l.doc_id,
                  "law": law_of("DIVIDENDS")}
                 for l in lines if l.source == "DIVIDENDS" and l.include]

    businesses = []
    bizs = {b.id: b for b in db.query(SABusiness).filter(SABusiness.job_id == job.id)}
    items = db.query(SABusinessItem).filter(SABusinessItem.job_id == job.id).order_by(SABusinessItem.id).all()
    from backend.app.sa import books
    for b in calc["trade"]["businesses"]:
        biz = bizs[b["id"]]
        try:
            bank = [l for l in books.view(db, job, biz)["lines"]]
        except Exception:                          # no statements, or one not read: the sheet goes without them
            bank = []
        # A trade built from the bank: its small balance sheet (SEF 5), as on the Self-employment page
        bsheet = None
        if any(i.business_id == b["id"] and i.description == books.FROM_BANK for i in items):
            try:
                from backend.app.sa.balance_sheet import build as _bs
                bsheet = _bs(db, job, biz)
            except Exception:
                bsheet = None
        businesses.append({**b, "cash_basis": bool(biz.cash_basis), "balance_sheet": bsheet,
                           "headings": {k: {"label": v[0], "box": v[1], "kind": v[2], **b["headings"].get(k, {"amount": 0.0, "disallowed": 0.0})}
                                        for k, v in T_HEADINGS.items()},
                           "items": [{"description": i.description, "heading": T_HEADINGS.get(i.heading, (i.heading,))[0],
                                      "amount": _money(i.amount), "disallowed": _money(i.disallowed), "doc_id": i.doc_id}
                                     for i in items if i.business_id == b["id"]],
                           "bank": [{"description": l["description"], "on": l["on"], "in": l["in"], "out": l["out"],
                                     "heading": books.label(l["heading"]), "doc_id": l["doc_id"]} for l in bank]})

    pitems = db.query(SAPropertyItem).filter(SAPropertyItem.job_id == job.id).order_by(SAPropertyItem.on, SAPropertyItem.id).all()

    def prop_data(p):
        if not p["properties"]:
            return None
        return {**{k: p[k] for k in ("allowance", "allowance_used", "before_losses", "losses_used", "profit", "loss_cf", "finance_costs")},
                "finance_cf": p.get("finance_cf", 0.0),
                "properties": [{**r, "headings": {h: (P_HEADINGS[h][0], P_HEADINGS[h][1], r["headings"][h]) for h in P_HEADINGS},
                                "items": [{"on": i.on or "", "description": i.description, "amount": _money(i.amount),
                                           "heading": P_HEADINGS.get(i.heading, (i.heading,))[0], "doc_id": i.doc_id}
                                          for i in pitems if i.property_id == r["id"]]}
                               for r in p["properties"]]}
    prop = prop_data(calc["property"])
    prop_abroad = prop_data(calc["foreign_property"])

    # Evidence map: every document and the lines it answers
    answers: Dict[int, List[str]] = {}
    for l in lines:
        if l.doc_id:
            answers.setdefault(l.doc_id, []).append(f"{l.source.replace('_', ' ').title()}: {l.label}")
    for i in items:
        if i.doc_id:
            answers.setdefault(i.doc_id, []).append(f"Self-employment: {i.description}")
    for i in db.query(SAPropertyItem).filter(SAPropertyItem.job_id == job.id, SAPropertyItem.doc_id.isnot(None)):
        answers.setdefault(i.doc_id, []).append(f"Property: {i.description}")
    for e in db.query(SAExpect).filter(SAExpect.job_id == job.id, SAExpect.doc_id.isnot(None)):
        answers.setdefault(e.doc_id, []).append("Last year's figures")
    bank_lines: Dict[int, int] = {}
    for b in businesses:
        for l in b["bank"]:
            if l["doc_id"]:
                bank_lines[l["doc_id"]] = bank_lines.get(l["doc_id"], 0) + 1
    evidence = []
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id).order_by(SADocument.id):
        said = sorted(set(answers.get(doc.id, [])))
        if bank_lines.get(doc.id):
            said.append(f"{bank_lines[doc.id]} bank line(s)")
        evidence.append({"id": doc.id, "file": doc.filename.replace("\\", "/").split("/")[-1], "kind": doc.kind.replace("_", " ").title(),
                         "tax_year": doc.tax_year, "status": doc.status.title(),
                         "in_year": "Yes" if doc.tax_year == job.tax_year else ("Not dated" if not doc.tax_year else "No"),
                         "answers": "; ".join(said[:6]) + (f" and {len(said) - 6} more" if len(said) > 6 else ""),
                         "read_by": doc.read_by, "outcome": outcome(doc, bool(said))})

    q = queries_mod.queries(db, job)
    return {"person": job.person_name, "tax_year": job.tax_year, "year_end": year_end_words(job.tax_year),
            "kind": kind, "version": version, "note": note, "blocks": counts["blocks"], "counts": counts,
            "made": datetime.utcnow().replace(microsecond=0), "utr": masked(job.utr), "ni": masked(job.ni_number),
            "first_return": bool(job.first_return), "company": company,
            "sources": [s.replace("_", " ").title() for s in json.loads(job.sources or "[]")],
            "sections": view["sections"], "result": view["result"] | {k: calc["calculation"][k] for k in
                                                                     ("income_tax_due", "class4", "class2", "cgt", "liability", "poa_each")},
            "deadlines": deadlines(job.tax_year),
            "employments": employments, "income": income, "reliefs": reliefs, "savings": savings, "dividends": dividends,
            "businesses": businesses, "property": prop, "property_abroad": prop_abroad, "last_year": lastyear.view(db, job),
            "calc": calc["calculation"], "inc": calc["income"], "notes": calc["notes"], "cgt": calc["cgt"], "foreign": calc["foreign"],
            "queries": q["items"], "evidence": evidence, "boxes": boxes_mod.boxes(db, job)}
