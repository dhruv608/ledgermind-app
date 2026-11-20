"""Each bank line sorted under a heading, the totals per heading, the accountant's own choices and private use."""

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.sa.trade import HEADINGS
from backend.app.sa.books.rules import (ASSET, ASSET_SUPPLIER, BARE_TRANSFER, CAPITAL, CAPITAL_PURCHASE, CAPITAL_TEST,
                                        CARD_COST_WORDS, CARD_REFUND, CARD_REPAYMENT, CARD_SUMMARY, CARD_UNSENT,
                                        CAR_TRADE, DRAWINGS, DRAWINGS_WORD, INVESTMENT_VALUE, LOAN_ADVANCE, LOAN_IN,
                                        MIXED, MORTGAGE_IN, NOT_TRADE, NOT_TRADE_IN, OWN_TRANSFER, PAYOUT_PLATFORMS,
                                        PAY_CARD_OFF, PLATFORM_FUNDING, PLATFORM_PAYOUT, REMIT_DAYS, RENT_IN,
                                        SAME_MONEY_DAYS, SA_HEADS, TRANSFER, TURNOVER_HEAD, UNSORTED, UNSURE, VAT,
                                        VAT_IN, VEHICLE_SOLD, WAGES_IN, car_bought)
from backend.app.sa.books.statements import (_agent_words, _employer_words, employer_in, from_a_person, key_of,
                                             own_transfer_pairs, payee_word)


