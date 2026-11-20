"""The tax calculation made from the job's lines (engine/calc.py), with Class 4, loss and marriage allowance choices."""

import json
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.sa.engine.calc import Income, calculate
from backend.app.sa.extract import p60
from backend.app.sa.models import SADocument, SAJob, SALine


def _used(line: SALine) -> float:
    return float(line.amount or 0) * float(line.share if line.share is not None else 1)


def to_income(job: SAJob, lines: List[SALine]) -> Tuple[Income, List[str]]:
    """The engine's input from the lines in use, and what the calculation cannot take yet."""
    inc = Income(tax_year=job.tax_year)
    notes: List[str] = []
    for l in lines:
        if not l.include:
            continue
        v, tax = _used(l), float(l.tax_paid or 0)
        s, k = l.source, l.kind
        if s == "EMPLOYMENT":
            inc.employment += v
        elif s == "SELF_EMPLOYMENT":
            inc.self_employment += v
        elif s == "PROPERTY":
            inc.property += v
            inc.finance_costs += float(l.extra or 0) * float(l.share or 1)
        elif s == "SAVINGS":
            if k != "ISA":
                inc.savings += v
        elif s == "DIVIDENDS":
            inc.dividends += v
        elif s == "PENSIONS":
            inc.pensions += v
        elif s == "FOREIGN":
            inc.foreign += v
            if tax:                                # foreign tax is not UK tax deducted: a credit (Foreign page)
                notes.append(f"Foreign tax of £{tax:,.2f} on {l.label or 'foreign income'}: enter the income on the "
                             f"Foreign page for the foreign tax credit.")
                continue
        elif s == "RELIEFS":
            if k == "GIFT_AID":
                inc.gift_aid_gross += round(v / 0.8, 2)
            elif k == "PENSION_RAS":
                inc.pension_ras_gross += round(v / 0.8, 2)
            elif k in ("VCT", "EIS", "SEIS"):
                inc.investments[k] = inc.investments.get(k, 0.0) + v
            elif k == "LOAN_INTEREST":
                inc.loan_interest += v
        inc.tax_deducted += tax
    return inc, notes


