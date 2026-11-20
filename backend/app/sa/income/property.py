"""Property items from letting agent statements and mortgage statements."""

import json
import re

from sqlalchemy.orm import Session

from backend.app.sa.models import SADocument, SAJob


def sync_letting_items(db: Session, job: SAJob) -> None:
    """Each letting statement's rent and costs on its property (R-SA105-01 to 11): the property found by its house
    number and street, else added (sole owner, residential: the accountant confirms the facts on the Property page);
    a line already there (same property, date, heading and amount, from another statement) is not added twice. Money
    paid over to the landlord and deposits are left out."""
    from backend.app.sa.extract.letting import overseas, same_property
    from backend.app.sa.models import SAProperty, SAPropertyItem
    done = {d for (d,) in db.query(SAPropertyItem.doc_id).filter(SAPropertyItem.job_id == job.id,
                                                                 SAPropertyItem.doc_id.isnot(None)).distinct().all()}
    from backend.app.sa.fx import rate as fx_rate
    props = db.query(SAProperty).filter(SAProperty.job_id == job.id, SAProperty.country.is_(None)).all()
    abroad = db.query(SAProperty).filter(SAProperty.job_id == job.id, SAProperty.country.isnot(None)).all()
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "LETTING_STATEMENT",
                                           SADocument.status.in_(("READ", "CHECK"))).order_by(SADocument.id).all():
        f = json.loads(doc.fields) if doc.fields else {}
        if doc.id in done or f.get("other_person") or f.get("unconfirmed"):
            continue                       # no agent named: confirmed first
        # Overseas: the overseas property business (SA106 F4-F5), in pounds at HMRC's average rate for the year; a
        # currency with no rate in the table is left for the accountant to enter
        per_gbp = fx_rate(f.get("currency") or "GBP", job.tax_year) if overseas(f) else 1.0
        if overseas(f) and not per_gbp:
            continue
        for p in f.get("properties") or []:
            if overseas(f):
                country = p.get("country") if p.get("country") not in (None, "GBR") else "XXX"
                prop = next((x for x in abroad if same_property(x.name, p["address"])), None)
                if prop is None:
                    prop = SAProperty(job_id=job.id, name=p["address"][:255], country=country[:3],
                                      note=f"Added from {doc.filename.split('/')[-1]}, {f.get('currency')} at {per_gbp} to £1 "
                                           f"(HMRC average): confirm the owner, share and foreign tax.")
                    db.add(prop)
                    db.flush()
                    abroad.append(prop)
                for l in p["lines"]:
                    if l["heading"] == "NOT_INCOME":
                        continue
                    db.add(SAPropertyItem(property_id=prop.id, job_id=job.id, on=l.get("on"), heading=l["heading"],
                                          amount=round(l["amount"] / per_gbp, 2), doc_id=doc.id,
                                          description=f"{l['description']} ({f.get('currency')} {l['amount']:,.2f} at {per_gbp})"[:255]))
                continue
            # No address read (the client's own sheet names none, or only its sheet): the file's name instead
            if re.fullmatch(r"\s*(sheet\s*\d*|not (specified|stated|given)|unknown|n/?a|none)?\s*", p.get("address") or "", re.I):
                p["address"] = doc.filename.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
            prop = next((x for x in props if same_property(x.name, p["address"])), None)
            if prop is None:
                prop = SAProperty(job_id=job.id, name=p["address"][:255],
                                  note=f"Added from {doc.filename.split('/')[-1]}: confirm the owner and share.")
                db.add(prop)
                db.flush()
                props.append(prop)
            seen = {(i.on, i.heading, round(float(i.amount), 2))
                    for i in db.query(SAPropertyItem).filter(SAPropertyItem.property_id == prop.id).all()}
            for l in p["lines"]:
                key = (l.get("on"), l["heading"], round(l["amount"], 2))
                if l["heading"] == "NOT_INCOME" or key in seen:
                    continue
                seen.add(key)
                db.add(SAPropertyItem(property_id=prop.id, job_id=job.id, on=l.get("on"), description=l["description"],
                                      heading=l["heading"], amount=l["amount"], doc_id=doc.id))
    db.commit()


def sync_mortgage_items(db: Session, job: SAJob) -> None:
    """Each mortgage interest certificate's interest as a finance cost of the let property it is on (R-SA105-05): the
    property found by its address, else the only UK let property when the certificate gives none. A mortgage on another
    address (the person's own home) is left out: not a cost of letting."""
    from backend.app.sa.extract.letting import same_property
    from backend.app.sa.models import SAProperty, SAPropertyItem
    done = {d for (d,) in db.query(SAPropertyItem.doc_id).filter(SAPropertyItem.job_id == job.id,
                                                                 SAPropertyItem.doc_id.isnot(None)).distinct().all()}
    props = db.query(SAProperty).filter(SAProperty.job_id == job.id, SAProperty.country.is_(None)).all()
    for doc in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "MORTGAGE_INTEREST",
                                           SADocument.status.in_(("READ", "CHECK"))).all():
        f = json.loads(doc.fields) if doc.fields else {}
        if doc.id in done or f.get("other_person") or f.get("interest") is None:
            continue
        addr = f.get("property_address")
        prop = next((p for p in props if addr and same_property(p.name, addr)), None)
        if prop is None and not addr and len(props) == 1:
            prop = props[0]
        if prop is None:
            continue                       # not on a let property (or not yet added): the accountant places it
        db.add(SAPropertyItem(property_id=prop.id, job_id=job.id, on=f.get("period_to"), heading="RES_FINANCE",
                              description=f"Mortgage interest ({f.get('lender') or 'lender'})"[:255],
                              amount=f.get("interest_year", f["interest"]), doc_id=doc.id))
    db.commit()
