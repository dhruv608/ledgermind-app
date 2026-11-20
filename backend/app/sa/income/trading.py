"""A trade's figures from VAT returns, CIS statements, receipts and invoices, and the client's own sheets; payments
on account from HMRC statements."""

import json
from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.sa.models import SADocument, SAJob


VAT_OUT, VAT_IN = "Output VAT on takings (VAT returns, box 1)", "Input VAT reclaimed (VAT returns, box 4)"


def vat_returns(db: Session, job: SAJob, start: str, end: str) -> List[Dict]:
    """The VAT returns that overlap start..end, one per return period (the client's copy and the firm's working for the
    same quarter count once), each with the part of it inside the period."""
    from backend.app.sa.extract.vat_return import overlap
    by_period: Dict = {}
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "VAT_RETURN",
                                         SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id):
        f = json.loads(d.fields) if d.fields else {}
        if f.get("other_person") or f.get("box1") is None:
            continue
        part = overlap(f, start, end)
        if part:
            by_period.setdefault((f.get("period_from"), f.get("period_to")), {**f, "part": part, "doc_id": d.id})
    return sorted(by_period.values(), key=lambda f: f.get("period_from") or "")


def sync_vat_returns(db: Session, job: SAJob) -> None:
    """A VAT-registered trade worked net of VAT (R-SA103-16, BIM31525): with one business whose takings come from the bank
    (VAT inclusive), the returns' output VAT comes off the takings and the input VAT reclaimed off the costs, each by the
    part of the return inside the business's period. Worked again each time, so a re-posted bank or a new return counts."""
    from backend.app.sa.books import FROM_BANK, period
    from backend.app.sa.models import SABusiness, SABusinessItem
    bizs = db.query(SABusiness).filter(SABusiness.job_id == job.id).all()
    if len(bizs) != 1:
        return                             # several businesses: which trade the returns belong to is a decision
    biz = bizs[0]
    db.query(SABusinessItem).filter(SABusinessItem.business_id == biz.id,
                                    SABusinessItem.description.in_((VAT_OUT, VAT_IN))).delete(synchronize_session=False)
    from_bank = db.query(SABusinessItem).filter(SABusinessItem.business_id == biz.id,
                                                SABusinessItem.description == FROM_BANK).count() > 0
    returns = vat_returns(db, job, *period(job, biz))
    if from_bank and returns:
        out_vat = round(sum((f.get("box1") or 0) * f["part"] for f in returns), 2)
        in_vat = round(sum((f.get("box4") or 0) * f["part"] for f in returns), 2)
        if out_vat:
            db.add(SABusinessItem(business_id=biz.id, job_id=job.id, heading="TURNOVER", description=VAT_OUT,
                                  amount=-out_vat, doc_id=returns[0]["doc_id"]))
        if in_vat:
            db.add(SABusinessItem(business_id=biz.id, job_id=job.id, heading="OTHER", description=VAT_IN,
                                  amount=-in_vat, doc_id=returns[0]["doc_id"]))
    db.commit()


def sync_statement_poa(db: Session, job: SAJob) -> None:
    """HMRC's statement gives the year's payments on account (R-FAM-03): put on Tax calculation as already paid when
    nothing was entered there (a figure the accountant typed is never replaced)."""
    from backend.app.sa.models import SAPayments
    row = db.get(SAPayments, job.id)
    if row is not None and float(row.poa_paid or 0):
        return
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "HMRC_STATEMENT",
                                         SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id.desc()):
        f = json.loads(d.fields) if d.fields else {}
        if f.get("poa_total") and not f.get("other_person"):
            row = row or SAPayments(job_id=job.id)
            row.poa_paid = f["poa_total"]
            db.merge(row)
            db.commit()
            return


