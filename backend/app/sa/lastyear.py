"""This year's checklist from last year (every source on last year's return is Continued, Changed or
Unknown). The lines come from last year's working paper (read when it is added: documents.read_last_year); the
newest one wins when more than one is sent (R-IN-08). The accountant can change, add or remove lines."""

import json
import re
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.sa.extract.lastyear import SOURCES

LABELS = {
    "EMPLOYMENT": "Employment", "PENSIONS": "Pensions and benefits", "SAVINGS": "Interest", "DIVIDENDS": "Dividends",
    "PROPERTY": "Property", "SELF_EMPLOYMENT": "Self-employment", "FOREIGN": "Foreign income", "OTHER": "Other income",
    "RELIEFS": "Reliefs", "CARRY_FORWARD": "Carried forward",
}
KIND_LABELS = {
    "P60": "Employment", "PENSION": "Pension", "STATE_PENSION": "State Pension", "BENEFIT": "State benefit",
    "INTEREST": "Interest", "DIVIDEND": "Dividends", "PROFIT": "Profit", "INCOME": "Income", "GIFT_AID": "Gift Aid",
    "PENSION_RAS": "Pension contributions", "LOSS": "Loss", "FINANCE_COSTS": "Unused finance costs",
    "DEFERRED": "Left to this year", "OTHER": "Other", "EXEMPT": "Not taxable", "CA_POOL": "Capital allowances pool",
    "USE_OF_HOME": "Use of home", "EXPENSES": "Employment expenses", "EMPLOYMENT:BENEFIT": "Benefits in kind (P11D)",
}


def last_year_doc(db: Session, job):
    """Last year's working paper that was read: with several versions, the latest by the file's own saved date, then
    the last one sent (R-IN-08)."""
    from backend.app.sa.models import SADocument
    found = []
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "WORKING_PAPER",
                                         SADocument.fields.isnot(None)):
        f = json.loads(d.fields)
        # A working paper named for a company ('Acme Consulting Ltd Working Papers') is the company's accounts,
        # not the person's own return: its profit is not their self-employment
        if f.get("last_year") and not COMPANY_FILE.search(d.filename.replace("\\", "/").split("/")[-1]):
            found.append((f.get("saved") or "", d.id, d))
    return max(found, key=lambda x: (x[0], x[1]))[2] if found else None


COMPANY_FILE = re.compile(r"\b(ltd|limited|plc|llp)\b", re.I)


def sync(db: Session, job) -> None:
    """The lines read from last year's working paper, in place of lines read from an older one (hand lines stay)."""
    from backend.app.sa.models import SAExpect
    doc = last_year_doc(db, job)
    rows = db.query(SAExpect).filter(SAExpect.job_id == job.id, SAExpect.auto == 1)
    if doc is None:
        # No usable paper (any read before came from one that no longer counts): its lines go, hand lines stay
        if rows.count():
            rows.delete(synchronize_session=False)
            db.commit()
        return
    if any(r.doc_id == doc.id for r in rows):
        return
    rows.delete(synchronize_session=False)
    for l in json.loads(doc.fields).get("lines") or []:
        db.add(SAExpect(job_id=job.id, doc_id=doc.id, source=l["source"], kind=l["kind"], name=l["name"], ref=l.get("ref"),
                        last_amount=l.get("amount"), last_tax=l.get("tax"), ended=l.get("ended"), note=l.get("note"),
                        status="ENDED" if l.get("ended") and l["source"] == "EMPLOYMENT" else None, auto=1,
                        agreed=0 if l.get("agreed") is False else 1))
    db.commit()


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


def view(db: Session, job) -> Dict:
    from backend.app.sa.models import SAExpect
    sync(db, job)
    doc = last_year_doc(db, job)
    fields = json.loads(doc.fields) if doc else {}
    order = list(LABELS)
    matched, new = match(db, job)
    by = {m["id"]: m for m in matched}
    rows = sorted(db.query(SAExpect).filter(SAExpect.job_id == job.id).all(),
                  key=lambda r: (order.index(r.source) if r.source in order else 99, r.id))

    def line(r):
        m = by.get(r.id, {})
        status = m.get("status", r.status)
        return {"id": r.id, "source": r.source, "source_label": LABELS.get(r.source, r.source), "kind": r.kind,
                "kind_label": KIND_LABELS.get(f"{r.source}:{r.kind}", KIND_LABELS.get(r.kind, r.kind)), "name": r.name, "ref": r.ref,
                "last_amount": _f(r.last_amount), "last_tax": _f(r.last_tax), "ended": r.ended, "note": r.note,
                "status": status, "status_label": STATUS_LABELS.get(status or "", ""), "this_amount": m.get("this_amount"),
                "question": m.get("question"), "group": m.get("group"), "group_last": m.get("group_last"),
                "group_first": m.get("group_first", False), "hand": bool(r.hand), "answer": r.answer, "auto": bool(r.auto),
                "agreed": bool(r.agreed)}
    return {
        "document": {"id": doc.id, "filename": doc.filename, "tax_year": doc.tax_year, "note": doc.note} if doc else None,
        "total_income": fields.get("total_income"), "answers": fields.get("answers") or {},
        "lines": [line(r) for r in rows],
        "new": new,
        "counts": {k: sum(1 for m in matched if m["status"] == k) for k in (CONTINUED, CHANGED, UNKNOWN, ENDED)},
        "statuses": [{"status": k, "label": v} for k, v in STATUS_LABELS.items() if k != NEW],
        "sources": {s: {"label": LABELS[s], "kinds": [{"kind": k, "label": KIND_LABELS.get(k, k)} for k in ks]}
                    for s, ks in SOURCES.items()},
    }


