"""Dividends paid into the person's own bank with no voucher on the return (R-SAV-04, R-DIR-01): the bank shows the money,
but the dividend declared (from the voucher, or the company's own books for the client's company) is what goes on the
return. A point per company for the accountant, with the bank's total; nothing is put on the return from the bank."""

import re
from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.sa import books

DIVIDEND_IN = re.compile(r"\bdividends?\b", re.I)
NOT_NAME = re.compile(r"\b(cr|bp|fpi|fp|bgc|bacs|dividends?|ltd|limited|plc)\b", re.I)


def payer_of(description: str) -> str:
    s = NOT_NAME.sub(" ", re.sub(r"[\d@:/*.,'-]+", " ", description or ""))
    return re.sub(r"\s+", " ", s).strip().upper()[:60]


def _words(name: str) -> set:
    return set(re.findall(r"[a-z]{3,}", (name or "").lower())) - {"and", "the", "ltd", "limited", "plc", "dividend", "dividends"}


def found(db: Session, job) -> List[Dict]:
    """[{payer, total, count}] for dividends in the bank in the tax year from a payer no dividend line on the return names."""
    from backend.app.sa.income import tax_year_dates
    from backend.app.sa.models import SALine
    start, end = (x.isoformat() for x in tax_year_dates(job.tax_year))
    on_return = [_words(l.label) for l in db.query(SALine).filter(SALine.job_id == job.id, SALine.source == "DIVIDENDS")]
    out: Dict[str, Dict] = {}
    for _acct, _bank, a in books.accounts(db, job):
        for l in a.lines:
            if not l.money_in or l.money_in <= 0 or not l.on or not (start <= l.on <= end) or not DIVIDEND_IN.search(l.description):
                continue
            payer = payer_of(l.description)
            if any(_words(payer) & w for w in on_return):
                continue                                     # a voucher or the company's books give it already
            g = out.setdefault(payer, {"payer": payer, "total": 0.0, "count": 0})
            g["total"] = round(g["total"] + l.money_in, 2)
            g["count"] += 1
    return sorted(out.values(), key=lambda g: -g["total"])
