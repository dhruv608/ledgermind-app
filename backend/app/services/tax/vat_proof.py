"""
The VAT proof: the VAT account at the year end explained line by line, in the firm's VAT
reconciliation layout, one sheet per scheme and basis:

  Standard, accruals    outstanding VAT per the returns, exception report, VAT yet to file, opening variance,
                        VAT filed but not in the accounts, adjustments
  Standard, cash        the same without 'filed but not in the accounts', with VAT on closing debtors (add), closing
                        creditors (less), opening debtors (less) and opening creditors (add): the returns count VAT
                        when the money moves, the books when the invoice is raised (Notice 731 s1)
  Flat rate, accruals   outstanding VAT, exception report, yet to file, opening variance, adjustments; the VAT the books
                        hold above the flat-rate returns is shown apart (the surplus is income, V-F06)
  Flat rate, cash       as flat rate, accruals, with the debtors lines only (no input VAT is reclaimed on the flat
                        rate scheme, FRS6500, so unpaid bills hold no VAT the returns count later)

The books' VAT is the VAT account's own movement (every line on 5300 except HMRC payments, interest and penalties):
the VAT column of a ledger export is often incomplete (QuickBooks sales without it), the VAT account never is. The
lines add up to what the VAT account should hold; the books less that total is the difference still to explain (an
HMRC payment per the VAT summary that is not in the ledger, or the other way round).
Shared by the control accounts screen and the workbook's G9 so the two cannot disagree. The exception report and the
adjustments are typed by the accountant (keys vatproof:exception, vatproof:adjustments).
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord

VAT_FRACTION = 1 / 6               # the VAT inside a standard-rated gross amount (20 / 120)
TRADE_DEBTORS, TRADE_CREDITORS = 4400, 5200
ENTERED_KEYS = ("vatproof:exception", "vatproof:adjustments")
TITLES = {("STANDARD", "ACCRUALS"): "Standard - Accruals", ("STANDARD", "CASH"): "Standard - Cash",
          ("FLAT_RATE", "ACCRUALS"): "Flat Rate - Accruals", ("FLAT_RATE", "CASH"): "Flat Rate - Cash"}


def _open_items_vat(engagement: ClientEngagement, tb_records: List[TBRecord], gl, vat_code: int) -> Dict[str, Any]:
    """The VAT inside the invoices and bills still unpaid at the year end, invoice by invoice from each one's tax
    code: each item on the aged debtors / creditors report at the year
    end is found in the ledger (same contact and date) and its own VAT line taken, in the share still unpaid; an item
    not found (or a summary report with totals only) is taken at a sixth. {"AR" / "AP": (vat, found, estimated)}."""
    from backend.app.services.ingestion.ageing_reports import outstanding_items, read_ageing_reports
    from backend.app.services.tax.open_items import documents_by_day, find_document, ledger_documents
    try:
        reports = read_ageing_reports(str(engagement.id), engagement.period_end_date, tb_records)
    except Exception:
        return {}
    docs = ledger_documents(gl, vat_code)
    out: Dict[str, Any] = {}
    for side, report in reports.items():
        if side not in ("AR", "AP") or report.as_at not in (None, engagement.period_end_date):
            continue
        items = outstanding_items(report)
        if not items:
            continue
        total, found, estimated = 0.0, 0, 0
        by_day = documents_by_day(docs, side)
        for it in items:
            d = find_document(it, by_day)
            if d and d["gross"] >= 0.01:
                total += abs(d["vat"]) * min(1.0, abs(it.amount) / d["gross"]) * (1 if it.amount >= 0 else -1)
                found += 1
            else:
                total += it.amount * VAT_FRACTION
                estimated += 1
        out[side] = (abs(total), found, estimated)
    return out


def _line(key: str, label: str, amount: Optional[float], note: str = "", entered: bool = False) -> Dict[str, Any]:
    return {"key": key, "label": label, "amount": None if amount is None else round(amount, 2), "note": note,
            "entered": entered}


def vat_proof(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session, pos=None,
              books: Optional[float] = None, gl=None) -> Dict[str, Any]:
    """The proof as a dict: title, scheme, basis, lines (key, label, amount or None when not known, note, entered),
    total, books (VAT owed to HMRC, a credit, as a positive figure), difference, and missing (why there is none)."""
    from backend.app.services.reconciliation.control_accounts import entered_inputs, vat_position
    from backend.app.services.sop.common import gl_lines
    from backend.app.services.tax.ct_computation import final_balances
    from backend.app.services.tax.vat_review import VAT_CONTROL, scheme_and_basis, vat_review

    profile = getattr(engagement, "profile", None)
    scheme, basis = scheme_and_basis(getattr(profile, "vat_scheme", None))
    if gl is None:
        gl = gl_lines(str(engagement.id), tb_records, db)
    if pos is None:
        pos = vat_position(db, engagement, ((l.when, str(l.code), l.description, l.debit - l.credit, l.source) for l in gl))
    if books is None:
        books = -final_balances(str(engagement.id), tb_records, db).get(VAT_CONTROL, 0.0)
    out: Dict[str, Any] = {"title": f"VAT Reconciliation - {TITLES[(scheme, basis)]}", "scheme": scheme, "basis": basis,
                           "lines": [], "total": None, "books": round(books, 2), "difference": None, "missing": ""}
    if not pos.returns:
        out["missing"] = "Enter the VAT returns on the VAT returns screen"
        return out

    review = vat_review(engagement, tb_records, db)
    checks, ped = review.returns, engagement.period_end_date
    year_start = review.year_start or (ped - timedelta(days=364))
    entered = entered_inputs(db, engagement.id)
    lines: List[Dict[str, Any]] = []

    # Outstanding VAT per the returns: what the returns filed say is owed, less what was paid on them
    shown = sum(pos.shown(i) for i in range(len(pos.returns)))
    paid = sum(p[2] for p in pos.payments)
    last_end = max(r.period_end for r in pos.returns)
    lines.append(_line("outstanding", "Outstanding VAT per the returns (to the last quarter end)", shown - paid,
                       f"Returns to {last_end:%d/%m/%Y} £{shown:,.2f} less "
                       f"{'payments per the VAT summary' if pos.source == 'summary' else 'HMRC payments on the VAT account'}"
                       f" £{paid:,.2f} (G9.1)"))
    if pos.charges:
        lines.append(_line("charges", "Interest and penalties posted to the VAT account (not VAT)",
                           -sum(c[2] for c in pos.charges), "HMRC interest or penalties: they change what is owed but "
                                                            "are not VAT"))
    if pos.other_tax:
        kinds = sorted({"corporation tax" if t[3] == "CT" else "PAYE and NI" for t in pos.other_tax})
        lines.append(_line("other_tax", "Other taxes paid from the VAT account (not VAT)",
                           -sum(t[2] for t in pos.other_tax),
                           f"{' and '.join(kinds).capitalize()} paid to HMRC but posted to the VAT account: moved by journal"))
    exception = entered.get("vatproof:exception") or {}
    lines.append(_line("exception", "Exception report", exception.get("balance"),
                       exception.get("note") or "Items on the software's VAT exception report, typed in", entered=True))

    # The VAT account's movement in the year, owed to HMRC as a positive figure, without the HMRC payments (the ledger's
    # own, also when the VAT summary gives the payments), interest and penalties: the VAT the books recorded
    taken: Dict[tuple, int] = {}
    paid_lines = pos.ledger_payments if pos.source == "summary" else pos.payments + pos.earlier_payments
    for when, _desc, net in paid_lines + pos.charges + [t[:3] for t in pos.other_tax]:
        taken[(when, round(net, 2))] = taken.get((when, round(net, 2)), 0) + 1
    moved: List[tuple] = []
    for l in gl:
        if l.code != VAT_CONTROL or not l.when or not (year_start <= l.when <= ped):
            continue
        net = round(l.debit - l.credit, 2)
        if taken.get((l.when, net)):
            taken[(l.when, net)] -= 1
            continue
        moved.append((l.when, -net))
    ledger = any(l.code == VAT_CONTROL for l in gl)
    inside = lambda c, when: max(c.start, year_start) <= when <= c.end
    unfiled = round(sum(v for when, v in moved if not any(inside(c, when) for c in checks)), 2)
    gaps = round(sum(v for when, v in moved if when <= last_end and not any(inside(c, when) for c in checks)), 2)

    # VAT yet to file: on the VAT account after the last return to the year end (next year's first return), and in
    # months no return entered covers
    if not ledger:
        lines.append(_line("yet_to_file", "VAT yet to file (after the last return)", None,
                           "No ledger lines on the VAT account: upload the general ledger"))
    else:
        lines.append(_line("yet_to_file", "VAT yet to file (after the last return)", unfiled,
                           (f"The VAT account from {last_end + timedelta(days=1):%d/%m/%Y} to {ped:%d/%m/%Y}"
                            if last_end < ped else "The returns reach the year end")
                           + (f"; incl. £{gaps:,.2f} in months no return entered covers" if abs(gaps) >= 0.01 else "")))

    # Opening variance: the VAT account at the start of the year less what was owed then: last year's returns still
    # unpaid, an earlier return paid this year, and the part of a return straddling the year start that is last
    # year's (by days)
    rows = [t for t in tb_records if t.std_code == VAT_CONTROL]
    pre_year = 0.0
    for c in checks:
        if c.start < year_start:
            days = (c.end - c.start).days + 1
            pre_year += (c.box1 - c.box4) * (year_start - c.start).days / days if days > 0 else 0.0
    if any(t.opening_amount is not None for t in rows) or not rows:
        opening = -sum(float(t.opening_amount or 0) for t in rows)
        owed_then = sum(pos.owed[:pos.brought_forward]) + sum(p[2] for p in pos.earlier_payments) + pre_year
        lines.append(_line("opening_variance", "Opening variance", opening - owed_then,
                           f"VAT account at the start of the year £{opening:,.2f} less owed then per the returns "
                           f"£{owed_then:,.2f}" + (f" (incl. £{pre_year:,.2f}, last year's part of the return "
                                                    f"straddling the year start, by days)" if pre_year else "")))
    elif ledger:
        # No opening column in the TB: the VAT account at the start of the year is its closing balance less the year's
        # movement in the ledger (opening 5300 + the year's VAT - payments = closing 5300)
        closing = sum(float(t.net_amount or 0) for t in rows)
        movement = sum(l.debit - l.credit for l in gl if l.code == VAT_CONTROL and l.when and year_start <= l.when <= ped)
        opening = -(closing - movement)
        owed_then = sum(pos.owed[:pos.brought_forward]) + sum(p[2] for p in pos.earlier_payments) + pre_year
        lines.append(_line("opening_variance", "Opening variance", opening - owed_then,
                           f"VAT account at the start of the year £{opening:,.2f} (no opening balance in the trial "
                           f"balance: its closing balance less the year's ledger movement) less owed then per the "
                           f"returns £{owed_then:,.2f}"
                           + ("; enter last year's last return to show what was owed at the start" if not owed_then else "")))
    else:
        lines.append(_line("opening_variance", "Opening variance", None,
                           "The VAT account's opening balance is not in the trial balance"))

    # The VAT account against the returns, for the same months this year (a return straddling the year start: its
    # last-year part, by days, is left to the opening variance)
    in_books = None
    if ledger:
        in_books = 0.0
        for c in checks:
            days = (c.end - c.start).days + 1
            share = ((c.end - max(c.start, year_start)).days + 1) / days if days > 0 else 0.0
            in_books += sum(v for when, v in moved if inside(c, when)) - (c.box1 - c.box4) * share
    if scheme == "STANDARD" and basis == "ACCRUALS":
        lines.append(_line("filed_not_in_accounts", "VAT filed but not in the accounts", in_books,
                           "The VAT account less the returns for the same months (an entry posted after its return "
                           "was filed shows here, and the opposite on a later return)" if in_books is not None else
                           "No ledger lines on the VAT account, so the returns cannot be compared with the books"))
    elif scheme == "FLAT_RATE" and basis == "ACCRUALS" and in_books is not None:
        lines.append(_line("flat_rate_surplus", "Flat rate: VAT in the books above the flat-rate returns", in_books,
                           "Books kept at standard rates hold more VAT than the flat rate charges: the surplus is income "
                           "(V-F06)"))

    # Cash basis: the returns count VAT when the money moves, the books when the invoice is raised (Notice 731)
    if basis == "CASH":
        def balance(code: int, field: str) -> Optional[float]:
            got = [t for t in tb_records if t.std_code == code]
            if field == "opening_amount" and got and all(t.opening_amount is None for t in got):
                return None
            return sum(float(getattr(t, field) or 0) for t in got)
        debtors, debtors_b = balance(TRADE_DEBTORS, "net_amount"), balance(TRADE_DEBTORS, "opening_amount")
        creditors, creditors_b = balance(TRADE_CREDITORS, "net_amount"), balance(TRADE_CREDITORS, "opening_amount")
        vat = lambda v, sign: None if v is None else sign * abs(v) * VAT_FRACTION
        # Invoice by invoice from the aged reports when the client gave them (VAT on closing debtors from the
        # customer balance detail); else a sixth of the balance
        open_vat = _open_items_vat(engagement, tb_records, gl, VAT_CONTROL) if scheme == "STANDARD" else {}
        how = lambda side, what: (f"VAT on {open_vat[side][1] + open_vat[side][2]} unpaid {what} per the aged "
                                  f"{'debtors' if side == 'AR' else 'creditors'} report: {open_vat[side][1]} from each "
                                  f"one's VAT in the ledger" + (f", {open_vat[side][2]} at a sixth (not found in the "
                                  f"ledger)" if open_vat[side][2] else ""))
        if "AR" in open_vat:
            lines.append(_line("closing_debtors", "VAT on closing debtors (add)", open_vat["AR"][0], how("AR", "invoices")))
        else:
            lines.append(_line("closing_debtors", "VAT on closing debtors (add)", vat(debtors, 1),
                               f"A sixth of trade debtors £{abs(debtors or 0):,.2f}: invoiced, not yet received"))
        if scheme == "STANDARD" and "AP" in open_vat:
            lines.append(_line("closing_creditors", "VAT on closing creditors (less)", -open_vat["AP"][0], how("AP", "bills")))
        elif scheme == "STANDARD":
            lines.append(_line("closing_creditors", "VAT on closing creditors (less)", vat(creditors, -1),
                               f"A sixth of trade creditors £{abs(creditors or 0):,.2f}: billed, not yet paid"))
        lines.append(_line("opening_debtors", "VAT on opening debtors (less)", vat(debtors_b, -1),
                           f"A sixth of trade debtors at the start £{abs(debtors_b):,.2f}: on this year's returns"
                           if debtors_b is not None else "Opening debtors not in the trial balance"))
        if scheme == "STANDARD":
            lines.append(_line("opening_creditors", "VAT on opening creditors (add)", vat(creditors_b, 1),
                               f"A sixth of trade creditors at the start £{abs(creditors_b):,.2f}: on this year's returns"
                               if creditors_b is not None else "Opening creditors not in the trial balance"))

    adjustments = entered.get("vatproof:adjustments") or {}
    lines.append(_line("adjustments", "Adjustments", adjustments.get("balance"),
                       adjustments.get("note") or "Any other correction, typed in", entered=True))

    out["lines"] = lines
    out["total"] = round(sum(l["amount"] for l in lines if l["amount"] is not None), 2)
    out["difference"] = round(books - out["total"], 2)
    return out