# ---- Each line matched to this year's figures (Continued / Changed / Unknown), and what is new ----

CONTINUED, CHANGED, UNKNOWN, ENDED, NEW = "CONTINUED", "CHANGED", "UNKNOWN", "ENDED", "NEW"
VARIANCE = 0.25                 # R-EX-07: a source moving more than 25% against last year is asked about
STATUS_LABELS = {CONTINUED: "Continued", CHANGED: "Changed", UNKNOWN: "Unknown", ENDED: "Ended", NEW: "New"}
# Words that say nothing about which payer it is
PLAIN = {"ltd", "limited", "plc", "llp", "the", "and", "bank", "interest", "account", "savings", "saver", "pension",
         "pensions", "group", "company", "income", "profit", "property", "address", "self", "employment",
         "dividends", "dividend", "from", "for", "with", "services", "street", "road"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3 and w not in PLAIN}


def _same_payer(last_name: str, last_ref: Optional[str], name: str, note: str = "") -> bool:
    if last_ref and last_ref.replace(" ", "").lower() in (note or "").replace(" ", "").lower():
        return True
    return bool(_words(last_name) & _words(name))


def _money(v: float) -> str:
    return f"£{v:,.2f}"


def this_year(db: Session, job) -> List[Dict]:
    """This year's figures, one row per source line: {source, kind, name, note, amount}; the losses and unused finance
    costs brought forward as rows of their own (_LOSSES, _FINANCE)."""
    from backend.app.sa.models import SABusiness, SALine
    from backend.app.sa.property import pooled
    from backend.app.sa.trade import all_businesses
    rows = []
    for l in db.query(SALine).filter(SALine.job_id == job.id, SALine.include == 1).all():
        share = float(l.share if l.share is not None else 1)
        rows.append({"source": l.source, "kind": l.kind, "name": l.label or "", "note": l.note or "",
                     "amount": round(float(l.amount or 0) * share, 2)})
    prop = pooled(db, job)
    for p in prop["properties"]:
        rows.append({"source": "PROPERTY", "kind": "PROFIT", "name": p["name"], "note": "", "amount": p["profit"]})
    trade = all_businesses(db, job)
    for b in trade["businesses"]:
        rows.append({"source": "SELF_EMPLOYMENT", "kind": "PROFIT", "name": b["name"], "note": "", "amount": b["adjusted_profit"]})
    rows.append({"source": "_LOSSES", "kind": "LOSS", "name": "", "note": "",
                 "amount": round(prop["losses_bf"] + sum(float(b.losses_bf or 0) for b in db.query(SABusiness).filter(SABusiness.job_id == job.id)), 2)})
    rows.append({"source": "_FINANCE", "kind": "FINANCE_COSTS", "name": "", "note": "",
                 "amount": round(prop["finance_costs"] - sum(p["finance_costs"] for p in prop["properties"]), 2)})
    return rows


def _this_year_amounts(db: Session, job) -> List[float]:
    """Every single amount in this year's figures: bank lines of each trade, the client's sheet rows, property items."""
    import json as _json
    from backend.app.sa import books
    from backend.app.sa.models import SABusiness, SADocument, SAPropertyItem
    out: List[float] = []
    for biz in db.query(SABusiness).filter(SABusiness.job_id == job.id):
        try:
            out += [l["in"] or l["out"] for l in books.view(db, job, biz)["lines"]]
        except Exception:
            pass                               # statements that cannot be put together: the sheet and property still count
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "CLIENT_ACCOUNTS"):
        out += [float(r.get("income") or r.get("expense") or 0) for r in (_json.loads(d.fields or "{}").get("rows") or [])]
    out += [abs(float(i.amount or 0)) for i in db.query(SAPropertyItem).filter(SAPropertyItem.job_id == job.id)]
    return [a for a in out if a]


