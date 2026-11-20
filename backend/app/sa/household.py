"""Household links between a firm's Self Assessment clients for the same year (R-IN-06): clients who share a
home or joint items, so each joint item is counted once and split by ownership. Found from what the returns hold:

  named       another client is named on this client's documents (a joint account holder, a co-landlord or
              borrower, a shareholder, a P60 put in the wrong folder)
  spouse      the spouse named on Family and loans is another client
  property    the same let property is on both returns (the shares should add up to the whole)
  postcode    the same postcode on both clients' bank statements"""

import json
import re
from typing import Dict, List

from backend.app.sa.extract.letting import same_property
from backend.app.sa.extract.p60 import owner

NAME_FIELDS = ("holders", "landlords", "borrowers")
ONE_NAME = ("employee", "shareholder", "carer", "person", "subcontractor", "name")


def _postcode(v) -> str:
    return re.sub(r"\s", "", (v or "").upper())


def _names(db, job) -> List[str]:
    from backend.app.sa.models import SADocument
    out = []
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.fields.isnot(None)):
        try:
            f = json.loads(d.fields)
        except ValueError:
            continue
        for k in NAME_FIELDS:
            out += [n for n in f.get(k) or [] if isinstance(n, str)]
        out += [f[k] for k in ONE_NAME if isinstance(f.get(k), str) and f.get(k)]
    return out


def _postcodes(db, job) -> set:
    from backend.app.sa.models import SADocument
    found = set()
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "BANK_STATEMENT",
                                         SADocument.fields.isnot(None)):
        pc = _postcode(json.loads(d.fields).get("postcode"))
        if len(pc) >= 5:
            found.add(pc)
    return found


def _same_person(a: str, b: str) -> bool:
    return owner(a, b) is None and owner(b, a) is None


def links(db, job) -> List[Dict]:
    """The firm's other clients for the same year linked to this one, each with why."""
    from backend.app.sa.models import SAFamily, SAJob, SAProperty
    others = db.query(SAJob).filter(SAJob.owner_user_id == job.owner_user_id, SAJob.tax_year == job.tax_year,
                                    SAJob.id != job.id).all()
    if not others:
        return []
    names = _names(db, job)
    fam = db.get(SAFamily, job.id)
    props = [p.name for p in db.query(SAProperty).filter(SAProperty.job_id == job.id)]
    codes = _postcodes(db, job)
    out = []
    for o in others:
        why = []
        if any(_same_person(n, o.person_name) for n in names):
            why.append(f"{o.person_name} is named on this client's documents")
        if fam is not None and fam.spouse_name and _same_person(fam.spouse_name, o.person_name):
            why.append("they are the spouse named on Family and loans")
        theirs = [p.name for p in db.query(SAProperty).filter(SAProperty.job_id == o.id)]
        shared = sorted({p for p in props for q in theirs if same_property(p, q)})
        if shared:
            why.append(f"both returns have {', '.join(shared)}: the shares should add up to the whole")
        if codes and codes & _postcodes(db, o):
            why.append("their bank statements give the same postcode")
        if why:
            out.append({"job_id": o.id, "person": o.person_name, "why": why})
    return out
