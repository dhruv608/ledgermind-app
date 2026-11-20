"""Moves a loan account mapped to the director's loan account (5400) to Other loans (5110) when it is named for someone
who is not a director (e.g. 'J Smith - Loan', a loan from a friend of the business), and flags it for a check. Runs once
the directors are known from Companies House. Codes the accountant confirmed, remembered or carried from last year are
left alone."""

import json
import re
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.models.database import ClientProfile, MasterCOA, TBRecord

DLA_CODES = (5400, 5401)
OTHER_LOANS = 5110
LOAN = re.compile(r"\bloans?\b", re.I)
DIRECTOR_WORDS = re.compile(r"\b(?:director|directors|dla|drawings?|capital|current|shareholder|owner|personal)\b", re.I)
# The person's name: the account name without 'loan', separators and words that are not a name
NOT_NAME = re.compile(r"\b(?:loans?|account|a/c|from|to|the|and|ltd|limited|mr|mrs|ms|miss|dr)\b|[^a-z' -]", re.I)


def _person(name: str) -> Optional[str]:
    rest = re.sub(r"\s+", " ", NOT_NAME.sub(" ", name or "")).strip(" -")
    words = rest.split()
    if not 1 <= len(words) <= 3 or not all(re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", w) for w in words):
        return None
    # An initial and a surname ('J Smith') or a first name and a surname
    return rest if len(words) >= 2 else None


def _is_director(person: str, directors: List[str]) -> bool:
    p = [w.lower() for w in re.findall(r"[A-Za-z']+", person)]
    for d in directors:
        q = [w.lower() for w in re.findall(r"[A-Za-z']+", d)]
        if q and p and p[-1] == q[-1] and (p[0] == q[0] or p[0][0] == q[0][0]):
            return True
    return False


def move_non_director_loans(engagement_id: str, db: Session) -> int:
    profile = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement_id).first()
    directors = [d for d in (json.loads(profile.directors or "[]") if profile else []) if d]
    if not directors:
        return 0                                   # who the directors are is not known: leave the mapping
    target = db.get(MasterCOA, OTHER_LOANS)
    if target is None:
        return 0
    moved = 0
    for t in db.query(TBRecord).filter(TBRecord.engagement_id == engagement_id, TBRecord.std_code.in_(DLA_CODES)):
        if t.mapping_status == "MATCHED" and (t.match_source or "") != "AI":
            continue                               # the accountant's, remembered or last year's code
        name = t.raw_account_name or ""
        if not LOAN.search(name) or DIRECTOR_WORDS.search(name):
            continue
        person = _person(name)
        if not person or _is_director(person, directors):
            continue
        t.std_code, t.std_name = OTHER_LOANS, target.std_name
        t.mapping_status, t.match_source = "NEEDS_REVIEW", "RULE"
        t.mapping_reason = (f"Check: a loan from {person}, who is not a director ({', '.join(directors)[:120]}): "
                            f"other loans (5110), not the director's loan account.")
        moved += 1
    if moved:
        db.commit()
    return moved
