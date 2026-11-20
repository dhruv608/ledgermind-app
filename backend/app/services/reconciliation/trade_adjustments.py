"""The Adjustments block under the trade debtors and trade creditors T: the items an accountant looks for between the
control account and what is really owed.

  Debtors                                              Creditors
  Duplicate invoices                                   Duplicate bills
  Receipts recorded directly, invoice still open       Payments recorded directly, bill still open
  Cash sales (received straight to the bank)           Cash payments (paid straight from the bank)
  Opening variance                                     Opening variance

The first two come from the duplicates review (sop/duplicates.py: same number / amount / contact twice, and an invoice or
bill outstanding at the year end with a direct receipt or payment of the same amount); cash sales / payments are the
direct receipts / payments in the ledger (not through debtors or creditors); the opening variance is the control
account's opening and this year's lines against its trial balance closing (the roll-forward's difference)."""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement

TRADE_CODE = {"customer": 4400, "supplier": 5200}
WORDS = {
    "customer": {"duplicate": "Duplicate invoices", "unallocated": "Receipts recorded directly, invoice still open",
                 "direct": "Cash sales (received straight to the bank)"},
    "supplier": {"duplicate": "Duplicate bills", "unallocated": "Payments recorded directly, bill still open",
                 "direct": "Cash payments (paid straight from the bank)"},
}
DETAILS_SHOWN = 8


def trade_adjustments(engagement: ClientEngagement, db: Session, side: str) -> Dict[str, Any]:
    from backend.app.services.papers.rollforward import rollforward
    from backend.app.services.sop.duplicates import duplicate_review, ledger_documents

    words = WORDS[side]
    flags = [f for f in duplicate_review(str(engagement.id), engagement.period_end_date, db) if f.side == side]
    direct = [d for d in ledger_documents(str(engagement.id), db) if d.side == side and d.kind == "direct"]

    def line(key: str, label: str, items: List[Any], amount: float, details: List[str], note: str = "") -> Dict[str, Any]:
        return {"key": key, "label": label, "amount": round(amount, 2), "count": len(items),
                "details": details[:DETAILS_SHOWN], "more": max(0, len(details) - DETAILS_SHOWN), "note": note}

    dupes = [f for f in flags if f.check in ("duplicate", "possible")]
    possible = sum(1 for f in dupes if f.check == "possible")
    unallocated = [f for f in flags if f.check == "unallocated"]
    lines = [
        line("duplicate", words["duplicate"], dupes, sum(f.amount for f in dupes),
             [f"{f.contact}: {f.detail}" for f in dupes],
             f"{possible} of them possible (one with no number)" if possible else ""),
        line("unallocated", words["unallocated"], unallocated, sum(f.amount for f in unallocated),
             [f"{f.contact}: {f.detail}" for f in unallocated]),
        line("direct", words["direct"], direct, sum(d.amount for d in direct),
             [f"{d.when:%d/%m/%Y} {d.contact} £{d.amount:,.2f} ({d.source})"
              for d in sorted(direct, key=lambda d: -d.amount)],
             "for information: not through the control account"),
    ]
    rf = rollforward(engagement, db, [TRADE_CODE[side]])
    variance = rf.get("difference")
    lines.append({"key": "opening", "label": "Opening variance", "amount": None if variance is None else round(variance, 2),
                  "count": 0, "details": [], "more": 0,
                  "note": ("last year's figures not known" if variance is None
                           else "the ledger follows on from last year's closing balance" if abs(variance) < 0.005
                           else "last year's closing and this year's lines do not reach the trial balance")})
    return {"side": side, "lines": lines}
