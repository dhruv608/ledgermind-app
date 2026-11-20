"""Family and loans: the High Income Child Benefit Charge, Marriage Allowance and student and postgraduate loan
repayments (R-FAM-01, 02, 04; SA100 2026 page TR5).

  Child Benefit   the charge falls on the partner with the higher adjusted net income (or the person alone): 1% of
                  the household's Child Benefit for every £200 of adjusted net income over £60,000 (ITEPA s681C); the
                  return's boxes are filled only by the one who pays. Who has the higher income is asked, never assumed
  Marriage        the person gives (TRANSFERRED: £1,260 less allowance) or receives (RECEIVED: a 20% reduction of
  Allowance       £1,260); neither may be taxed above the basic rate (ITA s55B): if they are, a Block until withdrawn
  loans           9% of income over the plan's threshold (the lowest when there are two plans), 6% over £21,000 for a
                  postgraduate loan, both together when both are owed; income is pay and trading profits, and all
                  unearned income once it is over £2,000 (CSLM16035); less what employers took through PAYE; nothing
                  while still studying or before repayments are due (R-FAM-02). Rounded down to the pound. An estimate
                  for the balance: the firm's tax software works out the repayment from the plan, so
                  the return needs the plan and the PAYE deductions"""

import math
from typing import Dict, List

from backend.app.sa.engine.calc import rates_for

PLANS = ("PLAN_1", "PLAN_2", "PLAN_4", "PLAN_5")
PLAN_LABELS = {"PLAN_1": "Plan 1", "PLAN_2": "Plan 2", "PLAN_4": "Plan 4 (Scotland)",
               "PLAN_5": "Plan 5 (England, courses from August 2023; repayments from April 2026)"}
ME, PARTNER = "ME", "PARTNER"
TRANSFERRED, RECEIVED = "TRANSFERRED", "RECEIVED"


def _f(v) -> float:
    return float(v or 0)


def plans_of(fam) -> List[str]:
    return [p for p in (fam.loan_plans or "").split(",") if p in PLANS] if fam else []


def student_loan(inc, fam, tax_year: str) -> Dict:
    """What the return charges for student and postgraduate loans, and how it is worked out."""
    r = rates_for(tax_year)["student_loan"]
    plans = plans_of(fam)
    pgl = bool(fam and fam.postgraduate)
    out = {"plans": plans, "postgraduate": pgl, "income": 0.0, "unearned": 0.0, "unearned_counted": False,
           "threshold": None, "due": 0.0, "pgl_due": 0.0, "deducted": 0.0, "pgl_deducted": 0.0, "charge": 0.0,
           "studying": bool(fam and fam.studying)}
    if not (plans or pgl) or out["studying"]:
        return out
    earned = inc.employment + inc.self_employment
    unearned = inc.property + inc.savings + inc.dividends + inc.foreign + inc.other + inc.pensions
    counted = unearned > r["unearned_over"]
    income = max(0.0, earned + (unearned if counted else 0.0) - inc.reliefs)
    out.update(income=round(income, 2), unearned=round(unearned, 2), unearned_counted=counted)
    threshold = min((r[p] for p in plans if p in r), default=None) if plans else None     # plan 5 from 2026-27
    if threshold is not None:
        out["threshold"] = threshold
        out["due"] = float(math.floor(max(0.0, income - threshold) * r["rate"]))
    if pgl:
        out["pgl_due"] = float(math.floor(max(0.0, income - r["postgraduate"]) * r["postgraduate_rate"]))
    out["deducted"], out["pgl_deducted"] = _f(fam.sl_deducted), _f(fam.pgl_deducted)
    # What employers took through PAYE comes off; more taken than due is refunded by the Student Loans Company
    out["charge"] = round(max(0.0, out["due"] - out["deducted"]) + max(0.0, out["pgl_due"] - out["pgl_deducted"]), 2)
    return out


def apply(inc, fam, tax_year: str) -> Dict:
    """The family facts into the engine's input; the loan working returned for the page."""
    if fam is None:
        return student_loan(inc, None, tax_year)
    if fam.child_benefit and fam.higher_income == ME:
        inc.child_benefit = _f(fam.child_benefit)
    if fam.marriage in (TRANSFERRED, RECEIVED):
        inc.marriage_allowance = fam.marriage.lower()
    loan = student_loan(inc, fam, tax_year)
    inc.student_loan = loan["charge"]
    return loan


def above_basic(calc: Dict) -> bool:
    return any(l["band"] in ("higher", "additional") and l["amount"] > 0 for l in calc["lines"])


