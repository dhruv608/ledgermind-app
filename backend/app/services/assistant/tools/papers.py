"""Tools that read the working papers built on the books: debtor ageing, GL scrutiny, roll-forwards, payroll by
month, queries, the VAT proof, the files check, coding review, sign-offs and ledger views."""

from typing import Any, Dict

from backend.app.services.assistant.tools.client_data import ClientData, _codes_for, _cut

def debtors_by_age(d: ClientData, only_old: bool = False) -> Dict[str, Any]:
    """Debtors by age per customer (not due, 1-30, 31-60, 61-90, 91+ days) from the client's aged receivables report."""
    from backend.app.services.reconciliation.debtor_ageing import debtor_ageing
    a = debtor_ageing(d.eng, d.db)
    if not a.get("report"):
        return {"error": "No aged debtors (aged receivables) report uploaded for this client."}
    rows = a["customers"]
    if only_old:
        rows = [c for c in rows if abs(c["boxes"][4]) >= 0.005]
    return {"report": a["report"], "as_at": a["as_at"], "boxes": a["boxes"], "total": a["total"],
            "totals_by_age": dict(zip(a["boxes"], a["totals"])),
            "customers": [{"customer": c["customer"], "total": c["total"], **dict(zip(a["boxes"], c["boxes"]))}
                          for c in rows[:40]], "more": max(0, len(rows) - 40)}


def gl_scrutiny(d: ClientData, account: str = "") -> Dict[str, Any]:
    """GL scrutiny (Accounts tab): without an account, each code's lines checked / moved / asked and flagged lines
    still to check; with an account, its flagged and decided lines (why flagged, what was decided)."""
    from backend.app.services.papers import scrutiny
    if not account:
        rep = scrutiny.report(d.eng, d.db)
        rows = sorted(rep["accounts"], key=lambda a: (-a["flagged"], -a["lines"]))
        flagged = rep["flagged"]
        return {"lines": sum(a["lines"] for a in rows), "checked": sum(a["checked"] for a in rows),
                "accounts": [{"code": a["code"], "account": a["name"], "lines": a["lines"], "checked": a["checked"],
                              "moved": a["moved"], "asked": a["asked"], "flagged_to_check": a["flagged"],
                              "total": a["total"]} for a in rows[:40]],
                "flagged_lines_to_check": [{"code": f["code"], "account": f["account"], "date": str(f["date"] or ""),
                                            "description": _cut(f["description"], 100), "amount": f["amount"],
                                            "why": _cut(f["flags"], 200)} for f in flagged[:30]],
                "more_flagged": max(0, len(flagged) - 30),
                "moved": [{"date": str(m["date"] or ""), "description": _cut(m["description"], 80), "amount": m["amount"],
                           "from": m["code"], "to": m["to_code"], "journal": m["journal"]} for m in rep["moved"][:15]],
                "asked": [{"date": str(q["date"] or ""), "description": _cut(q["description"], 80),
                           "question": _cut(q["question"], 150), "answer": _cut(q["answer"], 150) or None}
                          for q in rep["asked"][:15]]}
    codes = _codes_for(d, account)
    if not codes:
        return {"error": f"No account matches '{account}'."}
    out = []
    for code in codes[:3]:
        got = scrutiny.lines(d.eng, d.db, str(code))
        picked = [l for l in got["lines"] if l["flags"] or l["decision"]]
        out.append({"code": code, "account": got["name"], "lines": len(got["lines"]),
                    "flagged_or_decided": [{"date": l["date"], "description": _cut(l["description"], 120),
                                            "amount": l["net"], "flags": [f["text"] for f in l["flags"]],
                                            "decision": l["decision"]} for l in picked[:30]],
                    "more": max(0, len(picked) - 30)})
    return {"accounts": out}


def account_year(d: ClientData, account: str) -> Dict[str, Any]:
    """A balance sheet account's year (Balance sheet tab): opening, this year's lines by type, approved journals,
    closing, and whether opening + lines come to the trial balance."""
    from backend.app.services.papers.rollforward import rollforward
    codes = _codes_for(d, account)
    if not codes:
        return {"error": f"No account matches '{account}'."}
    return rollforward(d.eng, d.db, codes)


def payroll_by_month(d: ClientData) -> Dict[str, Any]:
    """Net wages, PAYE / NI and pension month by month from the ledger (owed, paid, balance, note), and the payroll
    cost against what was owed out: the VAT & payroll tab's card and the workbook's G6-G8."""
    from backend.app.services.papers.payroll_months import payroll_by_month as months
    data = months(d.eng, d.db)
    if not data["tables"]:
        return {"error": "This client's books have no payroll accounts."}
    tables = [{"control": t["title"], "opening": t["opening"], "months_to_look_at": t["flags"],
               "months": [{k: m[k] for k in ("month", "owed", "paid", "balance", "note") if m.get(k) is not None}
                          for m in t["months"]],
               "other_entries": t["other"], "journals": t["journals"], "still_owed_at_year_end": t["closing"]}
              for t in data["tables"]]
    s = data["summary"]
    summary = {"months_not_matching": s["flags"], "has_net_wages": s["has_net_wages"],
               "months": [{"month": m["month"], "total_cost": m["total_cost"], "total_owed_out": m["total_owed"],
                           "unexplained": m["unexplained"]} for m in s["months"]]} if s else None
    return {"note": "Amounts owed are positive (credit); a negative balance means more was paid than owed.",
            "tables": tables, "cost_v_owed_out": summary}


