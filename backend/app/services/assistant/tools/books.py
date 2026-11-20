"""Tools that read the books: overview, balances, ledger lines, review points, control accounts, journals, tax,
payroll, VAT returns, the asset register and monthly totals."""

import json
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from backend.app.models.database import (
    AuditFinding, FixedAssetRecord, GeneratedWorkpaper, GLTransaction, PayrollP32Record, ProposedJournal,
    SupplementaryDocument, TBRecord, VAT100Record,
)
from backend.app.services.assistant.tools.client_data import CT_SUMMARY, MAX_ROWS, ClientData, _cut, _date, _r, drcr, match_accounts

def client_overview(d: ClientData) -> Dict[str, Any]:
    e, p = d.eng, d.eng.profile
    # Profit before tax leaves out the tax charge (3800-3810); turnover is the Sales codes (below 500)
    pl = {code: v for code, v in d.final.items() if d.is_pl(code) and not 3800 <= code <= 3810}
    income = -sum(v for code, v in pl.items() if code < 500)
    findings = d.db.execute(select(AuditFinding.status).where(AuditFinding.engagement_id == e.id,
                                                              AuditFinding.procedure_ref != CT_SUMMARY)).scalars().all()
    docs = d.db.execute(select(SupplementaryDocument.doc_type).where(SupplementaryDocument.engagement_id == e.id)).scalars().all()
    wb = d.db.execute(select(GeneratedWorkpaper.generated_at).where(GeneratedWorkpaper.engagement_id == e.id)
                      .order_by(GeneratedWorkpaper.generated_at.desc())).scalars().first()
    out = {
        "client": e.client_name, "year_end": _date(e.period_end_date), "last_year_end": _date(e.prior_period_end_date),
        "software": e.source_system,
        "profit_before_tax": _r(-sum(pl.values())) if pl else None,
        "turnover": _r(income) if income else None,
        "accounts_in_tb": len(d.tb), "accounts_to_check": sum(1 for t in d.tb if t.mapping_status in ("NEEDS_REVIEW", "UNMAPPED")),
        "review_points": {"open": sum(1 for s in findings if s == "OPEN"), "total": len(findings)},
        "files_uploaded": sorted(set(docs)), "workbook_built": wb.isoformat(timespec="minutes") if wb else None,
    }
    if p is not None:
        out.update({
            "industry": p.industry_code, "vat_registered": p.is_vat_registered, "vat_scheme": p.vat_scheme,
            "payroll": p.has_payroll, "cis": p.cis_status, "framework": p.accounting_framework,
            "directors": json.loads(p.directors or "[]"),
        })
    return out


def account_balances(d: ClientData, search: str = "", section: str = "") -> Dict[str, Any]:
    """Final balances (TB plus approved journals) by firm code, with last year and the client's own account names."""
    names: Dict[int, List[str]] = {}
    for t in d.tb:
        if t.std_code is not None:
            names.setdefault(t.std_code, []).append(t.raw_account_name)
    codes = set(d.final) | set(d.last_year)
    s = (search or "").strip().lower()
    rows = []
    for code in sorted(codes):
        c = d.chart.get(code)
        name = c.std_name if c else str(code)
        if section and (("p" in section.lower()) != d.is_pl(code)):
            continue
        if s and not (s in name.lower() or s == str(code) or any(s in n.lower() for n in names.get(code, []))
                      or (c and s in (c.category or "").lower())):
            continue
        this, last = d.final.get(code, 0.0), d.last_year.get(code)
        if abs(this) < 0.005 and not last:
            continue
        rows.append({"code": code, "name": name, "category": c.category if c else "", "this_year": drcr(this),
                     "last_year": drcr(last),
                     "client_accounts": names.get(code, [])[:5]})
    return {"last_year_from": d.last_year_source or "not available",
            "count": len(rows), "rows": rows[:MAX_ROWS],
            "more": max(0, len(rows) - MAX_ROWS)}


