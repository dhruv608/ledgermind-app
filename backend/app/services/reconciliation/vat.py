"""The VAT position for the control accounts screen: the VAT account's balance against the returns, HMRC payments and
other taxes posted to it, and VAT paid per return."""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord, VAT100Record
from backend.app.services.mapping.chart_lookup import VAT_CONTROL



# ------------------------------------------------------------------------------------------------------------------
# VAT: the returns entered on the VAT returns screen and the HMRC payments on the VAT account (shared with G9 / G9.1)
# ------------------------------------------------------------------------------------------------------------------
@dataclass
class VatPosition:
    returns: List[Any]                           # VAT100Record, brought forward first, oldest first
    brought_forward: int                         # how many of them ended by last year's year end
    owed: List[float]                            # what each return left owed (for matching payments)
    payments: List[Tuple[date, str, float]]      # HMRC lines on the VAT account: (date, description, debit - credit)
    allocations: List[Dict[int, float]] = field(default_factory=list)   # each payment, by return index
    # Interest, penalties and surcharges posted to the VAT account: not payments of VAT (date, description, amount)
    charges: List[Tuple[date, str, float]] = field(default_factory=list)
    # Where the payments come from: the client's VAT summary (each return's paid amount and date) or the ledger
    source: str = "ledger"
    ledger_payments: List[Tuple[date, str, float]] = field(default_factory=list)   # the ledger's, kept to compare
    # Corporation tax or PAYE paid to (or refunded by) HMRC but posted to the VAT account: not VAT,
    # never a payment of a return; (date, description, debit - credit, "CT" or "PAYE")
    other_tax: List[Tuple[date, str, float, str]] = field(default_factory=list)
    # HMRC payments made before the first listed return had ended: they paid an earlier return not in the list
    earlier_payments: List[Tuple[date, str, float]] = field(default_factory=list)

    def shown(self, i: int) -> float:
        """A return's amount as G9.1 shows it: what was still owed for last year's, box 3 less box 4 for this year's."""
        r = self.returns[i]
        if i < self.brought_forward:
            return self.owed[i]
        return float(r.box3_total_vat_due or 0) - float(r.box4_vat_reclaimed or 0)

    @property
    def owed_per_returns(self) -> float:
        """VAT still owed per the returns less every HMRC payment, plus interest / penalties posted to the VAT account
        (a credit there adds to what the account shows as owed) (G9 'Total', D31)."""
        return round(sum(self.shown(i) for i in range(len(self.returns))) - sum(p[2] for p in self.payments)
                     - sum(c[2] for c in self.charges) - sum(t[2] for t in self.other_tax), 2)
HMRC_TEXT = re.compile(r"hmrc|h\.\s?m\.\s?r\.\s?c|hm revenue|revenue (and|&) customs", re.I)
# A ledger line that says it is the VAT paid ('VAT Payment' as Xero's type, 'VAT paid', 'VAT return payment')
VAT_PAID_TEXT = re.compile(r"\bvat\s+(return\s+)?(payment|paid|refund|repayment)\b", re.I)
# A VAT return is paid 1 month and 7 days after its period ends (Notice 700/12): a payment up to 70 days after a
# return ended is that return's, even when it is not the same amount (a VAT correction, a late or part payment)
PAID_WITHIN_DAYS = 70
# An HMRC payment for another tax ('HMRC COTAX', 'HMRC PAYE', 'NIC'), posted to the VAT account by mistake
OTHER_TAX_TEXT = re.compile(r"\bcotax\b|corporation\s+tax|\bpaye\b|\bnic\b|national\s+insurance|\bp32\b|\bcis\b", re.I)
CT_TEXT = re.compile(r"\bcotax\b|corporation\s+tax", re.I)
VAT_WORDS = re.compile(r"\bvat\b|\bndds\b", re.I)       # NDDS: HMRC's direct debit service, how VAT is collected


def other_tax_kind(desc: str) -> str:
    """'CT' or 'PAYE' when the bank narrative of an HMRC line says it is that tax, else "". Only the narrative (after the
    contact, 'HMRC PAYE - Hmrc Vat 123456789') counts: a client's one HMRC contact is often named for one tax and used
    for all ('HMRC PAYE' paying VAT); a line naming VAT, or with no narrative, stays VAT."""
    narrative = desc.split(" - ", 1)[1] if " - " in desc else ""
    if not narrative or VAT_WORDS.search(narrative) or not OTHER_TAX_TEXT.search(narrative):
        return ""
    return "CT" if CT_TEXT.search(narrative) else "PAYE"