def question(r, end_year: int) -> str:
    """The plain-English client query for a line not found this year (the standard wording where there is one)."""
    n, amt = r.name, _money(float(r.last_amount)) if r.last_amount is not None else ""
    # Interest and dividends inside an ISA, a SIPP or another pension wrapper are never on the return (R-SAV-05)
    if r.source in ("SAVINGS", "DIVIDENDS") and re.search(r"\b(isa|sipp|pension)\b", f"{n} {r.ref or ''}", re.I):
        return None
    if r.source == "PENSIONS":
        return {"STATE_PENSION": "Do you still receive the State Pension? We will use HMRC's figure for the year.",
                "BENEFIT": f"Did you receive {n} this year? Please send the DWP letter showing the amount."
                }.get(r.kind, f"Please send the pension P60 from {n} for the year to 5 April {end_year}.")
    if r.source == "RELIEFS":
        return {"GIFT_AID": "Did you make Gift Aid donations this year? How much in total?",
                "PENSION_RAS": "Did you pay into a personal pension this year? Please send the contribution statement."
                }.get(r.kind, f"Does {n} still apply this year?")
    if r.source == "CARRY_FORWARD":
        return {"DEFERRED": f"Last year's working paper left {amt} for {n} to this year, and no receipt or cost of that "
                            f"amount is in this year's figures: put it on the trade or the property, or note why not (R-EX-02).",
                "LOSS": f"Last year's loss of {amt} should be brought forward: enter it on the business or property.",
                "CA_POOL": f"Last year's paper shows {amt} carried forward for {n}: check it is the tax written-down value "
                           f"(the capital allowances computation, not the accounts' net book value), then enter it on the "
                           f"business. On the cash basis, plant other than cars is not pooled: its unrelieved value is "
                           f"deducted in the first cash basis year (R-SA103-03).",
                "USE_OF_HOME": f"Last year {amt} was claimed for use of home. The flat rate goes by the hours worked at home "
                               f"a month (from 25, 51 and 101 hours, the rates table), or actual costs apportioned: enter "
                               f"the hours on the business (R-SA103-13).",
                "FINANCE_COSTS": f"Unused finance costs of {amt} should be brought forward: enter them on the property."
                }.get(r.kind, f"{n} was carried forward from last year: check it is dealt with.")
    if r.source == "EMPLOYMENT" and r.kind == "BENEFIT":
        return (f"Last year {n} gave you benefits in kind ({amt}, on a P11D). Do you still have them (a company car, "
                f"medical cover)? Please send this year's P11D, or tell us they stopped (R-SA102-03).")
    if r.source == "EMPLOYMENT" and r.kind == "EXPENSES":
        return (f"Last year you claimed employment expenses of {amt} ({n}). Did you pay them again this year? Please send "
                f"the details (R-SA102-05).")
    if r.kind == "EXEMPT":
        return (f"Last year {n} ({amt}) was treated as not taxable. Did you receive it again this year, and is there "
                f"evidence of what it is?")
    return {
        "EMPLOYMENT": f"Did you still work for {n} on 5 April {end_year}? If so, please send your P60.",
        "SAVINGS": f"Please send the annual interest statement for your {n} account.",
        "DIVIDENDS": f"Did you receive dividends from {n} this year? Please send the dividend vouchers.",
        "PROPERTY": f"Do you still let {n}? Please send this year's rent and costs.",
        "SELF_EMPLOYMENT": f"Are you still trading as {n}? Please send this year's income and costs.",
        "FOREIGN": f"Did you receive {n} again this year? Please send the statement or assessment.",
        "OTHER": f"Did you receive {n} again this year? If it is regular, it may now be a trade.",
    }.get(r.source, f"Is {n} still received this year?")


