"""U-REC-002 Exchange difference on a foreign currency bank account, posted to the FX code by a named journal
(FRS 102 s30.9: monetary items are translated at the closing rate and the difference goes to profit or loss;
BIM39510 / 39520).

When the accountant types the statement balance in its currency and the year-end rate (control accounts screen, F3
tab), the books' sterling balance is set against the statement at that rate; the difference is the exchange gain or
loss of the year: Dr the bank / Cr 3562 for a gain, the reverse for a loss. A statement typed only in sterling stays a
question (U-REC-001): its difference may be missing lines, not exchange."""

from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, ProposedJournal, TBRecord
from backend.app.services.reconciliation.common import TOLERANCE, bank_currency, entered_inputs, statement_balance

FX_CODE = 3562


def currency_entry(entered: Dict) -> bool:
    """Typed in the account's currency with the year-end rate (not a sterling figure)."""
    return bool(entered) and entered.get("balance") is None and entered.get("currency_amount") is not None \
        and bool(entered.get("rate"))


def fx_journals(engagement: ClientEngagement, tb_records: List[TBRecord], chart, db: Session,
                counter: List[int]) -> Tuple[List[AuditFinding], List[ProposedJournal]]:
    from backend.app.services.review.yearend_journals import _entry, _journal, _point
    from backend.app.services.tax.ct_computation import final_balances
    inputs = entered_inputs(db, engagement.id)
    typed = {int(k.split(":")[1]): v for k, v in inputs.items()
             if k.startswith("bank:") and k.split(":")[1].isdigit() and currency_entry(v)
             and not v.get("agreed") and not str(v.get("note") or "").strip()}
    if not typed:
        return [], []
    bal = final_balances(str(engagement.id), tb_records, db)
    names: Dict[int, str] = {}
    for t in tb_records:
        if t.std_code in typed:
            names.setdefault(int(t.std_code), t.raw_account_name or chart.name(t.std_code))
    findings, journals = [], []
    for code, entered in sorted(typed.items()):
        label = names.get(code, chart.name(code))
        currency = bank_currency(label) or "the currency"
        statement = statement_balance(entered)
        books = round(bal.get(code, 0.0), 2)
        diff = round(statement - books, 2)          # + : the bank is worth more in sterling (a gain)
        if abs(diff) < TOLERANCE:
            continue
        dr, cr = (code, FX_CODE) if diff > 0 else (FX_CODE, code)
        entry = _entry(dr, cr, abs(diff), chart)
        word = "gain" if diff > 0 else "loss"
        point = _point(
            engagement, "U-REC-002", "Bank: exchange difference",
            f"{label[:70]}: exchange {word} of £{abs(diff):,.2f} at the year-end rate",
            (f"The statement typed for {label} ({code}) is {float(entered['currency_amount']):,.2f} {currency} at "
             f"{float(entered['rate'])} to £1 = £{statement:,.2f}; the books hold £{books:,.2f}. A foreign currency "
             f"balance is retranslated at the closing rate and the difference is the year's exchange {word} (FRS 102 "
             f"s30.9; BIM39520). A journal is proposed (Journals tab): {entry}. Reject it if lines are missing from "
             f"the books instead (then the statement's currency balance and the books' currency balance differ)."),
            abs(diff), entry)
        findings.append(point)
        journals.append(_journal(engagement, counter, f"Exchange {word} on {label[:80]} at the year-end rate",
                                 dr, cr, abs(diff), chart, point))
    return findings, journals