def sort_lines(accts, person: str, start: str, end: str, choices: Optional[Dict[str, str]] = None,
               paid_over: Optional[List[Tuple[date, float]]] = None, employer_names: Optional[List[str]] = None,
               lets: bool = False) -> List[Dict]:
    """Every line of the period with its heading: the accountant's choice first, else the firm's rules."""
    from backend.app.services.bank_only.bank_sort import sort_bank
    from backend.app.services.bank_only.input_files import BankAccount, BankLine, RawInput
    choices = choices or {}
    emp_words = _employer_words(employer_names or [])
    agent_words = _agent_words(accts)
    # The person's family name: money in from someone of that name is family money, not takings, until checked
    words = [w for w in re.findall(r"[A-Za-z]+", person or "") if w.lower() not in ("e2e", "mr", "mrs", "ms", "miss", "dr")]
    surname = words[-1] if len(words) >= 2 and len(words[-1]) > 2 else None
    raw = RawInput(client_name=person, year_end=date.fromisoformat(end), opening_bank=None)
    keep: Dict[int, Tuple[str, object]] = {}
    # The bank's own lines (a page with balances), by amount and way, for the lines on a sheet with no balances
    on_bank: Dict[Tuple[float, bool], List[date]] = {}
    for _acct, _bank, a in accts:
        for l in a.lines:
            if not getattr(l, "no_balance", False) and l.on:
                try:
                    on_bank.setdefault((round(l.money_in or l.money_out, 2), l.money_in > 0), []).append(date.fromisoformat(l.on))
                except ValueError:
                    pass
    for acct, _bank, a in accts:
        ba = BankAccount(name=str(acct), opening=a.opening, year_end=date.fromisoformat(end))
        for n, l in enumerate(a.lines):
            if not l.on or not (start <= l.on <= end):
                continue
            try:
                when = date.fromisoformat(l.on)
            except ValueError:
                continue
            if getattr(l, "no_balance", False) and any(
                    abs((when - d).days) <= SAME_MONEY_DAYS for d in on_bank.get((round(l.money_in or l.money_out, 2), l.money_in > 0), [])):
                continue                                        # the bank shows the same money: counted there
            b = BankLine(row=n + 1, when=when, description=l.description, money_out=l.money_out, money_in=l.money_in,
                         balance=l.balance, kind="", refs=[], account=str(acct), ref=f"{acct}:{n + 1}")
            ba.lines.append(b)
            raw.bank.append(b)
            keep[id(b)] = (acct, l)
        raw.accounts.append(ba)
    # The person is the 'director': their own name on a line is their own money (drawings or capital)
    sort = sort_bank(raw, directors=[person])
    investments = {str(acct) for acct, _bank, a in accts if any(INVESTMENT_VALUE.search(l.description or "") for l in a.lines)}
    # What went to and came back from each payee in the period: 'money back' more than was ever paid is not a refund
    paid_to: Dict[str, float] = {}
    back_from: Dict[str, float] = {}
    for _acct, _bank, a in accts:
        for x in a.lines:
            if x.on and start <= x.on <= end and (p := payee_word(x.description)):
                paid_to[p] = paid_to.get(p, 0.0) + (x.money_out or 0)
                back_from[p] = back_from.get(p, 0.0) + (x.money_in or 0)
    reported = {str(acct)[:-len(" report")] for acct, _bank, _a in accts if str(acct).endswith(" report")}
    # The card's own statements are here (its repayment lines or monthly summary): its purchases are on them, so paying
    # the card off from the bank is not a cost again. With none sent, the payment to the card is the only record
    card_statements = any(CARD_REPAYMENT.search(x.description or "") or CARD_SUMMARY.search(x.description or "")
                          for _acct, _bank, a in accts for x in a.lines)
    paired = own_transfer_pairs(sort.lines, keep)
    out = []
    for s in sort.lines:
        acct, l = keep[id(s.line)]
        k = key_of(l.on, l.description, l.money_in, l.money_out, l.balance)
        heading = SA_HEADS.get(s.head, UNSORTED)
        how, sure = s.how, s.sure and s.head not in UNSURE
        if id(s.line) in paired:
            heading, how, sure = TRANSFER, ("money between the person's own accounts: the same amount out of one and into "
                                            "another within two days"), True
        elif str(acct) in investments:
            heading, how, sure = NOT_TRADE, "an investment account's statement (its value going up and down): not the trade's", True
        elif getattr(l, "currency", None):
            # An account in another currency (an Irish account in euros): its money is not the UK trade's in pounds. What
            # it earns is foreign income, on the foreign pages at HMRC's exchange rate (SA106, R-SA106-01)
            heading, how, sure = NOT_TRADE, (f"an account in {l.currency}: not the UK trade's figures in pounds. Its income goes "
                                             f"on the foreign pages at HMRC's exchange rate (SA106)"), True
        if heading == DRAWINGS and s.line.money_in > 0:
            heading = CAPITAL if s.head in ("Director's loan", "Personal (director's loan)") else UNSORTED
            # The surname alone may be a relative's money (a gift or a loan), not the person's own: to check
            sure = False
        if s.line.money_out > 0 and heading == UNSORTED and DRAWINGS_WORD.search(l.description):
            heading, how, sure = DRAWINGS, "the line says drawings", True
        # A selling platform's payout (eBay, Etsy, Amazon, PayPal, a card machine) is the seller's takings, not a refund
        # of its fees, unless the line says refund
        if (s.line.money_in > 0 and heading in HEADINGS and HEADINGS[heading][2] == "cost"
                and set(re.findall(r"[a-z]{3,}", l.description.lower())) & PAYOUT_PLATFORMS
                and not re.search(r"refund|reversal|chargeback", l.description, re.I)):
            heading, how, sure = TURNOVER_HEAD, "a payout from a selling platform or card machine: takings", True
        # With the platform's own report sent, its sales are the takings there (gross, fees as costs): its payout to the
        # bank is the same money moved, not takings again (one money, one place)
        platform = getattr(l, "platform", None)
        payee = payee_word(l.description)
        if (s.line.money_in > 0 and heading in HEADINGS and HEADINGS[heading][2] == "cost" and (how or "").startswith("refund")
                and payee and back_from.get(payee, 0) > paid_to.get(payee, 0) + 1):
            # More came back from the payee than was ever paid to them: not a refund (an app paying a driver)
            heading, how, sure = UNSORTED, "money in from a payee, more than was ever paid to them: not a refund. Takings?", False
        if CARD_SUMMARY.search(l.description or ""):
            heading, how, sure = TRANSFER, "the card statement's summary of the month: the total of its lines, not a payment", True
        elif (s.line.money_out > 0 and card_statements and heading in (UNSORTED, DRAWINGS, "FINANCE", "OTHER", "LOAN_INTEREST")
              and PAY_CARD_OFF.search(l.description or "") and not CARD_COST_WORDS.search(l.description or "")):
            heading, how, sure = TRANSFER, "paying off a credit card: own money moved (the card's purchases are the costs)", True
        elif (s.line.money_out > 0 and not card_statements and heading in (UNSORTED, DRAWINGS, "FINANCE", "OTHER", "LOAN_INTEREST")
              and PAY_CARD_OFF.search(l.description or "") and not CARD_COST_WORDS.search(l.description or "")):
            heading, how, sure = UNSORTED, f"{CARD_UNSENT} (its purchases are the costs, the payment is not one)", False
        elif ((heading == UNSORTED or heading in HEADINGS and HEADINGS[heading][2] == "cost")
              and car_bought(l.description, s.line.money_out)):
            # Unsorted too: otherwise the AI is asked and sorts the car into travel
            heading, how, sure = ASSET, (f"a vehicle bought: {CAPITAL_PURCHASE}. A car is never a cost (capital allowances, "
                                            f"ITTOIA 2005 s33A); a van on the cash basis can be: the accountant says which"), False
        elif (s.line.money_in > 0 and heading in HEADINGS and HEADINGS[heading][2] == "cost"
                and WAGES_IN.search(l.description or "")):
            # Wages, a pension or a benefit paid in is never a refund of a cost (it would lower the costs and lift the
            # profit): it is not the trade's money at all
            heading, how, sure = NOT_TRADE, "wages, a pension or a benefit paid in: not the trade's, not a refund of a cost", True
        elif s.line.money_in > 0 and heading == TURNOVER_HEAD and VEHICLE_SOLD.search(l.description or ""):
            heading, how, sure = UNSORTED, "money for a vehicle (its sale or a deposit on it): capital, not takings?", False
        elif heading in (TURNOVER_HEAD, CAPITAL, UNSORTED, DRAWINGS) and OWN_TRANSFER.search(l.description or ""):
            heading, how, sure = TRANSFER, "money between the person's own accounts (the bank says internal transfer)", True
        elif s.line.money_in > 0 and CARD_REPAYMENT.search(l.description or ""):
            heading, how, sure = TRANSFER, "paying off the credit card: the person's own money, not takings", True
        elif platform and s.line.money_in > 0 and PLATFORM_FUNDING.search(l.description or ""):
            heading, how, sure = TRANSFER, f"money put into the {platform} account from the person's own card or bank", True
        elif platform and s.line.money_out > 0 and PLATFORM_PAYOUT.search(l.description or ""):
            heading, how, sure = TRANSFER, f"{platform}'s payout to the bank: the seller's own money moved", True
        elif (not platform and s.line.money_in > 0 and heading == CAPITAL and not reported
              and set(re.findall(r"[a-z]{3,}", (l.description or "").lower())) & PAYOUT_PLATFORMS
              and not re.search(r"refund|reversal|chargeback", l.description, re.I)):
            # A platform paying out to the person ('From Paypal*Smith J': their own name is the platform account's):
            # with no platform report sent, the payouts are the only record of the sales
            heading, how, sure = TURNOVER_HEAD, ("a payout from a selling platform in the person's own name: takings from "
                                                 "selling (or their own money moved: check)"), False
        elif (not platform and s.line.money_in > 0 and reported
              and set(re.findall(r"[a-z]{3,}", (l.description or "").lower())) & reported
              and not re.search(r"refund|reversal|chargeback", l.description, re.I)):
            heading, how, sure = TRANSFER, ("paid out by a selling platform whose own report is here: its sales are counted "
                                            "on the report, so this is the same money moved"), True
        if s.line.money_in > 0 and heading in (TURNOVER_HEAD, CAPITAL, UNSORTED):
            if VAT_IN.search(l.description):
                heading, how, sure = VAT, ("a VAT repayment from HMRC: not income when the figures are net of VAT (SOP "
                                           "N7); on the flat rate scheme the accountant decides"), True
            elif LOAN_ADVANCE.search(l.description):
                heading, how, sure = LOAN_IN, "a loan paid in: not income; record the loan (SOP money in table)", False
            elif NOT_TRADE_IN.search(l.description):
                heading, how, sure = NOT_TRADE, "a benefit, pension, wages or refund: not the trade's", True
            elif MORTGAGE_IN.search(l.description):
                heading, how, sure = NOT_TRADE, "mortgage money paid in (an advance or a surplus): a loan or capital, not takings", False
            elif RENT_IN.search(l.description):
                heading, how, sure = NOT_TRADE, "rent from a let property: property income (the Property page), not takings", True
            elif emp_words and (any(len(w & set(re.findall(r"[a-z]{3,}", l.description.lower()))) >= min(2, len(w))
                                    for w in emp_words) or employer_in(l.description, emp_words)):
                heading, how, sure = NOT_TRADE, "wages from the person's employer (its P60 or payslip): not takings", True
            elif agent_words and not str(acct).startswith("file ") and agent_words & set(re.findall(r"[a-z]{4,}", l.description.lower())):
                heading, how, sure = NOT_TRADE, ("paid over by the person's agent: its statements give the fees in full, with "
                                                 "its commission as a cost (not takings twice)"), True
            elif paid_over and any(abs(a - l.money_in) <= 1 and abs((d - date.fromisoformat(l.on)).days) <= REMIT_DAYS
                                   for d, a in paid_over):
                heading, how, sure = NOT_TRADE, "rent paid over by the letting agent (its statement shows it): the Property page, not takings", True
            elif heading == TURNOVER_HEAD and lets and "no sales invoices" in (how or "") and from_a_person(l.description):
                # The person lets property too: money from a person may be a tenant's rent (the Property page), not the
                # trade's takings: the accountant says which
                heading, how, sure = UNSORTED, "a payment from a person while the client also lets property: rent or takings?", False
            elif heading == TURNOVER_HEAD and CARD_REFUND.search(l.description):
                heading, how, sure = NOT_TRADE, "a card refund from a shop: money back, not takings", False
            elif heading == TURNOVER_HEAD and BARE_TRANSFER.match(l.description or ""):
                heading, how, sure = UNSORTED, "a transfer with no payer: whose money?", False
            elif (heading == TURNOVER_HEAD and surname and re.search(rf"\b{re.escape(surname)}\b", l.description, re.I)
                  and not set(re.findall(r"[a-z]{3,}", l.description.lower())) & PAYOUT_PLATFORMS):
                heading, how, sure = NOT_TRADE, "from someone of the same family name: family money, not takings?", False
        if (s.line.money_out >= CAPITAL_TEST and heading in HEADINGS and HEADINGS[heading][2] == "cost"
                and (ASSET_SUPPLIER.search(l.description or "") or CAR_TRADE.search(l.description or ""))):
            ask = (f"£{CAPITAL_TEST:,.0f} or more to an equipment, vehicle or building supplier: is it an asset? Equipment "
                   f"is a cost on the cash basis, cars and buildings are not")
            how, sure = (f"{how}; {ask}" if how else ask), False
        if s.head == "Director's loan":
            how = "the person's own name on the line" if how == "director's name on the line" else how
        if s.head == "Transfer between own accounts" and not s.pair and heading == TRANSFER:
            sure = False
        chosen = choices.get(k)
        out.append({"key": k, "account": acct, "on": l.on, "description": l.description, "in": l.money_in,
                    "out": l.money_out, "doc_id": l.doc_id, "page": l.page,
                    "heading": chosen or heading, "rule": heading, "how": "your choice" if chosen else how,
                    "sure": True if chosen else sure, "chosen": bool(chosen)})
    out.sort(key=lambda r: (r["on"], str(r["account"])))
    return out


