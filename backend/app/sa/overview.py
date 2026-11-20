"""The return at a glance: the result, each section's state and amount, and every item a person must look at.

  state   done (figures, nothing open), look (something to check), empty (no figures yet)
  look    documents read with a doubt or not readable, sections the person has but no figures for, a property with
          rent and no costs or costs and no rent, a P60's line changed by hand after it was read
  steps   Documents, Income, Review (queries open), Pack (done when the newest version is final)"""

import json
from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.sa.income import calculation, sync_p60_lines
from backend.app.sa.models import SADocument, SAJob, SALine

LABELS = {"EMPLOYMENT": "Employment", "SELF_EMPLOYMENT": "Self-employment", "PROPERTY": "Property",
          "SAVINGS": "Savings interest", "DIVIDENDS": "Dividends", "PENSIONS": "Pensions and benefits",
          "FOREIGN": "Foreign income", "CAPITAL_GAINS": "Capital gains", "RELIEFS": "Reliefs"}
KIND_WORDS = {"P60": "P60", "PAY": "entered", "INTEREST": "entered", "ISA": "entered", "DIVIDEND": "entered",
              "STATE_PENSION": "entered", "PENSION": "entered", "BENEFIT": "entered", "GIFT_AID": "entered",
              "PENSION_RAS": "entered", "SALARY_SACRIFICE": "entered", "PROFIT": "entered", "INCOME": "entered"}


