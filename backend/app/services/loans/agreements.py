"""The loans register's agreements with their schedules, and each linked to its accounts in the ledger by the lender's
name ('Acme Finance term loan' to '899 - Acme Finance Loan £30,000'). Used by the loans tabs (G4) and the review's
year-end loan journals."""

import re
from datetime import date
from typing import Dict, List, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.services.loans.schedule import Agreement, Schedule, schedule

# Words every loan name has: they say nothing about which lender it is
GENERIC = {"loan", "loans", "bank", "hp", "hire", "purchase", "ltd", "limited", "account", "finance", "the", "and",
           "of", "plc", "agreement", "term", "business", "brought", "forward", "creditors", "less", "than", "year",
           "years", "between", "after", "within", "other", "example", "lease", "leasing", "uk", "co"}


def name_words(text: str) -> Set[str]:
    # '£30,000' is one word (the amount tells two loans with the same lender apart)
    text = re.sub(r"(?<=\d),(?=\d{3})", "", (text or "").lower())
    return {w for w in re.findall(r"[a-z0-9]+", text)
            if w not in GENERIC and (len(w) >= 3 or w.isdigit() and len(w) >= 4) and not re.fullmatch(r"\d{1,3}", w)}


def agreement_schedules(engagement, db: Session) -> List[Tuple[Agreement, Schedule]]:
    """Each agreement on the uploaded loans register with its schedule at the year end."""
    from backend.app.models.loan_agreements import LoanAgreement
    if engagement.period_end_date is None:
        return []
    ye: date = engagement.period_end_date
    pye = engagement.prior_period_end_date or date(ye.year - 1, ye.month, min(ye.day, 28) if ye.month == 2 else ye.day)
    out = []
    num = lambda v: None if v is None else float(v)
    for a in db.query(LoanAgreement).filter(LoanAgreement.engagement_id == engagement.id).order_by(LoanAgreement.id):
        agreement = Agreement(lender=a.lender, kind=a.kind or "", drawdown=a.drawdown, first_payment=a.first_payment,
                              amount=float(a.amount), deposit=float(a.deposit or 0), payments=int(a.payments),
                              per_year=int(a.per_year or 12), rate=num(a.rate), charge=num(a.charge),
                              payment=num(a.payment), balloon=float(a.balloon or 0), method=a.method or "Actuarial")
        try:
            out.append((agreement, schedule(agreement, ye, pye)))
        except (ZeroDivisionError, ValueError, OverflowError):
            continue                     # terms that do not make a schedule (no payments): left out
    return out


def link(schedules: List[Tuple[Agreement, Schedule]], names: Sequence[str]) -> Dict[int, int]:
    """{agreement index: name index}, each name used once (the best match first)."""
    pairs = []
    for i, (a, _) in enumerate(schedules):
        want = name_words(a.lender)
        for j, n in enumerate(names):
            score = len(want & name_words(n))
            if score:
                pairs.append((score, i, j))
    out: Dict[int, int] = {}
    used = set()
    for score, i, j in sorted(pairs, reverse=True):
        if i not in out and j not in used:
            out[i] = j
            used.add(j)
    return out


def last_year_loans(engagement) -> Dict[str, float]:
    """{lender as last year's working paper names it: owed at last year's end}, read when the paper was uploaded
    (ingestion/last_year_adjustments.loans_carried_forward): each lender's share of a balance last year's TB keeps by
    code only."""
    import json
    try:
        inputs = json.loads(getattr(getattr(engagement, "profile", None), "tax_inputs", None) or "{}")
    except ValueError:
        return {}
    got = (inputs.get("_last_year_wp") or {}).get("loans_cf") or {}
    return {str(k): float(v) for k, v in got.items() if isinstance(v, (int, float)) and abs(v) >= 1}
