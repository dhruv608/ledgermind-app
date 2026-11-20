"""
CIS: every CIS amount in the ledger on a cash basis, in its HMRC tax month.

For HMRC, CIS exists when money moves: a deduction belongs to the date the contractor paid the subcontractor, CIS
suffered to the date the customer paid the client, never the invoice date. So:

- a payment or receipt line (Spend Money, Receivable Payment, bank lines) keeps its own date;
- an invoice line (the deduction booked on a bill or sales invoice) takes the date(s) the invoice was paid, found on
  the debtors / creditors control: the receipt with the invoice's reference, else the one paying exactly what was
  left, else the oldest unpaid invoice first; a part payment carries its share of the CIS;
- CIS on invoices still unpaid at the year end is a timing item (it goes to HMRC in the month it is paid); last
  year's unpaid list is the opening timing item (entered on the setup, from last year's CIS working);
- journals are never treated as cash: the reviewer decides.

Proof for each side: CIS in the ledger (invoice basis) + opening unpaid - closing unpaid = cash basis. A difference is
listed as an exception, never plugged.
"""

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, GLTransaction, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.cis.codes import CIS_DEDUCTED, CIS_SUFFERED

TRADE_DEBTORS, TRADE_CREDITORS = 4400, 5200

PAYMENT = re.compile(r"spend money|expense|bill payment|payable payment|supplier payment|purchase payment|\bbp\b|\bpp\b|bank payment|cheque|direct debit|card payment", re.I)
RECEIPT = re.compile(r"receivable payment|receive money|customer receipt|sales receipt|\breceipt\b|\bsr\b|bank receipt|\bpayment\b|deposit", re.I)
INVOICE = re.compile(r"invoice|\bbill\b|\bpi\b|\bsi\b", re.I)
CREDIT_NOTE = re.compile(r"credit note|\bsc\b|\bpc\b", re.I)
JOURNAL = re.compile(r"journal|\bjd\b|\bjc\b", re.I)


def event_type(source: str) -> str:
    s = source or ""
    if JOURNAL.search(s):
        return "JOURNAL"
    if CREDIT_NOTE.search(s) and "allocation" not in s.lower():
        return "CREDIT NOTE"
    if INVOICE.search(s):
        return "INVOICE"
    if PAYMENT.search(s):
        return "PAYMENT"
    if RECEIPT.search(s):
        return "RECEIPT"
    return "JOURNAL"


def tax_month_start(d: date) -> date:
    """HMRC tax months run from the 6th to the 5th: a date on the 1st to 5th belongs to the previous month's."""
    if d.day >= 6:
        return date(d.year, d.month, 6)
    return date(d.year - 1, 12, 6) if d.month == 1 else date(d.year, d.month - 1, 6)


def tax_year(d: date) -> str:
    start = d.year if (d.month, d.day) >= (4, 6) else d.year - 1
    return f"{start}/{str(start + 1)[2:]}"


def tax_month_number(start: date) -> int:
    """Month 1 = 6 April to 5 May."""
    return (start.month - 4) % 12 + 1


def contact_of(description: str) -> str:
    """The customer / supplier: the description before ' - ', without 'Payment: ' (Xero's ledger layout)."""
    text = re.sub(r"^\s*payment\s*:\s*", "", description or "", flags=re.I)
    return re.sub(r"\s+", " ", text.split(" - ")[0]).strip().lower()