def calculation(db: Session, job: SAJob) -> dict:
    from backend.app.sa.property import pooled
    lines = db.query(SALine).filter(SALine.job_id == job.id).all()
    inc, notes = to_income(job, lines)
    prop = pooled(db, job)
    if prop["properties"]:
        inc.property += prop["profit"]
        inc.finance_costs += prop["finance_costs"]
        if prop["loss_cf"]:
            notes.append(f"UK property loss of £{prop['loss_cf']:,.2f} to carry forward to next year.")
        if prop["boxes"]["CAPITAL"]:
            notes.append(f"£{prop['boxes']['CAPITAL']:,.2f} of property spending kept out as capital (an improvement): "
                         f"logged as cost for capital gains.")
    from backend.app.sa.trade import all_businesses
    trade = all_businesses(db, job)
    if trade["businesses"]:
        inc.self_employment += trade["taxable_profit"]
        inc.tax_deducted += trade["cis_deducted"]           # CIS taken off by contractors is tax paid
        if trade["loss_cf"]:
            notes.append(f"Trading loss of £{trade['loss_cf']:,.2f} to carry forward, unless it is claimed against other "
                         f"income this year or last: choose it on Tax calculation (SOP N1).")
        for b in trade["businesses"]:
            notes.extend(f"{b['name']}: {w}" for w in b["warnings"])
    # Foreign income by kind (foreign.py): before the loans, which count it as unearned income
    from backend.app.sa import foreign
    from backend.app.sa.property import ALLOWANCE
    frows = foreign.load(db, job)
    foreign.apply(inc, frows)
    # Overseas lettings: their own property business (SA106 F4-F5), non-savings income, the same finance cost rule
    fprop = pooled(db, job, overseas=True, allowance_left=ALLOWANCE - prop["allowance_used"])
    prows = []
    if fprop["properties"]:
        inc.foreign += fprop["profit"]
        inc.overseas_property += fprop["profit"]
        inc.overseas_finance_costs += fprop["finance_costs"]   # its own credit, limited by the overseas profit
        if fprop["loss_cf"]:
            notes.append(f"Overseas property loss of £{fprop['loss_cf']:,.2f} to carry forward (against overseas property only).")
        # Each country's part of the profit taxed (after last year's losses), for the credit
        ratio = fprop["profit"] / fprop["before_losses"] if fprop["before_losses"] > 0 else 0.0
        prows = [foreign.property_row({**c, "profit": round(c["profit"] * ratio, 2)}) for c in fprop["countries"] if c["foreign_tax"]]
    # Child Benefit charge, Marriage Allowance and loan repayments from the family facts (family.py)
    from backend.app.sa.family import PARTNER, apply
    from backend.app.sa.models import SAFamily
    fam = db.get(SAFamily, job.id)
    loan = apply(inc, fam, job.tax_year)
    # No Marriage Allowance set on the family page: the P60's tax code shows it (R-FAM-04: N gives it, M receives it)
    if not (fam and fam.marriage):
        ma = marriage_from_codes(db, job)
        if ma:
            inc.marriage_allowance = ma.lower()
            notes.append(f"Marriage Allowance {'given to the spouse' if ma == 'TRANSFERRED' else 'received'} as the P60's "
                         f"tax code shows (R-FAM-04): confirm it on Family and loans.")
    # Foreign Tax Credit Relief on the finished figures, source by source
    foreign.credits(inc, frows + prows)
    fprop["credits"] = prows
    notes.extend(n for r in frows for n in r["notes"])
    if fam is not None and fam.child_benefit and fam.higher_income == PARTNER:
        notes.append("Child Benefit: the partner has the higher income, so any charge is on their return, not this one.")
    # Foster, kinship and shared-lives care (foster.py, R-SP-01): only receipts over the limit are taxed, as trade
    from backend.app.sa.foster import for_job as foster_for
    care = foster_for(db, job)
    if care["profit"]:
        inc.self_employment += care["profit"]
    if care["exempt"]:
        notes.append(f"Care payments of £{care['receipts']:,.2f} are under the qualifying care limit of £{care['limit']:,.2f}: "
                     f"not taxed (R-SP-01).")
    # Payments on account already made for the year, and voluntary Class 2 (SAPayments: R-FAM-03, R-NIC-01)
    from backend.app.sa.models import SAPayments
    paid = db.get(SAPayments, job.id)
    if paid is not None:
        inc.payments_on_account_made = float(paid.poa_paid or 0)
        inc.class2_voluntary = bool(paid.class2_voluntary)
    from backend.app.sa.signals import _answers
    kept = _answers(db, job)
    inc.has_trade = bool(trade["businesses"]) or bool(care["profit"])
    c4 = (kept[CLASS4_KEY].value or "") if CLASS4_KEY in kept else ""
    inc.class4_exempt = c4 if c4 in CLASS4_EXEMPT else ""        # NONE: checked, not exempt
    claim = (kept[LOSS_KEY].value or "") if LOSS_KEY in kept else ""
    trade["loss_claim"] = loss_claim(inc, trade, claim, notes)
    calc = calculate(inc)
    # Residential finance costs the 20% credit could not use carry forward (ITTOIA s274A)
    prop["finance_cf"] = round(max(inc.finance_costs - calc.finance_costs_relieved, 0.0), 2) if inc.finance_costs else 0.0
    if prop["finance_cf"]:
        notes.append(f"Unused residential finance costs of £{prop['finance_cf']:,.2f} carry forward to next year.")
    if inc.overseas_finance_costs:
        fprop["finance_cf"] = round(max(inc.overseas_finance_costs - calc.overseas_finance_costs_relieved, 0.0), 2)
        if fprop["finance_cf"]:
            notes.append(f"Unused overseas residential finance costs of £{fprop['finance_cf']:,.2f} carry forward "
                         f"(against overseas property only).")
    checks = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.status.in_(("CHECK", "UNREADABLE"))).count()
    if checks:
        notes.append(f"{checks} document(s) to look at on Documents: the figures may change.")
    sources = json.loads(job.sources or "[]")
    have = ({l.source for l in lines if l.include} | ({"PROPERTY"} if prop["properties"] else set())
            | ({"SELF_EMPLOYMENT"} if trade["businesses"] else set()))
    for s in sources:
        if s not in have:
            notes.append(f"No figures yet for {s.replace('_', ' ').lower()}.")
    # Capital gains tax (cgt.py): on top of income tax, into the balance; never in payments on account (TMA s59A)
    from backend.app.sa.cgt import for_job
    c = calc.as_dict()
    c["class4_checked"] = bool(c4)
    c["extension"] = round(inc.gift_aid_gross + inc.pension_ras_gross, 2)
    cg = for_job(db, job, c)
    s = cg["summary"]
    c["cgt"], c["cgt_paid"] = s["tax"], s["paid_60_day"]
    if s["tax"] or s["paid_60_day"]:
        c["liability"] = round(c["liability"] + s["tax"], 2)
        c["balance"] = round(c["balance"] + s["tax"] - s["paid_60_day"], 2)
        c["due_31_january"] = round(c["due_31_january"] + s["tax"] - s["paid_60_day"], 2)
    if s["loss_cf"]:
        notes.append(f"Capital losses of £{s['loss_cf']:,.2f} to carry forward.")
    notes.extend(cg["notes"])
    return {"income": inc.__dict__, "calculation": c, "property": prop, "trade": trade, "notes": notes, "care": care,
            "loan": loan, "cgt": cg, "foreign": frows, "foreign_property": fprop}