def sync_cis_takings(db: Session, job: SAJob) -> None:
    """The gross on each CIS statement as the trade's takings (R-SA103-10: the turnover is the gross, not the net
    paid; the deductions are tax already paid, set on the business from the same statements). Only when the bank gives
    the trade no takings (no bank statements, or none sorted as takings): with bank takings the contractor's net
    payments are already there, and the gross-up is the accountant's point (the same money is never counted twice).
    One business: that one; none: one is added; several: the accountant says whose statements they are. A statement
    sent twice (same contractor, month and gross) is counted once. Materials on a statement are not taken as a cost:
    what the client paid for them is on their receipts or bank."""
    from datetime import date, timedelta
    from backend.app.sa.models import SABusiness, SABusinessItem
    from backend.app.sa import books
    docs = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "CIS_STATEMENT",
                                       SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id).all()
    read = [(d, json.loads(d.fields)) for d in docs if d.fields]
    read = [(d, f) for d, f in read if not f.get("other_person") and f.get("gross")]
    if not read:
        return
    done = {d for (d,) in db.query(SABusinessItem.doc_id).filter(SABusinessItem.job_id == job.id,
                                                                 SABusinessItem.doc_id.isnot(None)).distinct().all()}
    bizs = db.query(SABusiness).filter(SABusiness.job_id == job.id).all()
    if len(bizs) > 1:
        return
    biz = bizs[0] if bizs else None
    if biz is None:
        biz = SABusiness(job_id=job.id, name="Trade", note="Added from the CIS statements: name the trade.")
        db.add(biz)
        db.flush()
    elif not any(d.id in done for d, _ in read):
        # The first time: only when the bank gives the trade no takings (once taken, a statement sent later is added)
        # (nor when the client's own sheet or the accountant already gave it takings)
        totals = {t["heading"]: t["amount"] for t in books.view(db, job, biz)["totals"]}
        typed = db.query(SABusinessItem).filter(SABusinessItem.business_id == biz.id,
                                                SABusinessItem.heading.in_(("TURNOVER", "OTHER_INCOME"))).count()
        if (totals.get("TURNOVER") or 0) + (totals.get("OTHER_INCOME") or 0) > 0 or typed:
            return
    start, end = (str(x)[:10] for x in books.period(job, biz))
    # The tax month ends on the 5th: the month to 5 April belongs to a period ending 31 March
    last = (date.fromisoformat(end) + timedelta(days=5)).isoformat()
    seen = set()
    for d, f in read:
        key = ((f.get("contractor") or "").lower(), f.get("month_end"), f["gross"])
        if key in seen:
            continue
        seen.add(key)
        on = str(f.get("month_end") or "")[:10]
        if d.id in done or (on and not start <= on <= last):
            continue
        db.add(SABusinessItem(business_id=biz.id, job_id=job.id, heading="TURNOVER",
                              description=f"CIS gross from {f.get('contractor') or 'contractor'}"
                                          + (f", month to {on}" if on else ""),
                              amount=f["gross"], disallowed=0, doc_id=d.id))
    db.commit()


RECEIPT_DAYS = 10            # a receipt and its bank payment: the same amount within this many days


