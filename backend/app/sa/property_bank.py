"""Rent found in the person's own bank accounts (R-SA105-01, -11): a landlord with no letting agent is paid straight
into the bank, and the firm's working paper then takes the rent received there ('used bank'), payer by payer. Rent is
taken as received (the cash basis, ITTOIA 2005 s271A, is the default for property income up to £150,000).

What counts: money in during the tax year with rent words on the line ('SMITH JG RENT', 'TENANCY'), and a letting
agent's payment the agent's statements do not cover (a month whose statement is not in the folder). Left out: what an
agent's statement already gives, and lines already on a property. Nothing goes on the return by itself: the accountant
adds each payer to its property on the Property page (which property a tenant pays for is not on the bank line)."""

import re
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.sa import books

# The words around a payer's name that are not the payer: bank codes, 'rent', months
NOT_PAYER = re.compile(r"\b(cr|bp|fpi|fp|so|bgc|bacs|dd|tfr|ref|rent(al)?|for|the|month|sent from monzo|"
                       r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|june?|july?|aug(ust)?|sept?(ember)?|oct(ober)?|"
                       r"nov(ember)?|dec(ember)?)\b", re.I)
AGENT_WORDS = re.compile(r"[a-z]{4,}")
AGENT_COMMON = {"sales", "lettings", "letting", "estate", "estates", "agents", "agent", "property", "properties",
                "limited", "management", "homes", "residential", "group"}


def payer_of(description: str) -> str:
    """The payer's name from a bank line ('CR SMITH JG RENT' and 'SMITH JG APRIL RENT' are both SMITH JG)."""
    s = re.sub(r"[\d@:/*&.,'-]+", " ", description or "")
    s = NOT_PAYER.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().upper()[:60] or (description or "").strip().upper()[:60]


def _agents(db: Session, job) -> List[Dict]:
    """The letting agents on the person's statements, each with the words of its name and the properties it lets."""
    import json
    from backend.app.sa.models import SADocument
    out: Dict[str, Dict] = {}
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "LETTING_STATEMENT",
                                         SADocument.status.in_(("READ", "CHECK", "OTHER_YEAR"))):
        f = json.loads(d.fields) if d.fields else {}
        if not f.get("agent") or f.get("other_person"):
            continue
        a = out.setdefault(f["agent"], {"agent": f["agent"], "properties": set(), "periods": [],
                                        "words": set(AGENT_WORDS.findall(f["agent"].lower())) - AGENT_COMMON})
        a["properties"].update(p["address"] for p in f.get("properties") or [] if p.get("address"))
        try:
            a["periods"].append((date.fromisoformat(f["period_from"]), date.fromisoformat(f["period_to"])))
        except (KeyError, TypeError, ValueError):
            pass
    return [a for a in out.values() if a["words"]]


def found(db: Session, job) -> List[Dict]:
    """The rent in the bank not yet on a property, by payer: [{payer, total, lines, why, property}] (property: the one
    the agent lets, when its statements name just one)."""
    from backend.app.sa.income import tax_year_dates
    from backend.app.sa.models import SAProperty, SAPropertyItem
    start, end = (x.isoformat() for x in tax_year_dates(job.tax_year))
    agents = _agents(db, job)
    paid_over = books.remittances(db, job)
    have = {(i.on, round(float(i.amount), 2)) for i in db.query(SAPropertyItem).filter(SAPropertyItem.job_id == job.id,
                                                                                       SAPropertyItem.heading == "RENT")}
    props = {p.name: p.id for p in db.query(SAProperty).filter(SAProperty.job_id == job.id, SAProperty.country.is_(None))}
    groups: Dict[str, Dict] = {}
    for acct, _bank, a in books.accounts(db, job):
        for l in a.lines:
            if not l.money_in or l.money_in <= 0 or not l.on or not (start <= l.on <= end):
                continue
            if books.NOT_TRADE_IN.search(l.description):
                continue                                     # a benefit paid for a tenant is not the landlord's rent
            words = set(AGENT_WORDS.findall(l.description.lower()))
            agent = next((g for g in agents if g["words"] & words), None)
            if agent is None and not books.RENT_IN.search(l.description):
                continue
            when = date.fromisoformat(l.on)
            if agent and (any(abs(amt - l.money_in) <= 1 and abs((d - when).days) <= books.REMIT_DAYS for d, amt in paid_over)
                          or any(f <= when <= date.fromordinal(t.toordinal() + books.REMIT_DAYS) for f, t in agent["periods"])):
                continue                                     # the agent's statement for this month gives it
            if (l.on, round(l.money_in, 2)) in have:
                continue                                     # on a property already
            payer = agent["agent"] if agent else payer_of(l.description)
            g = groups.setdefault(payer, {"payer": payer, "total": 0.0, "lines": [], "property": None,
                                          "why": ("paid by the letting agent with no statement for the month: net of "
                                                  "its fees (ask for the statement)") if agent else "rent words on the line"})
            if agent and len(agent["properties"]) == 1:
                name = next(iter(agent["properties"]))
                from backend.app.sa.extract.letting import same_property
                g["property"] = next((pid for n, pid in props.items() if same_property(n, name)), None)
            g["lines"].append({"key": books.key_of(l.on, l.description, l.money_in, l.money_out, l.balance),
                               "account": acct, "on": l.on, "description": l.description, "amount": l.money_in,
                               "doc_id": l.doc_id})
            g["total"] = round(g["total"] + l.money_in, 2)
    return sorted(groups.values(), key=lambda g: -g["total"])


def add(db: Session, job, keys: List[str], property_id: Optional[int] = None, name: Optional[str] = None) -> int:
    """The chosen bank lines as rent on a property (a new one named `name` when no property is given). Returns the
    property's id."""
    from backend.app.sa.models import SAProperty, SAPropertyItem
    lines = [l for g in found(db, job) for l in g["lines"] if l["key"] in set(keys)]
    if property_id is None:
        prop = SAProperty(job_id=job.id, name=(name or "Rent in the bank")[:255],
                          note="Added from the rent in the bank: confirm the address, owner and share.")
        db.add(prop)
        db.flush()
        property_id = prop.id
    for l in lines:
        db.add(SAPropertyItem(property_id=property_id, job_id=job.id, on=l["on"], heading="RENT", amount=l["amount"],
                              description=f"Rent in the bank: {l['description']}"[:255], doc_id=l["doc_id"]))
    db.commit()
    return property_id