def client_queries(d: ClientData, status: str = "open", audience: str = "") -> Dict[str, Any]:
    """The Queries tab: what the app asks the client, the accountant or the preparer about this job."""
    from backend.app.services.queries.query_list import query_list
    q = query_list(d.db, d.eng)
    rows = q["queries"]
    if status.lower() == "open":
        rows = [r for r in rows if r["status"] == "OPEN"]
    elif status.lower() == "answered":
        rows = [r for r in rows if r["status"] in ("ANSWERED", "CLEARED")]
    if audience:
        rows = [r for r in rows if r["audience"] == audience.upper()]
    return {"open": q["open"], "blocking": q["blocking"],
            "queries": [{"for": r["audience"], "title": _cut(r["title"], 150), "detail": _cut(r["detail"], 250),
                         "amount": r["amount"] or None, "must_answer": r["blocking"], "status": r["status"],
                         "answer": _cut(r["answer"], 200) or None, "from": r["source"]} for r in rows[:40]],
            "more": max(0, len(rows) - 40)}


def vat_proof(d: ClientData) -> Dict[str, Any]:
    """The VAT proof (VAT reconciliation layout): what the VAT account should hold, line by line, against the books."""
    from backend.app.services.tax.vat_proof import vat_proof as proof
    p = proof(d.eng, d.tb, d.db)
    return {"title": p.get("title"), "books_owed": p.get("books"), "proof_total": p.get("total"),
            "difference": p.get("difference"), "missing": p.get("missing") or None,
            "lines": [{"line": l["label"], "amount": l["amount"], "note": _cut(l["note"], 200)} for l in p.get("lines", [])]}


def files_check(d: ClientData) -> Dict[str, Any]:
    """The Files tab: what the working papers need from the client's files, what is missing or must be fixed."""
    from backend.app.services.setup.data_check import data_check
    c = data_check(d.db, d.eng)
    items = [i for i in c["items"] if i["status"] != "OK"]
    return {"ready_to_build": c.get("ready"), "first_year": c.get("first_year"),
            "items": [{"status": i["status"], "what": i["label"], "detail": _cut(i["detail"], 220)} for i in items[:30]],
            "ok_items": sum(1 for i in c["items"] if i["status"] == "OK")}


def coding_review(d: ClientData) -> Dict[str, Any]:
    """Coding review: costs in the wrong account. Re-analysis (a merchant's lines against where the client and firm
    usually code them) and mispostings (a supplier split across accounts)."""
    from backend.app.services.reanalysis.misposting import review
    from backend.app.services.reanalysis.run import groups
    r = groups(d.eng, d.db)
    m = review(d.eng, d.db)
    return {
        "reanalysis": [{"merchant": g["merchant"], "now_in": " ".join(x for x in (str(g['from_code'] or ""), g['from_name']) if x),
                        "should_be_in": " ".join(x for x in (str(g['to_code'] or ""), g['to_name']) if x),
                        "reason": g["reason_text"], "outcome": g["outcome"], "lines": len(g["lines"]), "total": g["total"],
                        "decided": g["decision"]} for g in r["groups"][:15]],
        "mispostings": [{"supplier": g["merchant"], "recommended": g["recommended"], "status": g["status"],
                         "accounts": [f"{a['count']} in {a['code']} {a['name']}" for a in g["accounts"]],
                         "reason": _cut(g["reason"], 160)} for g in m["groups"][:15]],
        "summary": {"reanalysis": r["summary"], "mispostings": m["summary"]},
    }


def signoffs_and_evidence(d: ClientData) -> Dict[str, Any]:
    """Each area's sign-off (prepared, reviewed, approved: initials and date) and the documents on its Evidence tab."""
    from backend.app.api.endpoints.audit import _area_signoffs
    from backend.app.api.endpoints.evidence import _listing
    signed = _area_signoffs(d.db, str(d.eng.id))
    docs = _listing(d.db, str(d.eng.id))
    areas = sorted(set(signed) | set(docs))
    return {"areas": [{"area": a,
                       "signed": [f"{s['role'].lower()} {s['initials']} {str(s['signed_at'])[:10]}" for s in signed.get(a, [])],
                       "documents": [x["filename"] for x in docs.get(a, [])]} for a in areas],
            "note": "An area not listed has no sign-off and no document yet."}


def ledger_view(d: ClientData, account: str) -> Dict[str, Any]:
    """One account as uploaded and as it is now: lines moved off or onto it (GL scrutiny, mispostings) and journals."""
    from backend.app.services.papers.ledger_views import views
    codes = _codes_for(d, account)
    if not codes:
        return {"error": f"No account matches '{account}'"}
    v = views(d.eng, d.db, codes[0])
    pick = lambda rows: [{"date": r.get("date"), "text": _cut(r.get("description"), 80), "amount": r.get("net"),
                          "to" if "to" in r else "note": r.get("to") or r.get("note")} for r in rows[:15]]
    return {"code": v["code"], "name": v["name"], "totals": v["totals"], "moved_out": pick(v["moved_out"]),
            "moved_in": pick(v["moved_in"]),
            "journals": [{"ref": j["ref"], "text": _cut(j["description"], 100), "effect": j["effect"], "status": j["status"]}
                         for j in v["journals"][:15]]}
