"""A small balance sheet for a sole trader whose figures come from the bank, as a company's accounts are built
(bank uploaded and coded, a profit and loss and a small balance sheet, then the return). It is the
Self-employment (full) page SEF 5 (HS229, information from your accounts): what the business has at the period end
and the capital account that explains it.

  assets          each bank account's balance at the period end (from the statement lines inside the period)
  capital account opening capital (the bank balances at the start) + the profit from the bank + money the person put
                  in (capital introduced, and personal money paid into the account) - drawings (and personal spending
                  from it) = closing capital
  check           closing capital = net assets. Every line of every statement is in one of the two, so a difference
                  means a statement missing for part of the period, or lines not sorted yet: the same proof as a
                  company's trial balance check

On the cash basis there are no debtors, creditors or stock to bring in. Fixed assets are the accountant's (capital
allowances), so they are not guessed from the bank."""

from typing import Dict, List, Optional

from sqlalchemy.orm import Session


def _balance_at(lines, start: str, end: str, account) -> Dict[str, Optional[float]]:
    """The account's balance at the start and at the end of the period, from the printed balances of its lines."""
    inside = [l for l in lines if l.on and start <= l.on <= end]
    opening = closing = None
    with_bal = [l for l in inside if l.balance is not None]
    if with_bal:
        first, last = with_bal[0], with_bal[-1]
        opening = round(first.balance - first.money_in + first.money_out, 2)
        closing = round(last.balance, 2)
    else:
        opening, closing = account.opening, account.closing
    return {"opening": opening, "closing": closing}


def build(db: Session, job, biz) -> Dict:
    """{period, assets, capital, check} for the business (one business: its bank accounts are the person's statements)."""
    from backend.app.sa import books
    from backend.app.sa.trade import HEADINGS
    start, end = books.period(job, biz)
    accts = books.accounts(db, job)
    view = books.view(db, job, biz)
    view_lines = view["lines"]
    assets: List[Dict] = []
    opening = 0.0
    missing = []
    for acct, bank, a in accts:
        b = _balance_at(a.lines, start, end, a)
        if b["closing"] is None or b["opening"] is None:
            # No balances printed (a download with paid in and out only, the client's own sheet): its movement in the
            # period stands for it, so the check still proves the rest
            # (the lines the trade uses: a sheet's line the bank also shows is counted once, there)
            moved = round(sum(l["in"] - l["out"] for l in view_lines if str(l["account"]) == str(acct)), 2)
            missing.append(f"{bank or 'Bank'} {acct}")
            assets.append({"name": f"{bank or 'Bank'} account {acct} (no balance printed: the movement in the period)",
                           "amount": moved, "movement_only": True})
            continue
        assets.append({"name": f"{bank or 'Bank'} account {acct}", "amount": b["closing"]})
        opening += b["opening"]
    totals = {t["heading"]: t["amount"] for t in view["totals"]}
    income = sum(v for h, v in totals.items() if h in HEADINGS and HEADINGS[h][2] == "income")
    costs = sum(v for h, v in totals.items() if h in HEADINGS and HEADINGS[h][2] == "cost")
    profit = round(income - costs, 2)
    # Money in that is the person's own (capital, benefits, wages paid into the account) and money out that is theirs
    introduced = round(totals.get(books.CAPITAL, 0.0) + max(0.0, totals.get(books.NOT_TRADE, 0.0)), 2)
    drawings = round(totals.get(books.DRAWINGS, 0.0) + totals.get(books.TAX, 0.0)
                     - min(0.0, totals.get(books.NOT_TRADE, 0.0)), 2)
    other = {"Own accounts transfer": totals.get(books.TRANSFER, 0.0), "Loan or HP repaid": totals.get(books.LOAN, 0.0),
             "Loan received": totals.get(books.LOAN_IN, 0.0), "VAT paid or refunded": totals.get(books.VAT, 0.0),
             "Capital assets bought": totals.get(books.ASSET, 0.0),
             "Not sorted yet": round(totals.get(books.UNSORTED, 0.0) + totals.get(books.ASK, 0.0), 2)}
    # (the outside headings' totals are signed as income for capital/not-trade and as costs for the rest: see books.totals)
    closing_capital = round(opening + profit + introduced - drawings - sum(other.values()), 2)
    net_assets = round(sum(x["amount"] for x in assets), 2)
    diff = round(closing_capital - net_assets, 2)
    notes = []
    if missing:
        notes.append("No balance printed for " + ", ".join(missing) + ": shown as its movement in the period; ask for a "
                     "statement with balances for the true figure.")
    if other["Not sorted yet"]:
        notes.append(f"£{abs(other['Not sorted yet']):,.2f} of bank lines are not sorted yet: until they are, the split between "
                     f"profit and drawings is not final.")
    if abs(diff) >= 1:
        notes.append(f"Closing capital and net assets differ by £{diff:,.2f}: a statement is missing for part of the period, "
                     f"or an account in the bank lines has no balances.")
    return {"period": {"start": start, "end": end},
            "assets": assets, "net_assets": net_assets,
            "capital": {"opening": round(opening, 2), "profit": profit, "introduced": introduced, "drawings": drawings,
                        "transfers": round(other["Own accounts transfer"], 2), "loans_repaid": round(other["Loan or HP repaid"], 2),
                        "loans_received": round(other["Loan received"], 2), "vat": round(other["VAT paid or refunded"], 2),
                        "assets_bought": round(other["Capital assets bought"], 2),
                        "unsorted": round(other["Not sorted yet"], 2), "closing": closing_capital},
            "difference": diff, "balances": abs(diff) < 1, "notes": notes}