def account_transactions(d: ClientData, account: str = "", search: str = "", date_from: str = "", date_to: str = "",
                         order: str = "date", limit: int = 40) -> Dict[str, Any]:
    """Ledger lines of one account (by the client's account name or a firm code), optionally filtered."""
    limit = max(1, min(int(limit or 40), 80))
    a = (account or "").strip().lower()
    wanted = set(match_accounts(d.tb, a))
    q = select(GLTransaction).where(GLTransaction.engagement_id == d.eng.id)
    if a:
        if not wanted:
            return {"error": f"No account matches '{account}'. Use account_balances to find the name."}
        q = q.where(GLTransaction.raw_account_name.in_(wanted))
    lines = list(d.db.execute(q).scalars())
    s = (search or "").strip().lower()
    if s:
        lines = [l for l in lines if s in (l.description or "").lower() or s in (l.reference or "").lower()]
    try:
        if date_from:
            lines = [l for l in lines if l.transaction_date and l.transaction_date >= date.fromisoformat(date_from)]
        if date_to:
            lines = [l for l in lines if l.transaction_date and l.transaction_date <= date.fromisoformat(date_to)]
    except ValueError:
        pass
    if order == "largest":
        lines.sort(key=lambda l: -abs(float(l.net_amount or 0)))
    else:
        lines.sort(key=lambda l: (l.transaction_date or date.min))
    return {
        "accounts": sorted(wanted)[:10], "lines": len(lines),
        "total_debit": _r(sum(float(l.debit_amount or 0) for l in lines)),
        "total_credit": _r(sum(float(l.credit_amount or 0) for l in lines)),
        "rows": [{"date": _date(l.transaction_date), "account": l.raw_account_name, "description": _cut(l.description, 120),
                  "ref": l.reference, "debit": _r(l.debit_amount), "credit": _r(l.credit_amount),
                  **({"vat": _r(l.vat_amount)} if l.vat_amount else {})} for l in lines[:limit]],
        "more": max(0, len(lines) - limit),
    }


def review_points(d: ClientData, status: str = "OPEN", search: str = "") -> Dict[str, Any]:
    q = select(AuditFinding).where(AuditFinding.engagement_id == d.eng.id, AuditFinding.procedure_ref != CT_SUMMARY)
    if status and status.upper() != "ALL":
        q = q.where(AuditFinding.status == status.upper())
    rows = list(d.db.execute(q).scalars())
    s = (search or "").strip().lower()
    if s:
        rows = [f for f in rows if s in (f.finding_title or "").lower() or s in (f.finding_details or "").lower()
                or s in (f.procedure_ref or "").lower()]
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    rows.sort(key=lambda f: (order.get(f.severity, 4), f.procedure_ref or ""))
    by_severity: Dict[str, int] = {}
    for f in rows:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
    # Full details only when few points are asked for; a long list gives the titles (search for one to see more)
    detail = 400 if len(rows) <= 8 else 0
    return {"count": len(rows), "by_severity": by_severity, "rows": [
        {"id": f.id, "ref": f.procedure_ref, "severity": f.severity, "title": _cut(f.finding_title, 140),
         **({"details": _cut(f.finding_details, detail)} if detail else {}),
         **({"amount": _r(f.quantified_amount)} if f.quantified_amount else {}),
         **({"status": f.status} if (status or "").upper() == "ALL" else {}),
         **({"cleared_note": _cut(f.cleared_note, 150)} if f.cleared_note else {})} for f in rows[:30]],
        "more": max(0, len(rows) - 30)}


def control_accounts(d: ClientData) -> Dict[str, Any]:
    from backend.app.services.reconciliation.control_accounts import reconciliations, summary
    s = summary(reconciliations(d.eng, d.db))
    # The screen's figures carry each row's own sign (VAT: owed to HMRC is positive; debtors and creditors: the
    # amount; payroll: the year's cost). Each is written out in words, so it cannot be misread
    def words(key: str, v) -> Optional[str]:
        if v is None:
            return None
        v = round(float(v), 2)
        amount = f"£{abs(v):,.2f}"
        if key.startswith("bank"):
            return drcr(v) + (" (overdrawn)" if v < 0 else " (cash at bank)")
        if key == "vat":
            return f"{amount} owed to HMRC" if v > 0 else f"{amount} due from HMRC (repayment)" if v < 0 else "£0.00"
        if key.startswith("payroll"):
            return f"{amount} cost for the year" if v >= 0 else f"{amount} credit (a negative cost)"
        if key == "ct":
            return f"{amount} tax charge" if v >= 0 else f"{amount} tax credit"
        return amount if v >= 0 else f"minus {amount}"

    out = []
    for r in s["rows"]:
        key = r.get("key", "")
        row = {k: v for k, v in r.items() if k in ("account", "area", "compared_with", "status", "tab", "note") and v not in ("", None)}
        row["books"] = words(key, r.get("books"))
        if r.get("other") is not None:
            row["other_figure"] = words(key, r["other"])
        if r.get("difference") is not None:
            row["difference"] = f"£{abs(float(r['difference'])):,.2f}"
        out.append(row)
    s["rows"] = out
    return s