def issues(fam, calc: Dict, answers: Dict[str, str], tax_year: str) -> List[Dict]:
    """What must be asked or decided before the family part of the return is right."""
    out = []
    ani = calc["adjusted_net_income"]
    hicbc_from = rates_for(tax_year)["hicbc"]["from"]
    cb = _f(fam.child_benefit) if fam else 0.0
    said_cb = answers.get("child_benefit") == "YES"
    if ani > hicbc_from and (cb or said_cb):
        if not cb:
            out.append({"key": "cb_amount", "kind": "CLIENT", "block": True,
                        "text": "How much Child Benefit did you and your partner get for the year, and for how many children?"})
        if not (fam and fam.higher_income):
            out.append({"key": "cb_higher", "kind": "CLIENT", "block": True,
                        "text": f"Your income is over £{hicbc_from:,.0f}. Do you have a partner, and if so, is their income "
                                f"higher than yours? (Only the one with the higher income pays the Child Benefit charge.)"})
    # Over £100,000 the personal allowance tapers away (ITA 2007 s35): a planning point (R-FAM-05)
    taper = rates_for(tax_year)["taper_from"]
    if ani > taper:
        lost = min(rates_for(tax_year)["personal_allowance"], (ani - taper) // 2)
        out.append({"key": "pa_taper", "kind": "DECISION", "block": False,
                    "text": f"Adjusted net income is £{ani:,.0f}, over £{taper:,.0f}: £{lost:,.0f} of the personal allowance is "
                            f"lost (£1 for every £2 over, ITA s35), so that slice is taxed at about 60%. A personal pension "
                            f"contribution or Gift Aid reduces adjusted net income: a planning point to raise with the "
                            f"client (R-FAM-05)."})
    if fam and fam.marriage in (TRANSFERRED, RECEIVED) and above_basic(calc):
        who = "gives" if fam.marriage == TRANSFERRED else "receives"
        # A filing point, not a block: the accountant chooses whether the election stands
        out.append({"key": "ma_rate", "kind": "DECISION", "block": False,
                    "text": f"Marriage Allowance: this person {who} it but is taxed above the basic rate, so it is not "
                            f"allowed (ITA s55B). Withdraw it before the return is finished."})
    if answers.get("student_loan") == "YES" and not (plans_of(fam) or (fam and fam.postgraduate)) and not (fam and fam.studying):
        out.append({"key": "sl_plan", "kind": "CLIENT", "block": True,
                    "text": "Which student loan plan are you on (Plan 1, 2 or 4), and do you have a postgraduate loan? "
                            "Please send your payslips or P60 showing what your employer took."})
    return out


def view(db, job) -> Dict:
    from backend.app.sa.income import calculation
    from backend.app.sa.models import SAFamily
    from backend.app.sa.signals import _answers
    fam = db.get(SAFamily, job.id)
    calc = calculation(db, job)
    c = calc["calculation"]
    answers = {k[2:]: a.value for k, a in _answers(db, job).items() if k.startswith("q:")}
    facts = {"child_benefit": _f(fam.child_benefit) if fam and fam.child_benefit is not None else None,
             "children": fam.children if fam else None, "cb_stopped": fam.cb_stopped if fam else None,
             "higher_income": fam.higher_income if fam else None, "marriage": fam.marriage if fam else None,
             "spouse_name": fam.spouse_name if fam else None, "loan_plans": plans_of(fam),
             "postgraduate": bool(fam and fam.postgraduate), "studying": bool(fam and fam.studying),
             "sl_deducted": _f(fam.sl_deducted) if fam and fam.sl_deducted is not None else None,
             "pgl_deducted": _f(fam.pgl_deducted) if fam and fam.pgl_deducted is not None else None}
    return {"facts": facts, "answers": {k: answers.get(k) for k in ("child_benefit", "married", "student_loan")},
            "adjusted_net_income": c["adjusted_net_income"], "hicbc": c["hicbc"],
            "marriage_reduction": (c.get("reductions") or {}).get("marriage_allowance", 0.0),
            "personal_allowance": c["personal_allowance"], "loan": calc.get("loan") or {},
            "issues": issues(fam, c, answers, job.tax_year),
            "plans": [{"plan": p, "label": PLAN_LABELS[p], "threshold": rates_for(job.tax_year)["student_loan"][p]} for p in PLANS
                      if p in rates_for(job.tax_year)["student_loan"]],
            "hicbc_from": rates_for(job.tax_year)["hicbc"]["from"]}


def save(db, job, body: Dict) -> None:
    from backend.app.sa.models import SAFamily
    fam = db.get(SAFamily, job.id)
    if fam is None:
        fam = SAFamily(job_id=job.id)
        db.add(fam)
    for k, v in body.items():
        if k == "loan_plans":
            v = ",".join(p for p in PLANS if p in (v or [])) or None
        elif k in ("postgraduate", "studying"):
            v = int(bool(v))
        setattr(fam, k, v)
    db.commit()