JOURNAL_SOURCE = re.compile(r"journal|\bjnl\b|\bgj\b|\bjl\b|\bjd\b|\bjc\b", re.I)
# Interest, penalties and surcharges on the VAT account: what HMRC charged (or paid as repayment interest), not VAT
CHARGE_TEXT = re.compile(r"interest|penalt|surcharge|late (filing|payment|submission)|\bfine\b", re.I)
# QuickBooks writes this on every VAT payment or refund it records: not HMRC interest, so a VAT repayment is not read
# as interest and penalties
QB_VAT_MEMO = re.compile(r"\(interest recorded as bank deposit\)", re.I)


def vat_position(db: Optional[Session], engagement: ClientEngagement, lines: Iterable[Tuple[Any, ...]]) -> VatPosition:
    """lines: every ledger line as (date, firm code, description, debit - credit[, source]). An HMRC payment (or
    refund) on the VAT account is a line naming HMRC, or a line (not a journal) for exactly what a return left owed,
    dated after the return's period: QuickBooks names HMRC only on the bank side of the payment."""
    ped = engagement.period_end_date
    prior_ye = ped.replace(year=ped.year - 1, day=28) if (ped.month, ped.day) == (2, 29) else ped.replace(year=ped.year - 1)
    entered = []
    if db is not None:
        entered = [r for r in db.execute(select(VAT100Record).where(VAT100Record.engagement_id == engagement.id)).scalars() if r.period_end]
    entered.sort(key=lambda r: r.period_end)
    bfwd = [r for r in entered if r.period_end <= prior_ye]
    in_year = [r for r in entered if prior_ye < r.period_end <= ped]
    owed = [float(r.bfwd_outstanding if r.bfwd_outstanding is not None else r.box5_net_vat or 0) for r in bfwd]
    owed += [float(r.box5_net_vat or 0) for r in in_year]
    returns = bfwd + in_year

    def is_payment(when: date, desc: str, net: float, source: str) -> bool:
        if JOURNAL_SOURCE.search(source or ""):
            return False             # 'Filed VAT' journals move amounts between the VAT accounts; nothing is paid
        if HMRC_TEXT.search(desc or "") or VAT_PAID_TEXT.search(desc or "") or VAT_PAID_TEXT.search(source or ""):
            return True
        return any(abs(net - o) < 0.01 and abs(o) >= 0.01 and r.period_end < when for r, o in zip(returns, owed))

    payments, charges, other_tax = [], [], []
    for line in lines:
        when, code, desc, net = line[:4]
        source = line[4] if len(line) > 4 else ""
        if when is None or code != str(VAT_CONTROL):
            continue
        if CHARGE_TEXT.search(QB_VAT_MEMO.sub("", str(desc or ""))):
            charges.append((when, desc, round(net, 2)))   # interest / penalty: shown apart, never a payment
        elif other_tax_kind(str(desc or "")) and not JOURNAL_SOURCE.search(str(source or "")):
            other_tax.append((when, desc, round(net, 2), other_tax_kind(str(desc))))
        elif is_payment(when, str(desc or ""), round(net, 2), str(source or "")):
            payments.append((when, desc, round(net, 2)))
    payments.sort(key=lambda p: p[0])
    charges.sort(key=lambda p: p[0])
    other_tax.sort(key=lambda p: p[0])

    # The client's VAT summary says what was paid on each return and when: those are the payments, each against
    # its own return; the ledger's HMRC lines stay beside them to compare
    paid_per_summary = []
    if db is not None and returns:
        from backend.app.models.vat_payments import VatReturnPayment
        paid_per_summary = [p for p in db.execute(select(VatReturnPayment).where(
            VatReturnPayment.engagement_id == engagement.id)).scalars() if p.paid is not None and abs(float(p.paid)) >= 0.005]
    if paid_per_summary:
        pos = VatPosition(returns, len(bfwd), owed, [], charges=charges, source="summary", ledger_payments=payments,
                          other_tax=other_tax)
        used = set()
        for p in sorted(paid_per_summary, key=lambda p: (p.paid_date or p.period_end or date.min)):
            i = next((i for i, r in enumerate(returns) if i not in used and r.period_end == p.period_end
                      and (r.period_label or "") == (p.period_label or "")), None)
            if i is None:
                i = next((i for i, r in enumerate(returns) if i not in used and r.period_end == p.period_end), None)
            text = f"Per the VAT summary: {p.period_label}" + (
                f" (paid {p.paid_date_text})" if p.paid_date is None and p.paid_date_text else "")
            pos.payments.append((p.paid_date, text, round(float(p.paid), 2)))
            pos.allocations.append({} if i is None else {i: round(float(p.paid), 2)})
            if i is not None:
                used.add(i)
        return pos
    # A payment made before the first listed return had ended paid an earlier one (last year's return not entered):
    # it is not taken off this year's returns
    earlier = [p for p in payments if returns and p[0] <= returns[0].period_end]
    if earlier and not bfwd:
        # No last-year return entered: the opening quarter is picked from those payments, last year's return to the
        # day before this year's first one starts, owed as paid (a payment is what was filed); it shows as the
        # summary's first line
        first = returns[0]
        opening_end = (first.period_start - timedelta(days=1)) if first.period_start else \
            first.period_end - timedelta(days=(first.period_end - prior_ye).days or 91)
        opening = SimpleNamespace(period_label="Opening quarter", period_start=None, period_end=opening_end,
                                  bfwd_outstanding=None, box3_total_vat_due=None, box4_vat_reclaimed=None,
                                  box5_net_vat=None, box6_total_sales_ex_vat=None, opening=True)
        returns = [opening] + returns
        owed = [round(sum(p[2] for p in earlier), 2)] + owed
        bfwd, earlier = [opening], []
    payments = [p for p in payments if p not in earlier]
    pos = VatPosition(returns, len(bfwd), owed, payments, charges=charges, earlier_payments=earlier, other_tax=other_tax)

    # Each payment goes to its own return: one it pays to the penny, else the return it was due for (ended within
    # PAID_WITHIN_DAYS, not yet paid), whole, so an over or under payment shows on that return as on a VAT summary;
    # else the oldest return that had ended and was still unpaid
    remaining = list(owed)
    paid_by_date = set()
    for when, _, amount in payments:
        ended = [i for i, r in enumerate(pos.returns) if r.period_end < when]
        exact = next((i for i in ended if abs(remaining[i] - amount) < 0.01 and abs(amount) >= 0.01), None)
        due = next((i for i in ended if i not in paid_by_date and abs(remaining[i] - owed[i]) < 0.005 and amount * owed[i] > 0
                    and (when - pos.returns[i].period_end).days <= PAID_WITHIN_DAYS), None)
        own = exact if exact is not None else due
        if own is not None:
            remaining[own] -= amount
            paid_by_date.add(own)
            pos.allocations.append({own: round(amount, 2)})
            continue
        alloc, left = {}, amount
        for i, r in enumerate(pos.returns):
            if abs(left) < 0.005:
                break
            if r.period_end >= when or remaining[i] * left <= 0:
                continue
            take = min(left, remaining[i]) if left > 0 else max(left, remaining[i])
            alloc[i] = round(take, 2)
            remaining[i] -= take
            left -= take
        pos.allocations.append(alloc)
    return pos