def _used_amount(l) -> float:
    return float(l.amount or 0) * float(l.share if l.share is not None else 1)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def overview(db: Session, job: SAJob) -> Dict:
    sync_p60_lines(db, job)
    calc = calculation(db, job)
    c, prop, trade = calc["calculation"], calc["property"], calc["trade"]
    docs = db.query(SADocument).filter(SADocument.job_id == job.id).all()
    lines = db.query(SALine).filter(SALine.job_id == job.id).all()
    doc_status = {d.id: d.status for d in docs}
    look: List[Dict] = []

    # The same note on several documents (a run of one agent's monthly statements) is one line with the count
    by_note: Dict[str, List] = {}
    for d in docs:
        if d.status in ("CHECK", "UNREADABLE"):
            note = d.note or ('cannot be read' if d.status == 'UNREADABLE' else 'check the figures')
            by_note.setdefault(note, []).append(d)
    for note, ds in by_note.items():
        leaf = ds[0].filename.replace("\\", "/").split("/")[-1]
        look.append({"page": "documents", "doc_id": ds[0].id, "kind": "document",
                     "text": f"{leaf}: {note}" if len(ds) == 1 else f"{len(ds)} documents ({leaf} and others): {note}"})

    # The kinds ticked for the person, and any other kind that has figures (a P60 for someone not ticked as employed)
    from backend.app.sa.models import SOURCES
    ticked = set(json.loads(job.sources or "[]"))
    found = ({l.source for l in lines} | ({"PROPERTY"} if prop["properties"] else set())
             | ({"CAPITAL_GAINS"} if calc["cgt"]["disposals"] else set())
             | ({"FOREIGN"} if calc["foreign"] or calc["foreign_property"]["properties"] else set())
             | ({"SELF_EMPLOYMENT"} if trade["businesses"] else set()))
    sections = []
    for s in [x for x in SOURCES if x in ticked | found] + ["RELIEFS"]:
        mine = [l for l in lines if l.source == s and l.include]
        amount = round(sum(float(l.amount or 0) * float(l.share if l.share is not None else 1) for l in mine), 2)
        open_docs = [l for l in mine if l.doc_id and doc_status.get(l.doc_id) == "CHECK"]
        if s == "PROPERTY" and prop["properties"]:
            amount = prop["profit"]
            source = _plural(len(prop["properties"]), "property")
            state = "done"
            for p in prop["properties"]:
                if p["rents"] and not p["expenses"] and not p["finance_costs"]:
                    look.append({"page": "property", "kind": "property", "text": f"{p['name']}: rent but no costs entered. Any costs?"})
                    state = "look"
                elif not p["rents"]:
                    look.append({"page": "property", "kind": "property", "text": f"{p['name']}: no rent entered."})
                    state = "look"
        elif s == "SELF_EMPLOYMENT" and trade["businesses"]:
            amount = trade["taxable_profit"] + sum(float(l.amount or 0) for l in mine)
            n = len(trade["businesses"])
            source = f"{n} business{'' if n == 1 else 'es'}" + (", entered" if mine else "")
            state = "done"
            for b in trade["businesses"]:
                if not b["income"]:
                    look.append({"page": "self_employment", "kind": "trade", "text": f"{b['name']}: no turnover entered."})
                    state = "look"
                for w in b["warnings"]:
                    look.append({"page": "self_employment", "kind": "trade", "text": f"{b['name']}: {w}"})
                    state = "look"
        elif s == "FOREIGN" and (calc["foreign"] or calc["foreign_property"]["properties"]):
            fp = calc["foreign_property"]
            amount = round(sum(r["taxable"] for r in calc["foreign"]) + sum(_used_amount(l) for l in mine) + fp["profit"], 2)
            source = ", ".join(x for x in (_plural(len(calc["foreign"]), "source") if calc["foreign"] else "",
                                           _plural(len(fp["properties"]), "property") if fp["properties"] else "") if x)
            issues = [i for r in calc["foreign"] for i in r["issues"]]
            state = "look" if issues else "done"
            for i in issues:
                look.append({"page": "foreign", "kind": "foreign", "text": i["text"]})
        elif s == "CAPITAL_GAINS" and calc["cgt"]["disposals"]:
            cg = calc["cgt"]
            amount = cg["summary"]["net"]
            source = _plural(len(cg["disposals"]), "disposal")
            state = "look" if cg["issues"] else "done"
            for i in cg["issues"]:
                look.append({"page": "capital_gains", "kind": "capital_gains", "text": i["text"]})
        elif mine:
            words = sorted({KIND_WORDS.get(l.kind, "entered") for l in mine})
            n_docs = len({l.doc_id for l in mine if l.doc_id})
            source = ", ".join(_plural(n_docs, w) if w == "P60" else w for w in words)
            state = "look" if open_docs else "done"
            for l in open_docs:
                look.append({"page": s.lower(), "doc_id": l.doc_id, "kind": "line",
                             "text": f"{LABELS[s]}: {l.label} comes from a P60 that needs a look."})
        else:
            source, state = "nothing yet", "empty"
            if s != "RELIEFS":
                look.append({"page": s.lower(), "kind": "missing", "text": f"{LABELS[s]}: no figures yet."})
        sections.append({"id": s.lower(), "source": s, "label": LABELS[s], "amount": amount, "state": state,
                         "from": source})

    # Queries: an open Block stops the return being finished (an Unknown source blocks finalisation; R-OUT-01)
    from backend.app.sa.queries import queries
    q = queries(db, job)["counts"]
    if q["blocks"]:
        look.insert(0, {"page": "queries", "kind": "block",
                        "text": f"{q['blocks']} block{'s' if q['blocks'] > 1 else ''} open: the return cannot be finished until "
                                f"{'they are' if q['blocks'] > 1 else 'it is'} answered."})
    review_state = "look" if q["blocks"] or q["client"] or q["decisions"] else "done"

    doc_state = "empty" if not docs else ("look" if any(d.status in ("CHECK", "UNREADABLE") for d in docs) else "done")
    income_state = ("empty" if all(x["state"] == "empty" for x in sections if x["source"] != "RELIEFS")
                    else "look" if any(x["state"] != "done" for x in sections if x["source"] != "RELIEFS") else "done")
    # The pack: done when the newest version is final, look while only drafts are made
    from backend.app.sa.models import SAPack
    latest = db.query(SAPack).filter(SAPack.job_id == job.id).order_by(SAPack.version.desc()).first()
    pack_state = "empty" if latest is None else ("done" if latest.kind == "FINAL" else "look")
    from backend.app.sa.pack import deadlines
    due = next(d for label, d in deadlines(job.tax_year) if label.startswith("Online return"))
    return {
        "result": {"balance": c["balance"], "liability": c["liability"], "tax_deducted": c["tax_deducted"],
                   "due_31_january": c["due_31_january"], "poa_each": c["poa_each"], "due_date": due.isoformat()},
        "documents": {"count": len(docs), "state": doc_state,
                      "look": sum(1 for d in docs if d.status in ("CHECK", "UNREADABLE"))},
        "sections": sections,
        "steps": [{"id": "documents", "label": "Documents", "state": doc_state},
                  {"id": "income", "label": "Income", "state": income_state},
                  {"id": "review", "label": "Review", "state": review_state},
                  {"id": "pack", "label": "Pack", "state": pack_state}],
        "look": look,
        "queries": q,
        "notes": [n for n in calc["notes"] if not n.startswith("No figures yet") and "document(s) to look at" not in n],
    }
