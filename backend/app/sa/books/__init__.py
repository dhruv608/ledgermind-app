"""A sole trader's books from the bank statements (the raw data route; cash basis, R-SA103-03,
so money in and out when it is paid). Each line of the business's period is sorted with the firm's bank rules
(services/bank_only/bank_sort.py, the same as for a company with no books), then the firm's head is put under an SA103
heading (trade.py HEADINGS), or out of the business:

  DRAWINGS     money the person takes out, or spends on themselves: not a cost (ITTOIA s34, wholly and exclusively);
               tax paid to HMRC, donations (relieved as Gift Aid on the SA100, not in the trade) and their own pension
  CAPITAL      money the person puts in from their own name: not income
  TRANSFER     money moved between the person's own accounts
  NOT_TRADE    money in that is not the trade's: bank interest (SA100 interest box) and the like
  LOAN         a loan or HP repaid: capital, not a cost; only the interest is (BIM45650), to split by hand
  UNSORTED     no rule fits: the accountant picks (and the AI suggests)

The accountant's choice for a line (sa_bank_choices) is kept by the line's own words, so reading the statements
again keeps it. Totals per heading go into the business as items 'From the bank statements'."""

import json
from typing import Dict

from sqlalchemy.orm import Session

from backend.app.sa.trade import HEADINGS
# Everything callers import from this package
from backend.app.sa.books.rules import (ASK, ASSET, ASSET_SUPPLIER, BARE_TRANSFER, CAPITAL, CAPITAL_PURCHASE,
                                        CAPITAL_TEST, CARD_COST_WORDS, CARD_REFUND, CARD_REPAYMENT, CARD_SUMMARY,
                                        CARD_UNSENT, CAR_BOUGHT, CAR_DEALER, CAR_TRADE, DRAWINGS, DRAWINGS_WORD,
                                        FROM_BANK, INVESTMENT_VALUE, LOAN, LOAN_ADVANCE, LOAN_IN, MIXED, MORTGAGE_IN,
                                        NOT_TRADE, NOT_TRADE_IN, OUTSIDE, OWN_TRANSFER, PAYOUT_PLATFORMS, PAY_CARD_OFF,
                                        PERSONAL_PAYEE, PERSONAL_REGULAR, PLATFORM_FUNDING, PLATFORM_PAYOUT, REMIT_DAYS,
                                        RENT_IN, SAME_MONEY_DAYS, SA_HEADS, TAX, TRANSFER, TURNOVER_HEAD, UNSORTED,
                                        UNSURE, VAT, VAT_IN, VEHICLE_SOLD, WAGES_IN, car_bought, not_for_ai,
                                        platform_of)
from backend.app.sa.books.statements import (AGENT_COMMISSION, AGENT_COMMON, COMPANY_WORDS, PAIR_COMMON, PAIR_DAYS,
                                             PAIR_MIN, PERSON_TITLE, _agent_words, _employer_words, accounts,
                                             employer_in, employers, from_a_person, key_of, label, lets_property,
                                             own_transfer_pairs, payee_word, period, platform_copies, remittances)
from backend.app.sa.books.sort import choices_of, choose, mixed_use, private_use, sort_lines, totals
from backend.app.sa.books.ai import (AI_BATCH, AI_KIND, GENERIC_NAME, _ask, business_context, kept_suggestions,
                                     with_suggestions)


def view(db: Session, job, biz) -> Dict:
    start, end = period(job, biz)
    from backend.app.sa.extract.statement import covers
    accts = accounts(db, job)
    lines = with_suggestions(sort_lines(accts, job.person_name, start, end, choices_of(db, job), remittances(db, job),
                                        employers(db, job), lets=lets_property(db, job)),
                             kept_suggestions(db, job))
    t = totals(lines)
    order = list(HEADINGS) + list(OUTSIDE)
    return {"period": {"start": start, "end": end},
            "accounts": [{"account": acct, "bank": bank, "checks": a.checks + covers(a, start, end)} for acct, bank, a in accts],
            "lines": lines,
            "totals": [{"heading": h, "label": label(h), "amount": t[h],
                        "lines": sum(1 for r in lines if r["heading"] == h),
                        "to_check": sum(1 for r in lines if r["heading"] == h and not r["sure"])}
                       for h in order if h in t],
            "headings": [{"heading": h, "label": label(h)} for h in order],
            "mixed": mixed_use(lines, private_use(db, job, biz))}


def post(db: Session, job, biz) -> int:
    """The totals per SA103 heading into the business, in place of the ones put there before. Lines not sorted stay out.
    The private part of mixed-use costs (the business % given) is the heading's part not allowed."""
    from backend.app.sa.models import SABusinessItem
    lines = sort_lines(accounts(db, job), job.person_name, *period(job, biz), choices_of(db, job), remittances(db, job),
                       employers(db, job), lets=lets_property(db, job))
    db.query(SABusinessItem).filter(SABusinessItem.business_id == biz.id,
                                    SABusinessItem.description == FROM_BANK).delete(synchronize_session=False)
    private: Dict[str, float] = {}
    for m in mixed_use(lines, private_use(db, job, biz)):
        private[m["heading"]] = round(private.get(m["heading"], 0.0) + m["disallowed"], 2)
    n = 0
    for h, amount in totals(lines).items():
        if h in HEADINGS and abs(amount) >= 0.005:
            db.add(SABusinessItem(business_id=biz.id, job_id=job.id, heading=h, description=FROM_BANK, amount=amount,
                                  disallowed=min(private.get(h, 0.0), max(amount, 0.0))))
            n += 1
    db.commit()
    return n


def suggest(db: Session, job, biz) -> Dict[str, int]:
    """Asks the AI about the payees of unsorted money out not asked before; {asked, suggested}."""
    from concurrent.futures import ThreadPoolExecutor
    from backend.app.models.ai_answers import AIAnswer
    from backend.app.services.bank_only.books import payee_key
    lines = sort_lines(accounts(db, job), job.person_name, *period(job, biz), choices_of(db, job), remittances(db, job),
                       employers(db, job), lets=lets_property(db, job))
    groups: Dict[str, Dict] = {}
    for r in lines:
        p = payee_key(r["description"])
        if r["heading"] != UNSORTED or r["chosen"] or not r["out"] or not p or not_for_ai(r):
            continue
        g = groups.setdefault(p, {"payee": p, "lines": 0, "out": 0.0, "example": r["description"]})
        g["lines"] += 1
        g["out"] += r["out"]
    kept = kept_suggestions(db, job)
    new = sorted((g for p, g in groups.items() if p not in kept), key=lambda g: -g["out"])[:200]
    business = business_context(db, job, biz)
    batches = [new[i:i + AI_BATCH] for i in range(0, len(new), AI_BATCH)]

    def ask(batch):
        try:
            return _ask(batch, business)
        except Exception:          # no AI (an outage): nothing is guessed, the accountant picks by hand
            return {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(ask, batches))
    n = 0
    for batch, answers in zip(batches, replies):
        for j, g in enumerate(batch):
            if j in answers:
                db.add(AIAnswer(engagement_id=job.id, kind=AI_KIND, key=g["payee"][:300],
                                answer=json.dumps(answers[j]), model=answers[j].get("model")))
                n += 1
    db.commit()
    return {"asked": len(new), "suggested": n}