def journals(d: ClientData, status: str = "") -> Dict[str, Any]:
    q = select(ProposedJournal).where(ProposedJournal.engagement_id == d.eng.id)
    if status:
        q = q.where(ProposedJournal.status == status.upper())
    rows = []
    for j in d.db.execute(q.order_by(ProposedJournal.id)).scalars():
        lines = [{"code": l.account_code, "account": l.account_name, "dr": _r(l.debit), "cr": _r(l.credit)} for l in j.lines] \
            or [{"code": j.debit_code, "account": j.debit_name, "dr": _r(j.amount), "cr": 0.0},
                {"code": j.credit_code, "account": j.credit_name, "dr": 0.0, "cr": _r(j.amount)}]
        rows.append({"ref": j.journal_ref, "description": _cut(j.description, 150), "status": j.status,
                     "source": j.source, "lines": lines[:8]})
    return {"count": len(rows), "rows": rows[:40], "more": max(0, len(rows) - 40)}


def tax_computation(d: ClientData) -> Dict[str, Any]:
    from backend.app.services.tax.ct_computation import ct_computation
    ct = ct_computation(d.eng, d.tb, d.db)
    return {
        "period": f"{ct.period_start} to {ct.period_end}", "profit_before_tax": _r(ct.profit_before_tax),
        "computation": [{"line": l.label, "amount": _r(l.amount), **({"note": _cut(l.note, 120)} if l.note else {})} for l in ct.lines][:40],
        "capital_allowances": [{"line": l.label, "amount": _r(l.amount)} for l in ct.capital_allowances][:15],
        "losses_used": _r(ct.losses_used), "losses_carried_forward": _r(ct.losses_carried_forward),
        "profits_chargeable": _r(ct.profits_chargeable), "corporation_tax": _r(ct.corporation_tax),
        "s455_tax": _r(ct.s455_tax), "total_tax": _r(ct.total_tax), "tax_in_accounts": _r(ct.tax_in_accounts),
        "difference_to_accounts": _r(ct.difference_to_accounts), "rates": ct.rate_slices,
        "to_confirm": [_cut(n, 200) for n in ct.notes][:10],
    }


def payroll(d: ClientData, by: str = "month") -> Dict[str, Any]:
    rows = list(d.db.execute(select(PayrollP32Record).where(PayrollP32Record.engagement_id == d.eng.id)).scalars())
    if not rows:
        return {"error": "No payroll report uploaded for this client."}
    fields = ("gross_pay", "tax_deducted", "employee_nic", "employer_nic", "pension_employee", "pension_employer", "net_pay")
    groups: Dict[str, Dict[str, float]] = {}
    for r in rows:
        key = (r.employee_name or "(not named)") if by == "employee" else (r.tax_month_label or _date(r.period_end) or "")
        g = groups.setdefault(key, {f: 0.0 for f in fields})
        for f in fields:
            g[f] += float(getattr(r, f) or 0)
    # Plain names for the answer's columns ('pension_employee' / 'pension_employer' both read as 'Pension (Emp)')
    label = {"gross_pay": "gross_pay", "tax_deducted": "paye_tax", "employee_nic": "employees_ni",
             "employer_nic": "employers_ni", "pension_employee": "staff_pension", "pension_employer": "employer_pension",
             "net_pay": "net_pay"}
    total = {label[f]: _r(sum(g[f] for g in groups.values())) for f in fields}
    return {"by": by, "total": total, "rows": [{"name": k, **{label[f]: _r(v) for f, v in g.items()}}
                                               for k, g in list(groups.items())[:40]], "more": max(0, len(groups) - 40)}