def totals(lines: List[Dict]) -> Dict[str, float]:
    """Per heading: money in less money out for income, money out less money in (refunds) for costs."""
    out: Dict[str, float] = {}
    for r in lines:
        h = r["heading"]
        income = h in HEADINGS and HEADINGS[h][2] == "income" or h in (CAPITAL, NOT_TRADE)
        out[h] = round(out.get(h, 0.0) + ((r["in"] - r["out"]) if income else (r["out"] - r["in"])), 2)
    return out


def choices_of(db: Session, job) -> Dict[str, str]:
    from backend.app.sa.models import SABankChoice
    return {c.key: c.heading for c in db.query(SABankChoice).filter(SABankChoice.job_id == job.id)}


def choose(db: Session, job, keys: List[str], heading: Optional[str]) -> None:
    """The accountant's heading for lines (None: back to the rules)."""
    from backend.app.sa.models import SABankChoice
    db.query(SABankChoice).filter(SABankChoice.job_id == job.id, SABankChoice.key.in_(keys)).delete(synchronize_session=False)
    if heading:
        for k in keys:
            db.add(SABankChoice(job_id=job.id, key=k, heading=heading))
    db.commit()


def mixed_use(lines: List[Dict], pcts: Dict[str, Optional[float]]) -> List[Dict]:
    """Costs used partly for personal life, by kind: the amount under its heading, the business %
    given (None: not given yet) and the part not allowed. Only the business share is allowed (ITTOIA 2005 s34(2))."""
    out = []
    for kind, (label, heading, words) in MIXED.items():
        amount = round(sum(l["out"] - l["in"] for l in lines if l["heading"] == heading and words.search(l["description"] or "")), 2)
        if amount >= 1:
            pct = pcts.get(kind)
            out.append({"kind": kind, "label": label, "heading": heading, "amount": amount, "business_pct": pct,
                        "disallowed": round(amount * (100 - pct) / 100, 2) if pct is not None else 0.0})
    return out


def private_use(db: Session, job, biz) -> Dict[str, Optional[float]]:
    """The business % given for each mixed-use kind (kept as answers 'pu:<business>:<kind>')."""
    from backend.app.sa.signals import _answers
    kept = _answers(db, job)
    out: Dict[str, Optional[float]] = {}
    for kind in MIXED:
        a = kept.get(f"pu:{biz.id}:{kind}")
        try:
            out[kind] = float(a.value) if a and a.value not in (None, "") else None
        except ValueError:
            out[kind] = None
    return out