def sync_receipt_items(db: Session, job: SAJob) -> None:
    """The client's receipts and invoices on their trade (purchase and sales invoices; costs by SA103 heading),
    each money once (a receipt matched to its payment is the same money):

      a cost      a receipt whose payment is on the bank statements (the same amount within 10 days) is that payment's
                  evidence, not a second cost; one paid in cash, by a card whose statements were not sent, or from an
                  account not sent is a cost under its heading (paid personally for the trade). Personal spending is
                  left out, a capital item is left for the capital allowances, entertaining is disallowed (s45)
      a sale      the client's own invoice is takings only when the bank gives the trade no takings (as the CIS
                  statements); otherwise the bank's receipts are the takings and the invoices their evidence
      VAT         a business that files VAT returns takes costs without their VAT; one that does not, with it
                  (BIM31535)

    One business: that one; none: one is added; several: the accountant says whose receipts they are. A bill sent
    twice (the same issuer, date and total) counts once; a bill outside the business's period is left out. Only bills
    both readers agree on are added (a bill to check waits)."""
    from datetime import date
    from backend.app.sa.models import SABusiness, SABusinessItem
    from backend.app.sa import books
    docs = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "INVOICE",
                                       SADocument.status == "READ").order_by(SADocument.id).all()
    read = [(d, json.loads(d.fields).get("bills") or []) for d in docs if d.fields]
    read = [(d, bills) for d, bills in read if bills]
    if not read:
        return
    done = {d for (d,) in db.query(SABusinessItem.doc_id).filter(SABusinessItem.job_id == job.id,
                                                                 SABusinessItem.doc_id.isnot(None)).distinct().all()}
    read_new = [(d, bills) for d, bills in read if d.id not in done]
    if not read_new:
        return
    bizs = db.query(SABusiness).filter(SABusiness.job_id == job.id).all()
    if len(bizs) > 1:
        return
    useful = any(b["heading"] not in ("PERSONAL", "CAPITAL") for _, bills in read_new for b in bills)
    if not bizs and not useful:
        return
    biz = bizs[0] if bizs else SABusiness(job_id=job.id, name="Trade", note="Added from the receipts and invoices: name the trade.")
    if not bizs:
        db.add(biz)
        db.flush()
    start, end = (str(x)[:10] for x in books.period(job, biz))
    vat_registered = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "VAT_RETURN").count() > 0
    view = books.view(db, job, biz)
    lines = view["lines"]
    totals = {t["heading"]: t["amount"] for t in view["totals"]}
    bank_takings = (totals.get("TURNOVER") or 0) + (totals.get("OTHER_INCOME") or 0) > 0
    # Takings already given another way (the CIS statements, the client's sheet, typed by the accountant)
    receipt_docs = {d.id for d, _ in read}
    typed_takings = any(i.doc_id not in receipt_docs for i in db.query(SABusinessItem).filter(
        SABusinessItem.business_id == biz.id, SABusinessItem.heading.in_(("TURNOVER", "OTHER_INCOME"))))
    used = set()                                   # bank lines already matched to a receipt

    def in_bank(amount: float, on: str, side: str) -> bool:
        day = date.fromisoformat(on)
        for k, l in enumerate(lines):
            if k in used or not l.get("on") or abs(float(l.get(side) or 0) - amount) > 0.01:
                continue
            try:
                if abs((date.fromisoformat(str(l["on"])[:10]) - day).days) <= RECEIPT_DAYS:
                    used.add(k)
                    return True
            except ValueError:
                continue
        return False

    seen = set()
    for d, bills in read:                           # the bills already taken count as seen
        if d.id in done:
            seen |= {((b.get("issuer") or "").lower(), b.get("date"), b["total"]) for b in bills}
    notes = []
    for d, bills in read_new:
        for b in bills:
            key = ((b.get("issuer") or "").lower(), b.get("date"), b["total"])
            if key in seen or not b.get("date") or not start <= b["date"] <= end:
                continue
            seen.add(key)
            if b["heading"] == "PERSONAL":
                continue
            if b["heading"] == "CAPITAL":
                notes.append(f"{b.get('issuer') or 'A receipt'} {b['date']} £{b['total']:,.2f} ({b.get('what') or 'an asset'}): "
                             f"a capital item, for the capital allowances, not a cost.")
                continue
            if b["kind"] == "SALE":
                if bank_takings or typed_takings or in_bank(b["total"], b["date"], "in"):
                    continue
                heading, amount, disallowed = "TURNOVER", b["total"] - (b["vat"] if vat_registered else 0), 0
            else:
                # Paid from the bank: that payment's evidence. Paid INTO the bank: money the person received (a pay
                # statement read as a bill), never a cost
                if in_bank(b["total"], b["date"], "out") or in_bank(b["total"], b["date"], "in"):
                    continue
                amount = round(b["total"] - (b["vat"] if vat_registered else 0), 2)
                heading = "ADVERTISING" if b["heading"] == "ENTERTAINING" else b["heading"]
                disallowed = amount if b["heading"] == "ENTERTAINING" else 0
            what = f": {b['what']}" if b.get("what") else ""
            db.add(SABusinessItem(business_id=biz.id, job_id=job.id, heading=heading, amount=round(amount, 2),
                                  disallowed=disallowed, doc_id=d.id,
                                  description=f"{'Invoice to' if b['kind'] == 'SALE' else 'Receipt:'} "
                                              f"{(b.get('customer') if b['kind'] == 'SALE' else b.get('issuer')) or ''} "
                                              f"{b['date']}{what}"[:255]))
    if notes:
        biz.note = " ".join(x for x in (biz.note, *notes) if x)[:4000]
    db.commit()