def match(db: Session, job):
    """Each line's status from this year's figures (a status the accountant set stays), and this year's figures that
    are new: ([{id, this_amount, status, question}], [new figures])."""
    from backend.app.sa.models import SAExpect
    end_year = int(job.tax_year[:4]) + 1
    rows = db.query(SAExpect).filter(SAExpect.job_id == job.id).order_by(SAExpect.id).all()
    now = this_year(db, job)
    used: set = set()
    found: Dict[int, Optional[float]] = {}
    amounts = None
    trades = [i for i, x in enumerate(now) if x["source"] == "SELF_EMPLOYMENT"]
    last_trades = [r for r in rows if r.source == "SELF_EMPLOYMENT" and not r.ended]
    one_trade = len(trades) == 1 and len(last_trades) > 1
    if one_trade:
        used.add(trades[0])
    for r in rows:
        if r.source == "CARRY_FORWARD" and r.kind in ("LOSS", "FINANCE_COSTS"):
            have = next(x["amount"] for x in now if x["source"] == ("_LOSSES" if r.kind == "LOSS" else "_FINANCE"))
            found[r.id] = have if abs(have) >= 0.005 else None
            continue
        if r.source == "CARRY_FORWARD" and r.kind == "DEFERRED" and r.last_amount is not None:
            # A receipt or cost left to this year (R-EX-02): matched when this year's bank, the client's sheet or a
            # property shows the same amount (to the pound)
            if amounts is None:
                amounts = _this_year_amounts(db, job)
            want = abs(float(r.last_amount))
            found[r.id] = want if any(abs(a - want) <= 1 for a in amounts) else None
            continue
        if r.source == "CARRY_FORWARD" and r.kind in ("CA_POOL", "USE_OF_HOME"):
            # Dealt with once the business has its pools, or its hours worked at home (R-SA103-03, -13)
            from backend.app.sa.models import SAAllowance, SABusiness
            bizs = db.query(SABusiness).filter(SABusiness.job_id == job.id).all()
            done = (any(b.home_hours for b in bizs) if r.kind == "USE_OF_HOME" else
                    any(float(b.capital_allowances or 0) for b in bizs) or
                    db.query(SAAllowance).filter(SAAllowance.business_id.in_([b.id for b in bizs] or [-1])).count() > 0)
            found[r.id] = float(r.last_amount or 0) if done else None
            continue
        if r.source == "CARRY_FORWARD" or r.kind == "EXEMPT":
            found[r.id] = None                     # matched by the accountant, never by a figure
            continue
        # A P11D benefit or an expenses claim matches only its own kind, never the pay from the same employer
        hits = [i for i, x in enumerate(now) if i not in used and x["source"] == r.source
                and (x["kind"] == r.kind or (r.source in ("PROPERTY", "SELF_EMPLOYMENT", "EMPLOYMENT")
                                             and r.kind not in ("BENEFIT", "EXPENSES") and x["kind"] not in ("BENEFIT", "EXPENSES")))
                and (r.kind in ("STATE_PENSION", "GIFT_AID", "PENSION_RAS") or _same_payer(r.name, r.ref, x["name"], x["note"]))]
        if one_trade and r in last_trades:
            # Last year's paper split one trade by contract or customer: the trade this year, compared in total
            found[r.id] = None
            continue
        if not hits and r.source in ("PROPERTY", "SELF_EMPLOYMENT"):
            # One business (or property) both years: the same one, whatever it is called this year
            mine = [i for i, x in enumerate(now) if i not in used and x["source"] == r.source]
            if len(mine) == 1 and sum(1 for x in rows if x.source == r.source) == 1:
                hits = mine
        used.update(hits)
        found[r.id] = round(sum(now[i]["amount"] for i in hits), 2) if hits else None
    changed = False
    out = []
    for r in rows:
        amount = found.get(r.id)
        last = float(r.last_amount) if r.last_amount is not None else None
        group = one_trade and r in last_trades
        if group:
            # Each line of the split trade carries the trade's totals: last year's lines added up, this year's profit
            amount = now[trades[0]]["amount"]
            last = round(sum(float(x.last_amount or 0) for x in last_trades), 2)
        if r.hand and r.status:
            status = r.status
        elif r.ended and r.source in ("EMPLOYMENT", "PENSIONS", "PROPERTY", "SELF_EMPLOYMENT"):
            status = ENDED                         # R-SA102-02: no query for a job that had already ended
        elif amount is None:
            status = UNKNOWN
        elif last and abs(amount - last) > VARIANCE * abs(last):
            status = CHANGED
        else:
            status = CONTINUED
        if status != r.status:
            r.status, changed = status, True
        ask = None
        if status == UNKNOWN and not r.hand:
            ask = question(r, end_year)
        elif status == CHANGED and not r.hand and last is not None and amount is not None:
            what = f"self-employment profit ({now[trades[0]]['name']})" if group else r.name
            ask = (f"Your {what} was {_money(last)} last year and {_money(amount)} this year "
                   f"({(amount - last) / abs(last):+.0%}). What changed?")
            if group and r is not last_trades[0]:
                ask = None                         # asked once, on the trade's first line
        out.append({"id": r.id, "this_amount": amount, "status": status, "question": ask,
                    "group": f"Part of {now[trades[0]]['name']}: compared as one trade" if group else None,
                    "group_last": last if group else None, "group_first": bool(group and r is last_trades[0])})
    if changed:
        db.commit()
    new = [{"source": x["source"], "source_label": LABELS.get(x["source"], x["source"]), "name": x["name"], "amount": x["amount"]}
           for i, x in enumerate(now) if i not in used and not x["source"].startswith("_") and x["source"] != "RELIEFS"
           and abs(x["amount"]) >= 0.005]
    return out, new