def vat_returns(d: ClientData) -> Dict[str, Any]:
    rows = list(d.db.execute(select(VAT100Record).where(VAT100Record.engagement_id == d.eng.id)
                             .order_by(VAT100Record.period_end)).scalars())
    if not rows:
        return {"error": "No VAT returns uploaded for this client."}
    paid: Dict[str, Any] = {}
    try:
        from backend.app.services.reconciliation.control_accounts import vat_paid_per_return
        got = vat_paid_per_return(d.eng, d.db)
        paid = {x["period_end"]: x for x in got["returns"]} if got["source"] else {}
    except Exception:
        d.db.rollback()
    return {"rows": [{"period": r.period_label, "start": _date(r.period_start), "end": _date(r.period_end),
                      "box1": _r(r.box1_vat_due_sales), "box4": _r(r.box4_vat_reclaimed), "box5": _r(r.box5_net_vat),
                      "box6": _r(r.box6_total_sales_ex_vat), "box7": _r(r.box7_total_purchases_ex_vat),
                      **({"paid": paid[_date(r.period_end)]["paid"], "unpaid": paid[_date(r.period_end)]["unpaid"]}
                         if _date(r.period_end) in paid else {})} for r in rows]}


def fixed_assets(d: ClientData) -> Dict[str, Any]:
    rows = list(d.db.execute(select(FixedAssetRecord).where(FixedAssetRecord.engagement_id == d.eng.id)).scalars())
    if not rows:
        return {"error": "No fixed asset register uploaded for this client."}
    tot = lambda f: _r(sum(float(getattr(r, f) or 0) for r in rows))
    return {"totals": {f: tot(f) for f in ("cost_bwd", "additions", "disposals", "cost_fwd", "depr_charge", "nbv")},
            "rows": [{"asset": _cut(r.description, 80), "category": r.category, "bought": _date(r.acquisition_date),
                      "additions": _r(r.additions), "cost_fwd": _r(r.cost_fwd), "depreciation": _r(r.depr_charge),
                      "nbv": _r(r.nbv)} for r in rows[:40]], "more": max(0, len(rows) - 40)}


def monthly_totals(d: ClientData, account: str = "", search: str = "") -> Dict[str, Any]:
    """Month by month movement (debits less credits) of the matching accounts from the ledger, this year and, when
    last year's client is in the app, last year: for trends and charts."""
    a = (account or "").strip().lower()
    if not a:
        return {"error": "Give an account name, firm code or words (e.g. 'sales', '3230', 'repairs')."}

    def months(engagement_id: str, tb: List[TBRecord]) -> Dict[str, float]:
        names = set(match_accounts(tb, a))
        if not names:
            return {}
        out: Dict[str, float] = {}
        q = select(GLTransaction).where(GLTransaction.engagement_id == engagement_id, GLTransaction.raw_account_name.in_(names))
        for l in d.db.execute(q).scalars():
            if not l.transaction_date or (search and search.lower() not in (l.description or "").lower()):
                continue
            key = l.transaction_date.strftime("%Y-%m")
            out[key] = out.get(key, 0.0) + float(l.debit_amount or 0) - float(l.credit_amount or 0)
        return out

    this = months(d.eng.id, d.tb)
    if not this:
        return {"error": f"No ledger lines for '{account}'. Use account_balances to find the account name."}
    rows = [{"month": date.fromisoformat(k + "-01").strftime("%b %Y"), "this_year": _r(v)} for k, v in sorted(this.items())]
    out: Dict[str, Any] = {"accounts": match_accounts(d.tb, a)[:15],
                           "sign": "debit positive (costs), credit negative (income)", "rows": rows,
                           "total_this_year": _r(sum(this.values()))}
    try:
        from backend.app.services.review.last_year import last_year_job
        last = last_year_job(d.eng, d.db)
        if last is not None:
            ly_tb = list(d.db.execute(select(TBRecord).where(TBRecord.engagement_id == last.id)).scalars())
            ly = months(last.id, ly_tb)
            # Same month a year earlier, set against this year's month
            for r, k in zip(rows, sorted(this)):
                y, m = int(k[:4]), int(k[5:])
                r["last_year"] = _r(ly.get(f"{y - 1:04d}-{m:02d}", 0.0))
            out["total_last_year"] = _r(sum(ly.values()))
    except Exception:
        d.db.rollback()
    return out