CLASS4_KEY, LOSS_KEY = "nic:class4", "loss:claim"         # the accountant's choices on Tax calculation (SAAnswer)
CLASS4_EXEMPT = ("PENSION_AGE", "UNDER_16", "NON_RESIDENT")
CLASS4_CHOICES = CLASS4_EXEMPT + ("NONE",)
LOSS_CLAIMS = ("CURRENT", "PRIOR", "CARRY_FORWARD")


def loss_claim(inc, trade: Dict, claim: str, notes: List[str]) -> Dict:
    """This year's trading loss as the accountant chose: set against the other income of this year
    (ITA 2007 s64(2)(a), SA103S box 33 / SA103F 78), of last year (s64(2)(b), box 34 / 79), or carried forward against
    the same trade (s83, box 35 / 80). A claim against income is capped at the greater of £50,000 or 25% of adjusted
    total income (s24A); the part over the cap carries forward. With no choice the loss carries forward."""
    loss = trade.get("loss_year", 0.0)
    out = {"loss": loss, "claim": claim, "current": 0.0, "back": 0.0, "cap": None}
    if not loss:
        return out
    if claim not in ("CURRENT", "PRIOR"):
        return out
    notes[:] = [n for n in notes if "unless it is claimed against other income" not in n]
    if claim == "CURRENT":
        other = calculate(inc).total_income          # this year's income, the loss not yet set against it
        ati = max(other - inc.pension_ras_gross, 0.0)  # adjusted total income (s24A(5)): less gross relief-at-source pensions
        cap = round(max(50000.0, 0.25 * ati), 2)
        used = round(min(loss, other, cap), 2)
        out.update(current=used, cap=cap)
        inc.reliefs += used
        if loss > used:
            why = "the cap" if cap < min(loss, other) else "the other income"
            notes.append(f"Trading loss of £{loss:,.2f}: £{used:,.2f} set against other income this year (box 33 / 78); "
                         f"£{loss - used:,.2f} is over {why} and carries forward.")
    else:
        out["back"] = loss
        notes.append(f"Trading loss of £{loss:,.2f} carried back to last year's income (box 34 / 79, ITA 2007 s64(2)(b)): "
                     f"the relief is given in last year's terms. Check last year's income takes it all and the £50,000 or "
                     f"25% cap (s24A) on that year; any part left over carries forward.")
    # Into each business, in order, off its loss carried forward (for the boxes)
    left = {"loss_current": out["current"], "loss_back": out["back"]}
    for b in trade["businesses"]:
        for k in left:
            take = round(min(left[k], b["loss_year"] - b["loss_current"] - b["loss_back"]), 2)
            if take > 0:
                b[k] = round(b[k] + take, 2)
                b["loss_cf"] = round(b["loss_cf"] - take, 2)
                left[k] = round(left[k] - take, 2)
    trade["loss_cf"] = round(sum(b["loss_cf"] for b in trade["businesses"]), 2)
    return out


def marriage_from_codes(db: Session, job: SAJob) -> Optional[str]:
    """TRANSFERRED or RECEIVED when a P60 on the return has a tax code ending in N or M (HMRC applied the transfer)."""
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "P60",
                                         SADocument.status.in_(("READ", "CHECK"))):
        f = json.loads(d.fields) if d.fields else {}
        if f.get("other_person") or f.get("tax_year") not in (None, job.tax_year):
            continue
        suffix = p60.code_parts(f.get("tax_code"))["suffix"]
        if suffix in ("N", "M"):
            return "TRANSFERRED" if suffix == "N" else "RECEIVED"
    return None