def vat_paid_per_return(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    """What each VAT return owed, what was paid against it and what is left, matched as on G9 (the VAT summary's own
    payments when uploaded, else the HMRC lines on the VAT account, oldest return first)."""
    from backend.app.services.sop.common import gl_lines
    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    lines = gl_lines(str(engagement.id), tb_records, db)
    pos = vat_position(db, engagement, ((l.when, str(l.code), l.description, l.debit - l.credit, l.source) for l in lines))
    known = pos.source == "summary" or any(l.code == VAT_CONTROL for l in lines)
    paid = [0.0] * len(pos.returns)
    paid_on: Dict[int, List[str]] = {}
    dates: Dict[int, List[str]] = {}          # the date of each payment against the return (the VAT summary's Date paid)
    for (when, _, _), alloc in zip(pos.payments, pos.allocations):
        for i, amount in alloc.items():
            paid[i] += amount
            paid_on.setdefault(i, []).append(f"£{amount:,.2f} on {when:%d/%m/%Y}")
            if when and f"{when:%d/%m/%Y}" not in dates.get(i, []):
                dates.setdefault(i, []).append(f"{when:%d/%m/%Y}")
    note = lambda i: (f"Last year's return, picked from the HMRC payment{'s' if len(paid_on.get(i, [])) > 1 else ''} "
                      f"{', '.join(paid_on.get(i, []))}")
    return {"source": pos.source if known else "", "returns": [
        {"period_end": r.period_end.isoformat(), "owed": round(pos.owed[i], 2), "opening": bool(getattr(r, "opening", False)),
         "note": note(i) if getattr(r, "opening", False) else "",
         "paid": round(paid[i], 2) if known else None, "unpaid": round(pos.owed[i] - paid[i], 2) if known else None,
         "paid_on": dates.get(i, [])}
        for i, r in enumerate(pos.returns)],
        # The HMRC VAT account (date, description, amount): every payment to or from HMRC this
        # year, last year's returns paid this year, and the interest / penalties HMRC charged (not VAT)
        "hmrc": sorted([{"date": w.isoformat() if w else None, "description": d, "amount": round(a, 2), "kind": k}
                        for k, items in (("payment", pos.payments), ("earlier", pos.earlier_payments), ("charge", pos.charges))
                        for w, d, a in items], key=lambda x: x["date"] or "")}
