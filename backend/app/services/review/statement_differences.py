"""U-REC-001 A balance the accountant typed from its document (bank or card statement, supplier or lender statement,
any balance sheet account on the control accounts screen) that does not agree to the books, with no explanation:
a query (the difference is shown and named; an unexplained one is queried).

The books are the closing balance with the approved journals (as the screen and the ETB show them), debit positive,
the same sign the screen compares the typed figure in. A row ticked as agreed, or typed with a note saying why it
differs, is explained. Accounts with their own statement rule are left to it: PAYE / NI and pension (U-PAY-020 / 021)
and loans (U-LOAN-004). A question only: no journal, since the cause (a missing ledger line, a timing item, an exchange
difference) decides the entry."""

from typing import Dict, List

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement, TBRecord
from backend.app.services.mapping.chart_lookup import PAYE_NIC
from backend.app.services.reconciliation.common import TOLERANCE, bank_currency, entered_inputs, statement_balance
from backend.app.services.review.fx_difference import currency_entry

KINDS = {"bank": "bank statement", "code": "statement / supporting document"}


def _causes(kind: str, currency: str) -> str:
    if kind == "bank":
        extra = (" For a foreign currency account, check the statement balance and the year-end rate typed: what "
                 "is left after them is an exchange gain or loss (3562)." if currency else "")
        return ("Usual causes: bank lines missing from the books or posted twice, cheques or receipts in the books "
                "not yet on the statement (timing items, list them), or a statement balance from the wrong date." + extra)
    return ("Usual causes: an invoice, credit note or payment missing from the books or from the document, an item "
            "in the wrong period, or a figure typed from the wrong date.")


def unexplained_differences(engagement: ClientEngagement, tb_records: List[TBRecord], chart, db: Session,
                            materiality: float) -> List[AuditFinding]:
    from backend.app.services.review.loan_statements import loan_codes
    from backend.app.services.review.paye_check import PENSION_PAYABLE
    from backend.app.services.tax.ct_computation import final_balances
    inputs = entered_inputs(db, engagement.id)
    if not inputs:
        return []
    own_rule = {PAYE_NIC, PENSION_PAYABLE} | set(loan_codes(tb_records))
    names: Dict[int, List[str]] = {}
    for t in tb_records:
        if t.std_code is not None:
            names.setdefault(int(t.std_code), [])
            if t.raw_account_name and t.raw_account_name not in names[int(t.std_code)]:
                names[int(t.std_code)].append(t.raw_account_name)
    bal = None
    out: List[AuditFinding] = []
    for key, entered in sorted(inputs.items()):
        kind, _, code_text = key.partition(":")
        if kind not in KINDS or not code_text.isdigit() or not entered:
            continue
        code = int(code_text)
        if code in own_rule or entered.get("agreed") or str(entered.get("note") or "").strip():
            continue
        if kind == "bank" and currency_entry(entered):
            continue                     # a currency statement at the year-end rate: the exchange journal (U-REC-002)
        statement = statement_balance(entered)
        if statement is None:
            continue
        if bal is None:
            bal = final_balances(str(engagement.id), tb_records, db)
        books = round(bal.get(code, 0.0), 2)
        diff = round(books - statement, 2)
        if abs(diff) < TOLERANCE:
            continue
        label = " / ".join(names.get(code) or []) or chart.name(code)
        where = f"{label} ({code})"
        doc = KINDS[kind]
        currency = bank_currency(label) if kind == "bank" else ""
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-REC-001",
            procedure_name="Control account not agreed", severity="HIGH" if abs(diff) >= materiality else "MEDIUM",
            source_row_ref=where[:100], quantified_amount=abs(diff), status="OPEN",
            finding_title=f"{label[:80]}: books £{books:,.2f} v {doc} £{statement:,.2f}, £{diff:,.2f} not explained"[:255],
            finding_details=(
                f"The books show £{books:,.2f} on {where} at {engagement.period_end_date:%d/%m/%Y} (debit positive, "
                f"after the approved journals); the {doc} figure typed on the control accounts screen is "
                f"£{statement:,.2f}. The £{diff:,.2f} difference has no explanation. {_causes(kind, currency)} "
                f"Post a journal for what belongs in the books, or type the reason against the figure on the control "
                f"accounts screen.\n\nQuery to the client: Please send the {doc} at "
                f"{engagement.period_end_date:%d/%m/%Y} and explain the £{abs(diff):,.2f} difference against the "
                f"books (any items missing, duplicated or in the wrong period).")))
    return out