def sync_client_sheets(db: Session, job: SAJob) -> None:
    """The client's own income and expenses sheet on their trade (one business: that one; none: one is added): each row
    in the period under its SA103 heading; commuting and study costs kept but disallowed pending a decision. When the
    trade also has bank statements, each side is taken from one place: the sheet's income when the bank shows no
    takings, its costs when the bank shows none; otherwise the sheet is a cross-check (trade_points.py)."""
    from backend.app.sa.extract import client_sheet
    from backend.app.sa.models import SABusiness, SABusinessItem
    from backend.app.sa.books import period
    docs = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "CLIENT_ACCOUNTS",
                                       SADocument.status.in_(("READ", "CHECK"))).all()
    if not docs:
        return
    has_bank = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "BANK_STATEMENT",
                                           SADocument.status.in_(("READ", "CHECK"))).count() > 0
    done = {d for (d,) in db.query(SABusinessItem.doc_id).filter(SABusinessItem.job_id == job.id,
                                                                 SABusinessItem.doc_id.isnot(None)).distinct().all()}
    bizs = db.query(SABusiness).filter(SABusiness.job_id == job.id).all()
    taken = set()
    for d in docs:
        if d.id in done and d.fields:
            for r in json.loads(d.fields).get("rows") or []:
                taken.add((r.get("on"), r.get("income"), r.get("expense"), (r.get("detail") or "").lower()))
    for doc in sorted(docs, key=lambda d: d.id):
        f = json.loads(doc.fields) if doc.fields else {}
        if doc.id in done or not f.get("rows"):
            continue
        biz = bizs[0] if len(bizs) == 1 else None
        if biz is None and not bizs:
            biz = SABusiness(job_id=job.id, name="Trade", note=f"Added from {doc.filename.split('/')[-1]}: name the trade.")
            db.add(biz)
            db.flush()
            bizs.append(biz)
        if biz is None:
            continue                       # several businesses: the accountant says whose sheet it is
        start, end = period(job, biz)
        # A second version of the sheet repeats the first one's rows: a row already taken is counted once
        rows = []
        for r in f["rows"]:
            key = (r.get("on"), r.get("income"), r.get("expense"), (r.get("detail") or "").lower())
            if key not in taken:
                taken.add(key)
                rows.append(r)
        out = client_sheet.lines(rows, start, end)
        # With bank statements, each side comes from one place: the sheet's income only when the bank shows no takings,
        # its costs only when the bank shows none (the same money is never counted twice)
        if has_bank:
            from backend.app.sa import books
            totals = {t["heading"]: t["amount"] for t in books.view(db, job, biz)["totals"]}
            bank_in = totals.get("TURNOVER", 0.0) + totals.get("OTHER_INCOME", 0.0)
            from backend.app.sa.trade import HEADINGS as _TH
            bank_costs = sum(v for h, v in totals.items() if h in _TH and _TH[h][2] == "cost")
            out["items"] = [i for i in out["items"] if (i["heading"] == "TURNOVER" and not bank_in)
                            or (i["heading"] != "TURNOVER" and not bank_costs)]
        for it in out["items"]:
            db.add(SABusinessItem(business_id=biz.id, job_id=job.id, heading=it["heading"], description=it["description"],
                                  amount=it["amount"], disallowed=it["disallowed"], doc_id=doc.id))
        notes = []
        if out["outside"]:
            notes.append(f"{out['outside']} row(s) of the client's sheet fall outside the period and are left out.")
        for why, text, amount in out["decisions"]:
            reason = {"commuting": "commuting, BIM37605", "study": "study or a new qualification",
                      "use of home": "use of home: the flat rate by hours worked at home, R-SA103-13",
                      "mileage": "mileage: business miles at the flat rate once the journeys are checked, R-SA103-12"}[why]
            notes.append(f"{text}: £{amount:,.2f} disallowed pending a decision ({reason}).")
        if out["miles"]:
            notes.append(f"{out['miles']:,.0f} miles on the client's sheet: business travel or commuting? Enter business "
                         f"miles for the flat rate once decided.")
        if notes:
            biz.note = " ".join(x for x in (biz.note, *notes) if x)[:4000]
    db.commit()
