"""
CIS: the books on a cash basis against what was filed with HMRC, tax month by tax month, as tests T1 to T10, with
the timing items that explain a year-end difference (never netted silently).

Each test is PASS, FAIL, INFO or NOT RUN (the HMRC figure it needs is not entered). A FAIL becomes a review point
with its query (to the client or to the accountant). Tolerance: £1 per month.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, MasterCOA, TBRecord
from backend.app.services.cis.codes import CIS_DEDUCTED, CIS_SUFFERED, CIS_TEXT, cis_points
from backend.app.services.cis.cash import CisCash, Side, cis_cash
from backend.app.services.cis.hmrc import hmrc_screen

TOLERANCE = 1.0
PAYE_CONTROL = 5320
RATES = (0.20, 0.30, 0.0)


@dataclass
class Check:
    ref: str                 # "T1"
    name: str
    status: str              # PASS / FAIL / INFO / NOT RUN
    summary: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    query_to: str = ""       # "Client" or "Accountant" (when it fails)
    query: str = ""
    amount: float = 0.0


def _money(v: float) -> str:
    return f"-£{-v:,.2f}" if v < 0 else f"£{v:,.2f}"


def _side(cash: CisCash, name: str) -> Optional[Side]:
    return next((s for s in cash.sides if s.name == name), None)


def _month_end(start_iso: str) -> date:
    s = date.fromisoformat(start_iso)
    return date(s.year + (s.month == 12), s.month % 12 + 1, 5)


def _compare(months: List[Dict[str, Any]], books_key: str, books: Dict[str, float], hmrc_key: str,
             period_end: date) -> (List[Dict[str, Any]], int, int):
    """Rows for each month with an HMRC figure; returns (rows, entered, failing)."""
    rows, entered, failing = [], 0, 0
    for m in months:
        h = m["hmrc"].get(hmrc_key)
        b = round(books.get(m["tax_month"], 0.0), 2)
        if h is None:
            if b:
                rows.append({"tax_month": m["tax_month"], "label": m["label"], "books": b, "hmrc": None, "difference": None,
                             "note": "HMRC figure not entered"})
            continue
        entered += 1
        diff = round(b - float(h), 2)
        note = ""
        if abs(diff) >= TOLERANCE and _month_end(m["tax_month"]) > period_end:
            note = "The tax month runs past the year end: HMRC includes payments on the 1st to 5th after it (timing)"
        if abs(diff) >= TOLERANCE:
            failing += 1
        rows.append({"tax_month": m["tax_month"], "label": m["label"], "books": b, "hmrc": float(h), "difference": diff,
                     "note": note})
    return rows, entered, failing


def cis_checks(engagement: ClientEngagement, db: Session, setup_cis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    setup_cis = setup_cis or {}
    cash = cis_cash(engagement, db, setup_cis)
    if not cash.on:
        return {"on": False}
    screen = hmrc_screen(engagement, db, setup_cis)
    months, end = screen["months"], cash.period_end
    deducted, suffered = _side(cash, "deducted"), _side(cash, "suffered")
    by_month = lambda side, attr="amount": {m: sum(getattr(i, attr) or 0 for i in side.cash if i.tax_month == m)
                                           for m in {i.tax_month for i in side.cash}} if side else {}
    checks: List[Check] = []

    if screen["mode"] == "NOT_AVAILABLE":
        checks.append(Check("HMRC", "HMRC figures", "FAIL", "HMRC figures not available: every month is unverified",
                            query_to="Client", query="Please send the CIS300 returns / EPS reports and the HMRC PAYE-CIS "
                                                     "account statement for the period."))

    # T1 / T2 / T3: the contractor side
    if deducted:
        rows, entered, failing = _compare(months, "deducted", by_month(deducted), "deducted", end)
        unexplained = [r for r in rows if r["difference"] and abs(r["difference"]) >= TOLERANCE and not r["note"]]
        status = "NOT RUN" if not entered else ("FAIL" if unexplained else "PASS")
        checks.append(Check("T1", "CIS deducted per month (books vs CIS300)", status,
                            (f"{failing} of {entered} month(s) differ; after the timing months "
                             f"{_money(sum(r['difference'] for r in unexplained))} is unexplained") if entered
                            else "No CIS300 figures entered", rows,
                            "Accountant", "; ".join(f"CIS300 for {r['label']} differs by {_money(r['difference'])}: amend the "
                                                    f"return or correct the books?" for r in unexplained[:4]),
                            sum(abs(r["difference"]) for r in unexplained)))
        rows, entered, failing = _compare(months, "gross", by_month(deducted, "gross"), "gross", end)
        bad = [r for r in rows if r["difference"] and abs(r["difference"]) >= TOLERANCE and not r["note"]]
        checks.append(Check("T2", "Gross payments to subcontractors per month (books vs CIS300)",
                            "NOT RUN" if not entered else ("FAIL" if bad else "PASS"),
                            f"{failing} of {entered} month(s) differ" if entered else "No CIS300 gross figures entered", rows,
                            "Accountant", "Check the materials split (CIS300 box) and non-CIS suppliers in subcontractor costs"
                            if bad else "", sum(abs(r["difference"]) for r in bad)))
        # The rate is on the labour, materials left out (FA04 s61)
        base = lambda i: i.labour if i.labour else i.gross
        odd = [{"cash_date": i.cash_date.isoformat(), "contact": i.contact, "reference": i.reference, "gross": i.gross,
                "labour": i.labour, "deduction": i.amount, "rate": round(i.amount / base(i), 4)}
               for i in deducted.cash if base(i) and min(abs(i.amount / base(i) - r) for r in RATES) > 0.005]
        no_gross = sum(1 for i in deducted.cash if not i.gross)
        checks.append(Check("T3", "Deduction rate on each payment (20% / 30% / 0%)", "FAIL" if odd else "PASS",
                            f"{len(odd)} payment(s) at another rate" + (f"; {no_gross} without a gross amount" if no_gross else ""),
                            odd, "Client", "Please confirm the HMRC verification number and status for "
                            + ", ".join(sorted({o["contact"] for o in odd})[:5]) if odd else ""))

    # T4 / T5 / T6 / T7: the subcontractor side
    if suffered:
        rows, entered, failing = _compare(months, "suffered", by_month(suffered), "suffered_statements", end)
        checks.append(Check("T4", "CIS suffered per month (books vs contractors' statements)",
                            "NOT RUN" if not entered else ("FAIL" if failing else "PASS"),
                            f"{failing} of {entered} month(s) differ" if entered else "No contractor statements entered",
                            rows, "Client", "Please send the payment and deduction statements for the months that differ"
                            if failing else ""))
        # EPS claims are often made a month after the receipt: compared over each tax year, months shown for information
        rows, entered, _ = _compare(months, "suffered", by_month(suffered), "claimed_eps", end)
        by_year: Dict[str, List[float]] = {}
        for r, m in ((r, next(x for x in months if x["tax_month"] == r["tax_month"])) for r in rows if r["hmrc"] is not None):
            y = by_year.setdefault(m["tax_year"], [0.0, 0.0])
            y[0] += r["books"]
            y[1] += r["hmrc"]
        under = {y: round(b - h, 2) for y, (b, h) in by_year.items() if b - h >= TOLERANCE}
        checks.append(Check("T5", "CIS suffered claimed on the EPS (by tax year)",
                            "NOT RUN" if not entered else ("FAIL" if under else "PASS"),
                            ("; ".join(f"{y}: books {_money(b)}, claimed {_money(h)}" for y, (b, h) in by_year.items()))
                            if entered else "No EPS claims entered", rows, "Accountant",
                            "; ".join(f"{y}: {_money(v)} of CIS suffered not claimed on the EPS: claim in the same tax year, "
                                      f"or a repayment claim after 5 April" for y, v in under.items()), sum(under.values())))
        # T6: a surplus cannot roll into the next tax year: at month 12 it needs a repayment claim
        year_in = screen["year"]
        surplus_rows = []
        for ty in sorted({m["tax_year"] for m in months}):
            ms = [m for m in months if m["tax_year"] == ty]
            if not any(m["month_no"] == 12 for m in ms) or not any(m["hmrc"] for m in ms):
                continue
            claimed = sum(float(m["hmrc"].get("claimed_eps") or 0) for m in ms)
            # CIS suffered is set against PAYE tax, employer and employee NI, student loan and CIS deducted
            # (CIS 340 s1.11, CISR76020)
            due = sum(float(m["hmrc"].get(k) or 0) for m in ms
                      for k in ("paye_tax", "employer_nic", "employee_nic", "student_loan", "deducted")) \
                - sum(float(m["hmrc"].get("allowance") or 0) for m in ms)
            surplus_rows.append({"tax_year": ty, "months_entered": sum(1 for m in ms if m["hmrc"]), "claimed": round(claimed, 2),
                                 "due": round(due, 2), "surplus": round(claimed - due, 2)})
        failing6 = [r for r in surplus_rows if r["surplus"] >= TOLERANCE and not year_in.get("repayment_amount")]
        checks.append(Check("T6", "Same-tax-year offset (surplus at month 12 needs a repayment claim)",
                            "NOT RUN" if not surplus_rows else ("FAIL" if failing6 else "PASS"),
                            "; ".join(f"{r['tax_year']}: surplus {_money(r['surplus'])} ({r['months_entered']} months entered)"
                                      for r in surplus_rows) or "No tax year ends in the period with HMRC figures",
                            surplus_rows, "Accountant", "; ".join(f"{r['tax_year']} CIS surplus of {_money(r['surplus'])} not "
                                                                   f"reclaimed: confirm the repayment claim" for r in failing6),
                            sum(r["surplus"] for r in failing6)))
        # T7: CIS suffered should be about 20% of CIS labour income
        tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
        sales_codes = {c.std_code for c in db.execute(select(MasterCOA)).scalars() if c.category == "Sales"}
        labour = -sum(float(t.net_amount or 0) for t in tb if t.std_code in sales_codes and CIS_TEXT.search(t.raw_account_name or ""))
        if labour >= 1:
            rate = suffered.invoice_basis / labour
            ok = any(abs(rate - r) <= 0.02 for r in RATES)
            checks.append(Check("T7", "Expected CIS on labour income (about 20%)", "PASS" if ok else "INFO",
                                f"CIS suffered {_money(suffered.invoice_basis)} on CIS labour income {_money(labour)}: {rate:.1%}",
                                [], "Accountant", "" if ok else "The customer may hold gross payment status, or materials "
                                                                 "are not split from labour: check the invoices"))
        else:
            checks.append(Check("T7", "Expected CIS on labour income (about 20%)", "NOT RUN",
                                "No sales account named for CIS labour"))

    # T8: wages carrying CIS (codes.py's check)
    from backend.app.services.sop.common import gl_lines
    tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    t8 = [p for p in cis_points(tb, gl_lines(str(engagement.id), tb, db), set(), None) if p.ref == "CIS-T8"]
    checks.append(Check("T8", "Wages carrying CIS", "FAIL" if t8 else "PASS",
                        "; ".join(p.title for p in t8) or "No wages account carries CIS payments", [],
                        "Accountant", "; ".join(f"Approve the remap of {_money(p.amount)} from Wages to Subcontractor costs"
                                                for p in t8), sum(p.amount for p in t8)))

    # T9: CIS300 filed (or nil) by the 19th after each tax month
    if deducted:
        late = []
        for m in months:
            h, due = m["hmrc"], date.fromisoformat(m["tax_month"])
            due = date(due.year + (due.month == 12), due.month % 12 + 1, 19)
            if not h:
                continue
            if h.get("filed") in (None, "NO"):
                late.append({"tax_month": m["tax_month"], "label": m["label"], "problem": "not filed" if h.get("filed") == "NO" else "filing not entered"})
            elif h.get("filed_on") and date.fromisoformat(h["filed_on"]) > due:
                late.append({"tax_month": m["tax_month"], "label": m["label"], "problem": f"filed {h['filed_on']}, due {due.isoformat()}"})
        entered = sum(1 for m in months if m["hmrc"])
        checks.append(Check("T9", "CIS300 returns filed on time (by the 19th)",
                            "NOT RUN" if not entered else ("FAIL" if late else "PASS"),
                            f"{len(late)} month(s) late or not filed" if late else (f"{entered} month(s) filed" if entered else "No returns entered"),
                            late, "Accountant", "Late CIS300 penalties: £100 at 1 day, £200 at 2 months, £300 or 5% of the "
                                                "deductions at 6 and 12 months" if late else ""))

    # T10: the books' CIS and PAYE controls at the year end against the HMRC account balance, after timing items
    from backend.app.services.tax.ct_computation import final_balances
    bal = final_balances(str(engagement.id), tb, db)
    owed_books = -round(bal.get(CIS_SUFFERED, 0.0) + bal.get(CIS_DEDUCTED, 0.0) + bal.get(PAYE_CONTROL, 0.0), 2)
    timing = timing_items(cash, end)
    hmrc_cf = screen["year"].get("balance_cf")
    if hmrc_cf is None:
        checks.append(Check("T10", "Books to the HMRC account at the year end", "NOT RUN",
                            f"Books owe HMRC {_money(owed_books)} (4421 + 5321 + 5320); enter the HMRC balance at the year end",
                            [{"item": t["item"], "amount": t["amount"]} for t in timing]))
    else:
        after = round(owed_books + sum(t["effect"] for t in timing), 2)
        diff = round(after - float(hmrc_cf), 2)
        checks.append(Check("T10", "Books to the HMRC account at the year end", "PASS" if abs(diff) < TOLERANCE else "FAIL",
                            f"Books owe {_money(owed_books)}, after timing items {_money(after)}; HMRC {_money(float(hmrc_cf))}: "
                            f"difference {_money(diff)}",
                            [{"item": t["item"], "amount": t["amount"]} for t in timing], "Accountant",
                            f"Books and the HMRC PAYE / CIS account differ by {_money(diff)} after the timing items: "
                            f"reconcile before signing off" if abs(diff) >= TOLERANCE else "", abs(diff)))

    return {"on": True, "mode": screen["mode"], "checks": [asdict(c) for c in checks], "timing": timing,
            "sides": {s.name: {"cash": s.cash_total, "invoice_basis": s.invoice_basis, "opening_unpaid": s.opening_unpaid,
                               "closing_unpaid": s.closing_unpaid, "proof_difference": s.proof_difference,
                               "exceptions": s.exceptions} for s in cash.sides}}


def timing_items(cash: CisCash, period_end: date) -> List[Dict[str, Any]]:
    """What explains the books against HMRC at the year end. effect: what it adds to the amount owed to HMRC per the
    books to reach HMRC's view: CIS on unpaid sales invoices is in the books' asset but not yet reclaimable (+); CIS on
    unpaid bills is in the books' liability but not yet due (-)."""
    out = []
    for s in cash.sides:
        if s.closing_unpaid:
            out.append({"item": f"CIS on {'sales invoices' if s.name == 'suffered' else 'bills'} unpaid at the year end "
                                f"({len(s.unpaid)})", "amount": s.closing_unpaid,
                        "effect": s.closing_unpaid if s.name == "suffered" else -s.closing_unpaid,
                        "lines": [{"booked": i.booked.isoformat() if i.booked else None, "contact": i.contact,
                                   "reference": i.reference, "amount": i.amount, "note": i.note} for i in s.unpaid]})
        if s.opening_unpaid:
            out.append({"item": f"Last year's unpaid CIS {'received' if s.name == 'suffered' else 'paid'} this year",
                        "amount": s.opening_unpaid, "effect": 0.0, "lines": []})
        if s.journals:
            total = round(sum(j.amount for j in s.journals), 2)
            out.append({"item": f"CIS journals ({len(s.journals)}): the reviewer decides", "amount": total, "effect": 0.0,
                        "lines": [{"booked": j.booked.isoformat() if j.booked else None, "contact": j.contact,
                                   "reference": j.reference, "amount": j.amount, "note": j.note} for j in s.journals]})
    return out


def check_points(engagement: ClientEngagement, db: Session, setup_cis: Optional[Dict[str, Any]] = None) -> List[Check]:
    """The failing tests, for the review (T8 is raised by codes.py's check already)."""
    result = cis_checks(engagement, db, setup_cis)
    if not result.get("on"):
        return []
    return [Check(**c) for c in result["checks"] if c["status"] == "FAIL" and c["ref"] != "T8"]
