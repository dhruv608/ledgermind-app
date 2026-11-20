"""The Payroll summary: month by month from the payroll reports, in three tables, Total, Employees and Directors:

  pay date, gross wages, PAYE, employee's NI, student loan, employee's pension, employer's NI, net wages, employer's
  pension, PAYE liability for the month, employment allowance, total PAYE liability, pension payable

PAYE liability = PAYE + employee's and employer's NI + student loan, less statutory pay recovered (what HMRC collects
through PAYE); employment allowance = that liability less what the report says is due to HMRC (when the report gives
it); pension payable = employee's and employer's pension. A person is a director when their name is one of the
directors on Client details (the same matching as Companies House: same first name, every word of the shorter name in
the longer one)."""

import json
from collections import OrderedDict
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, PayrollP32Record

COLUMNS = ("gross", "paye", "ee_ni", "student_loan", "ee_pension", "er_ni", "net", "er_pension",
           "liability", "allowance", "total_liability", "pension_payable")


def _num(v) -> float:
    return float(v or 0)


def payroll_summary(engagement: ClientEngagement, db: Session) -> Dict[str, Any]:
    from backend.app.services.setup.companies_house import same_person

    profile = getattr(engagement, "profile", None)
    try:
        directors = [d for d in json.loads(getattr(profile, "directors", None) or "[]") if isinstance(d, str) and d]
    except ValueError:
        directors = []
    records = [r for r in db.execute(select(PayrollP32Record).where(PayrollP32Record.engagement_id == engagement.id)).scalars()
               if r.period_end and "annual" not in (r.tax_month_label or "").lower()]
    named = any(r.employee_name for r in records)

    def is_director(name: str) -> bool:
        return any(same_person(name, d) for d in directors)

    # Employment allowance by month: from the report (liability less due to HMRC) when it gives what is due, else the
    # allowance the PAYE month by month table finds in the ledger (payroll_months), so the two screens agree
    ledger_allowance: Dict[str, float] = {}

    def from_ledger() -> Dict[str, float]:
        if not ledger_allowance:
            from backend.app.services.papers.payroll_months import payroll_by_month
            paye = next((t for t in payroll_by_month(engagement, db)["tables"] if t["key"] == "paye"), None)
            for m in (paye or {}).get("months", []):
                ledger_allowance[m["month"][:7]] = float(m.get("allowance") or 0)
            ledger_allowance.setdefault("_", 0.0)
        return ledger_allowance

    def table(rows: List[PayrollP32Record], whole: bool = False) -> Dict[str, Any]:
        months: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for r in sorted(rows, key=lambda r: r.period_end):
            key = r.period_end.strftime("%Y-%m")
            m = months.setdefault(key, {"month": key, "pay_date": r.period_end.isoformat(), **{c: 0.0 for c in COLUMNS},
                                        "_due": 0.0, "_due_given": True})
            m["pay_date"] = max(m["pay_date"], r.period_end.isoformat())
            m["gross"] += _num(r.gross_pay)
            m["paye"] += _num(r.tax_deducted)
            m["ee_ni"] += _num(r.employee_nic)
            m["student_loan"] += _num(r.student_loan)
            m["ee_pension"] += _num(r.pension_employee)
            m["er_ni"] += _num(r.employer_nic)
            m["net"] += _num(r.net_pay)
            m["er_pension"] += _num(r.pension_employer)
            liability = (_num(r.tax_deducted) + _num(r.employee_nic) + _num(r.employer_nic) + _num(r.student_loan)
                         - _num(r.statutory_pay_recovered))
            m["liability"] += liability
            m["_due"] += _num(r.total_hmrc_due)
            m["_due_given"] = m["_due_given"] and r.total_hmrc_due is not None and _num(r.total_hmrc_due) != 0
        out = []
        for m in months.values():
            m["allowance"] = (max(0.0, m["liability"] - m["_due"]) if m["_due_given"]
                              else from_ledger().get(m["month"], 0.0) if whole else 0.0)
            m["total_liability"] = m["liability"] - m["allowance"]
            m["pension_payable"] = m["ee_pension"] + m["er_pension"]
            out.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items() if not k.startswith("_")})
        total = {c: round(sum(m[c] for m in out), 2) for c in COLUMNS}
        return {"months": out, "total": total, "people": len({r.employee_name for r in rows if r.employee_name})}

    tables = [{"key": "total", "title": "Total", **table(records, whole=True)}]
    # The split only when a director is on the payroll (else Employees would repeat the total)
    on_payroll = [r for r in records if is_director(r.employee_name or "")] if named and directors else []
    if on_payroll:
        staff = [r for r in records if not is_director(r.employee_name or "")]
        if staff:
            tables.append({"key": "employees", "title": "Employees", **table(staff)})
        tables.append({"key": "directors", "title": "Directors", **table(on_payroll)})
    return {
        "tables": tables,
        "has_reports": bool(records),
        # The directors on the payroll by their payroll names (the wages T splits payments by them)
        "director_names": sorted({r.employee_name for r in on_payroll if r.employee_name}),
        "split": ("" if on_payroll else
                  "No director is on the payroll" if named and directors else
                  "The payroll report has no names, so employees and directors cannot be split" if records and not named else
                  "No directors on Client details, so employees and directors cannot be split" if records else ""),
    }