def _ref(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


@dataclass
class Line:
    when: date
    account: str
    source: str
    description: str
    reference: str
    amount: float          # debit - credit
    code: Optional[int]


# Materials in a subcontractor's payment: no CIS on them (FA04 s61, CISR15100), so the rate test leaves them out
MATERIALS_CODES = {1100, 1101, 1102, 1103, 1104, 1105, 1106, 1107, 1108, 1109, 1400, 2100, 2400}
MATERIALS_TEXT = re.compile(r"\bmaterials?\b", re.I)

@dataclass
class CashItem:
    cash_date: Optional[date]
    contact: str
    reference: str
    source: str
    event: str
    amount: float                    # CIS (positive = suffered / deducted)
    booked: Optional[date] = None    # the ledger date, when it differs (an invoice paid later)
    tax_month: Optional[str] = None  # ISO date of the 6th that starts it
    tax_month_no: Optional[int] = None
    tax_year: Optional[str] = None
    note: str = ""
    gross: Optional[float] = None    # contractor side: the payment's gross labour and materials (from the cost lines)
    labour: Optional[float] = None   # the same, materials left out: what the deduction is worked on (FA04 s61)


@dataclass
class Side:
    name: str                        # "suffered" or "deducted"
    code: int
    invoice_basis: float = 0.0       # CIS in the ledger this year
    opening_unpaid: float = 0.0
    closing_unpaid: float = 0.0
    cash: List[CashItem] = field(default_factory=list)
    unpaid: List[CashItem] = field(default_factory=list)     # CIS on invoices unpaid at the year end
    journals: List[CashItem] = field(default_factory=list)   # reviewer decides
    settled: List[CashItem] = field(default_factory=list)    # CIS recovered from / paid to HMRC (not CIS of the year)
    exceptions: List[str] = field(default_factory=list)

    @property
    def cash_total(self) -> float:
        return round(sum(i.amount for i in self.cash), 2)

    @property
    def proof_difference(self) -> float:
        """Invoice basis + opening - closing - cash: nil when the conversion is complete (journals excepted)."""
        return round(self.invoice_basis + self.opening_unpaid - self.closing_unpaid - self.cash_total
                     - sum(j.amount for j in self.journals), 2)

    @property
    def settled_total(self) -> float:
        return round(sum(i.amount for i in self.settled), 2)

    def months(self) -> List[Dict[str, Any]]:
        by: Dict[str, float] = defaultdict(float)
        for i in self.cash:
            by[i.tax_month] += i.amount
        return [{"tax_month": m, "month_no": tax_month_number(date.fromisoformat(m)),
                 "tax_year": tax_year(date.fromisoformat(m)), "amount": round(v, 2)} for m, v in sorted(by.items())]


def _place(item: CashItem) -> CashItem:
    if item.cash_date:
        start = tax_month_start(item.cash_date)
        item.tax_month, item.tax_month_no, item.tax_year = start.isoformat(), tax_month_number(start), tax_year(start)
    return item


# ------------------------------------------------------------------------------------------------------------------
# Invoices on the control account, and which receipts / payments paid them
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class Invoice:
    when: date
    contact: str
    ref: str
    amount: float
    left: float
    paid: List[Tuple[date, float]] = field(default_factory=list)


def _settle(control: List[Line], sign: int) -> Tuple[List[Invoice], Dict[str, List[Tuple[date, float]]]]:
    """sign +1 for debtors (an invoice is a debit), -1 for creditors. Returns the invoices with what paid them, and
    payments not matched to an invoice of this year (they paid last year's invoices)."""
    invoices: Dict[str, List[Invoice]] = defaultdict(list)
    settlements: Dict[str, List[Line]] = defaultdict(list)
    for l in control:
        amount = sign * l.amount
        if event_type(l.source) == "INVOICE" and amount > 0:
            c = contact_of(l.description)
            invoices[c].append(Invoice(l.when, c, _ref(l.reference), amount, amount))
        elif amount < 0:
            settlements[contact_of(l.description)].append(l)
    unmatched: Dict[str, List[Tuple[date, float]]] = defaultdict(list)
    for c, pays in settlements.items():
        open_ = sorted(invoices.get(c, []), key=lambda i: i.when)
        for p in sorted(pays, key=lambda x: x.when):
            left, ref = -sign * p.amount, _ref(p.reference)
            candidates = [i for i in open_ if i.left > 0.005 and i.when <= p.when]
            same_ref = [i for i in candidates if ref and i.ref == ref]
            exact = [i for i in candidates if abs(i.left - left) < 0.01][:1]
            for group in (same_ref, exact, candidates):
                for i in group:
                    if left < 0.005:
                        break
                    if i.left < 0.005:
                        continue
                    take = min(left, i.left)
                    i.left -= take
                    i.paid.append((p.when, take))
                    left -= take
            if left > 0.005:
                unmatched[c].append((p.when, left))
    return [i for v in invoices.values() for i in v], unmatched


# ------------------------------------------------------------------------------------------------------------------
# One side
# ------------------------------------------------------------------------------------------------------------------
def _side(name: str, code: int, cis_lines: List[Line], control: List[Line], sign: int, period_end: date,
          opening_unpaid: Optional[float], gross_of: Optional[Dict[Tuple[date, str, str], float]] = None,
          labour_of: Optional[Dict[Tuple[date, str, str], float]] = None) -> Side:
    side = Side(name, code)
    invoices, unmatched = _settle(control, sign)
    # Only customers / suppliers with CIS: payments of other parties' old invoices carry no CIS
    cis_parties = {contact_of(l.description) for l in cis_lines}
    unmatched = {c: v for c, v in unmatched.items() if c in cis_parties}
    by_key: Dict[Tuple[str, str, date], List[Invoice]] = defaultdict(list)
    for i in invoices:
        by_key[(i.contact, i.ref, i.when)].append(i)
    used: Dict[Tuple[str, str, date], int] = defaultdict(int)
    # Two CIS lines in one transaction (same date, party, reference) share its gross in proportion to their CIS
    cis_in_tx: Dict[Tuple[date, str, str], float] = defaultdict(float)
    for l in cis_lines:
        cis_in_tx[(l.when, contact_of(l.description), _ref(l.reference))] += sign * l.amount

    for l in cis_lines:
        amount = round(sign * l.amount, 2)
        ev, c = event_type(l.source), contact_of(l.description)
        base = dict(contact=c, reference=l.reference or "", source=l.source or "", event=ev)
        tx = (l.when, c, _ref(l.reference))
        gross = (gross_of or {}).get(tx)
        labour_share = ((labour_of or {}).get(tx, 0.0) / gross) if gross else None
        if gross and abs(cis_in_tx[tx]) >= 0.005:
            gross *= amount / cis_in_tx[tx]
        labour = round(gross * labour_share, 2) if gross and labour_share is not None else None
        if amount < 0 and ev != "CREDIT NOTE":
            # The other way round: CIS suffered recovered (offset on the EPS), or deductions paid over to HMRC. Not CIS
            # of the year: kept apart for the HMRC position (checks.py)
            side.settled.append(_place(CashItem(cash_date=l.when, amount=-amount, booked=l.when,
                                                note="recovered from HMRC" if sign > 0 else "paid to HMRC", **base)))
            continue
        side.invoice_basis += amount
        if ev in ("PAYMENT", "RECEIPT"):
            side.cash.append(_place(CashItem(cash_date=l.when, amount=amount, gross=gross, labour=labour, **base)))
        elif ev in ("INVOICE", "CREDIT NOTE"):
            k = (c, _ref(l.reference), l.when)
            matches = by_key.get(k, [])
            inv = matches[used[k] % len(matches)] if matches else None   # several invoices alike: in turn
            used[k] += 1
            if ev == "CREDIT NOTE" or inv is None:
                # A credit note reverses its invoice's CIS: treated at its own date (listed so the reviewer sees it)
                note = "credit note: dated as booked" if ev == "CREDIT NOTE" else "invoice not found on the control account: dated as booked"
                side.cash.append(_place(CashItem(cash_date=l.when, amount=amount, booked=l.when, note=note, **base)))
                if ev != "CREDIT NOTE":
                    side.exceptions.append(f"{l.when:%d/%m/%Y} {c} {l.reference}: invoice not found on the control account")
                continue
            paid_in_year = 0.0
            for when, taken in inv.paid:
                share = amount * taken / inv.amount
                if when <= period_end:
                    paid_in_year += share
                    side.cash.append(_place(CashItem(cash_date=when, amount=share, booked=l.when,
                                                     gross=gross * taken / inv.amount if gross else None,
                                                     labour=labour * taken / inv.amount if labour else None,
                                                     note="re-dated to the payment" if when != l.when else "", **base)))
            unpaid = round(amount - paid_in_year, 2)
            if abs(unpaid) >= 0.005:
                side.unpaid.append(CashItem(cash_date=None, amount=unpaid, booked=l.when,
                                            note="unpaid at the year end" if paid_in_year < 0.005 else "part paid at the year end", **base))
        else:
            side.journals.append(_place(CashItem(cash_date=l.when, amount=amount, booked=l.when,
                                                 note="journal: not cash, reviewer decides", **base)))

    # Last year's unpaid CIS received / paid this year: spread over the payments that settled last year's invoices
    side.opening_unpaid = round(opening_unpaid or 0.0, 2)
    if side.opening_unpaid:
        old = sorted(((w, a, c) for c, items in unmatched.items() for w, a in items if w <= period_end), key=lambda x: x[0])
        total = sum(a for _, a, _ in old)
        if total:
            for when, amt, c in old:
                side.cash.append(_place(CashItem(cash_date=when, contact=c, reference="", source="last year's invoice",
                                                 event="RECEIPT" if sign > 0 else "PAYMENT",
                                                 amount=side.opening_unpaid * amt / total,
                                                 note="last year's unpaid CIS, spread over the payments of last year's invoices")))
        else:
            side.exceptions.append("Opening unpaid CIS entered, but no payment of last year's invoices found this year")
    elif any(unmatched.values()):
        old_total = sum(a for items in unmatched.values() for w, a in items if w <= period_end)
        if old_total >= 1:
            side.exceptions.append(f"£{old_total:,.2f} paid this year on invoices from before the year: enter last year's "
                                   f"unpaid CIS on the Setup tab (from last year's CIS working)")

    side.invoice_basis = round(side.invoice_basis, 2)
    side.closing_unpaid = round(sum(i.amount for i in side.unpaid), 2)
    for i in side.cash:
        i.amount = round(i.amount, 2)
        i.gross = round(i.gross, 2) if i.gross is not None else None
    if abs(side.proof_difference) >= 1:
        side.exceptions.append(f"Proof does not agree by £{side.proof_difference:,.2f}")
    return side


# ------------------------------------------------------------------------------------------------------------------
# The engagement
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class CisCash:
    on: bool
    period_start: Optional[date]
    period_end: date
    sides: List[Side]

    def as_dict(self) -> Dict[str, Any]:
        def side(s: Side) -> Dict[str, Any]:
            return {"name": s.name, "code": s.code, "invoice_basis": s.invoice_basis, "opening_unpaid": s.opening_unpaid,
                    "closing_unpaid": s.closing_unpaid, "cash": s.cash_total, "proof_difference": s.proof_difference,
                    "settled_with_hmrc": s.settled_total, "settled": [asdict(i) for i in s.settled],
                    "months": s.months(), "exceptions": s.exceptions,
                    "lines": [asdict(i) for i in sorted(s.cash, key=lambda i: (i.cash_date or date.min))],
                    "unpaid": [asdict(i) for i in s.unpaid], "journals": [asdict(i) for i in s.journals]}
        return {"on": self.on, "period_start": self.period_start.isoformat() if self.period_start else None,
                "period_end": self.period_end.isoformat(), "sides": [side(s) for s in self.sides]}


def ledger_lines(engagement_id: str, tb_records: Iterable[TBRecord], db: Session) -> List[Line]:
    from backend.app.services.sop.common import code_matcher
    code_of = code_matcher(ChartLookup.gl_account_codes(tb_records))    # sub-accounts by their parent too
    out = []
    for tx in db.execute(select(GLTransaction).where(GLTransaction.engagement_id == engagement_id)).scalars():
        if not tx.transaction_date:
            continue
        code = code_of(tx.raw_account_name or "")
        out.append(Line(tx.transaction_date, tx.raw_account_name or "", tx.source or "", tx.description or "",
                        tx.reference or "", float(tx.debit_amount or 0) - float(tx.credit_amount or 0), code))
    return out


def cis_cash(engagement: ClientEngagement, db: Session, setup_cis: Optional[Dict[str, Any]] = None) -> CisCash:
    """setup_cis: the setup's CIS answers (opening_unpaid_suffered / opening_unpaid_deducted from last year's working)."""
    tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    end = engagement.period_end_date
    start = engagement.prior_period_end_date + timedelta(days=1) if engagement.prior_period_end_date else None
    codes = {t.std_code for t in tb}
    if CIS_SUFFERED not in codes and CIS_DEDUCTED not in codes:
        return CisCash(False, start, end, [])
    lines = [l for l in ledger_lines(str(engagement.id), tb, db) if l.when <= end and (start is None or l.when >= start)]
    # Contractor side: a payment's gross = its cost lines (P&L) in the same transaction (date, supplier, reference)
    gross_of: Dict[Tuple[date, str, str], float] = defaultdict(float)
    labour_of: Dict[Tuple[date, str, str], float] = defaultdict(float)
    for l in lines:
        if l.code is not None and l.code < 4000 and l.amount > 0:
            key = (l.when, contact_of(l.description), _ref(l.reference))
            gross_of[key] += l.amount
            if l.code not in MATERIALS_CODES and not MATERIALS_TEXT.search(l.description or ""):
                labour_of[key] += l.amount
    setup_cis = setup_cis or {}
    sides = []
    for name, code, control, sign, opening in (
            ("suffered", CIS_SUFFERED, TRADE_DEBTORS, 1, setup_cis.get("opening_unpaid_suffered")),
            ("deducted", CIS_DEDUCTED, TRADE_CREDITORS, -1, setup_cis.get("opening_unpaid_deducted"))):
        if code not in codes:
            continue
        sides.append(_side(name, code, [l for l in lines if l.code == code], [l for l in lines if l.code == control],
                           sign, end, float(opening) if opening not in (None, "") else None,
                           gross_of if name == "deducted" else None, labour_of if name == "deducted" else None))
    return CisCash(True, start, end, sides)
