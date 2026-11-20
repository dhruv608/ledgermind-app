"""Capital gains (SA108; R-SA108-01..06), disposal by disposal, then the year's tax.

  date        the date of disposal is the unconditional contract (TCGA s28, CG14250): it decides the tax year and the
              rates; a contract before 6 April belongs to the earlier year's return (R-SA108-06: amend that one)
  gain        proceeds less cost, buying and selling costs and improvements, the person's share of each; a negligible
              value claim makes a loss of the cost (R-SA108-04)
  home        private residence relief: the months it was the main home plus the final 9 months (s223), over the
              months owned; the rest of the gain is taxable (letting relief only with shared occupation: a decision)
  losses      this year's losses come off this year's gains in full; losses brought forward only down to the annual
              exempt amount (s2A, CG21520); what is left carries forward
  order       losses and the annual exempt amount go first to the gains taxed at the highest rate (s4B); Business
              Asset Disposal Relief gains use up the basic rate band first, then the other gains: the rate below the
              band, the higher rate above it
  rates       by the disposal date (rates.json: 2024-25 split at 30 October 2024)
  60 days     a UK home sold at a gain needs a return and payment within 60 days of completion; the tax paid then
              comes off the return's balance (boxes 9 and 10)
  shares      share and crypto cost uses the matching rules (same day, 30 days, section 104 pool: CG51560); the
              cost entered is the matched cost, worked out by the accountant"""

from datetime import date, timedelta
from typing import Dict, List, Optional

from backend.app.sa.engine.calc import _down, _p, rates_for

KINDS = {"RESIDENTIAL": "Residential property", "CRYPTO": "Cryptoassets", "OTHER": "Other property and assets",
         "LISTED": "Listed shares and securities", "UNLISTED": "Unlisted shares and securities"}
# SA108 2026 boxes for each section: number, proceeds, allowable costs, gains before losses, losses, claim code
BOXES = {"RESIDENTIAL": ("3", "4", "5", "6", "7", "8"), "CRYPTO": ("13.1", "13.2", "13.3", "13.4", "13.5", "13.6"),
         "OTHER": ("14", "15", "16", "17", "19", "20"), "LISTED": ("23", "24", "25", "26", "27", "28"),
         "UNLISTED": ("31", "32", "33", "34", "35", "36")}
FINAL_MONTHS = 9
DAYS_A_MONTH = 365.25 / 12


def _d(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _f(v) -> float:
    return float(v or 0)


def months_between(a: date, b: date) -> float:
    """Calendar months from a to b, part months by days (6 Oct 2015 to 6 Oct 2025 is exactly 120)."""
    whole = (b.year - a.year) * 12 + (b.month - a.month)
    return whole + (b.day - a.day) / DAYS_A_MONTH


def year_bounds(tax_year: str):
    y = int(tax_year[:4])
    return date(y, 4, 6), date(y + 1, 4, 5)


def period_rates(tax_year: str, when: Optional[date]) -> Dict:
    periods = rates_for(tax_year)["cgt"]["periods"]
    for p in periods:
        if when and date.fromisoformat(p["from"]) <= when <= date.fromisoformat(p["to"]):
            return p
    return periods[-1]


def one(d, tax_year: str, today: date, non_resident: bool = False) -> Dict:
    """A disposal's gain or loss, its rates, and what must be asked or decided about it."""
    share = _f(d.share) if d.share is not None else 1.0
    proceeds = round(_f(d.proceeds) * share, 2)
    allowable = round((_f(d.cost) + _f(d.costs) + _f(d.improvements)) * share, 2)
    if d.negligible:
        proceeds = 0.0
    before = round(proceeds - allowable, 2)
    start, end = year_bounds(tax_year)
    sold, completed, bought = _d(d.contract_date), _d(d.completion_date), _d(d.acquired)
    issues: List[Dict] = []
    notes: List[str] = []

    def issue(key, kind, text, block):
        issues.append({"key": f"{key}:{d.id}", "kind": kind, "text": text, "block": block})

    in_year = True
    if sold is None:
        issue("date", "CLIENT", f"{d.name}: please send the contract note or completion statement (the date of sale).", True)
    elif sold < start:
        in_year = False
        issue("year", "DECISION", f"{d.name}: the contract was on {sold:%d/%m/%Y}, before 6 April {start.year}: the gain belongs "
                                  f"to the earlier year's return (amend it), not this one (TCGA s28).", True)
    elif sold > end:
        in_year = False
        notes.append(f"{d.name}: the contract is after 5 April {end.year}: next year's return.")
    # No purchase cost: asked, except for a sale the share matching costed (a nil pool cost is real there, e.g. bonus
    # shares; a missing history is asked on the holding)
    if not d.negligible and _f(d.proceeds) and not _f(d.cost) and not getattr(d, "matched", False):
        issue("cost", "CLIENT", f"{d.name}: what did it cost, and what were the buying and selling costs (fees, stamp duty)? "
                                f"Please send the purchase papers.", True)
    # Nothing received: a gift or a transfer, taxed at market value (TCGA s17, s18) unless to a spouse living
    # together (no gain, no loss: TCGA s58)
    if not d.negligible and not _f(d.proceeds) and (_f(d.cost) or d.acquired):
        issue("gift", "CLIENT", f"{d.name}: no sale price. Was it a gift, or sold to family or a connected person? Then its "
                                f"market value on the date is used: please send a valuation. A transfer to a spouse or "
                                f"civil partner living together is no gain, no loss.", True)

    relief = 0.0
    if d.kind == "RESIDENTIAL" and d.main_home_months and before > 0:
        if bought and sold and sold > bought:
            owned = months_between(bought, sold)
            months = min(owned, d.main_home_months + FINAL_MONTHS)
            relief = round(before * months / owned, 2) if owned else 0.0
            if months < owned:
                notes.append(f"{d.name}: private residence relief for {months:.0f} of {owned:.0f} months "
                             f"(incl. the final {FINAL_MONTHS}); letting relief only with shared occupation.")
        else:
            issue("dates", "CLIENT", f"{d.name}: when was it bought? (private residence relief is by months owned)", True)
    gain = round(before - relief, 2)

    # A non-resident reports every UK residential disposal within 60 days, even with no gain (HS307)
    if d.kind == "RESIDENTIAL" and d.uk and (gain > 0 or non_resident) and in_year:
        if completed is None:
            issue("completion", "CLIENT", f"{d.name}: please send the completion statement (the 60-day return runs from completion).", True)
        else:
            due = completed + timedelta(days=rates_for(tax_year).get("cgt_return_days", 60))
            if not d.rtt_date:
                if today > due:
                    issue("rtt", "DECISION", f"{d.name}: the 60-day UK property return was due on {due:%d/%m/%Y} and has not been "
                                             f"sent. Send it and pay now (late filing penalty and interest).", True)
                else:
                    issue("rtt", "DECISION", f"{d.name}: send the 60-day UK property return and payment by {due:%d/%m/%Y}.", False)
            elif _d(d.rtt_date) and _d(d.rtt_date) > due:
                notes.append(f"{d.name}: the 60-day return was sent late ({_d(d.rtt_date):%d/%m/%Y}, due {due:%d/%m/%Y}): penalty likely.")
    if d.negligible:
        notes.append(f"{d.name}: negligible value claim: a loss of the cost (R-SA108-04).")
    if d.kind == "UNLISTED" and gain < 0 and in_year:
        issue("income_loss", "DECISION", f"{d.name}: a loss on unlisted shares may be set against income (share loss relief, "
                                         f"ITA s131; EIS/SEIS: R-SA108-05). Decide whether to claim.", False)
    rates = period_rates(tax_year, sold)
    return {"id": d.id, "kind": d.kind, "kind_label": KINDS.get(d.kind, d.kind), "name": d.name, "proceeds": proceeds,
            "allowable": allowable, "before_relief": before, "relief": relief, "gain": gain, "in_year": in_year,
            "badr": bool(d.badr), "rate_class": "badr" if d.badr else ("residential" if d.kind == "RESIDENTIAL" else "other"),
            "rates": rates, "rtt_gain": _f(d.rtt_gain), "rtt_tax": _f(d.rtt_tax), "negligible": bool(d.negligible),
            "issues": issues, "notes": notes, "sold": d.contract_date, "doc_id": d.doc_id,
            "input": {"kind": d.kind, "name": d.name, "acquired": d.acquired, "contract_date": d.contract_date,
                      "completion_date": d.completion_date, "proceeds": _f(d.proceeds), "cost": _f(d.cost), "costs": _f(d.costs),
                      "improvements": _f(d.improvements), "share": share, "uk": bool(d.uk), "main_home_months": d.main_home_months,
                      "badr": bool(d.badr), "negligible": bool(d.negligible), "rtt_date": d.rtt_date,
                      "rtt_gain": _f(d.rtt_gain) if d.rtt_gain is not None else None,
                      "rtt_tax": _f(d.rtt_tax) if d.rtt_tax is not None else None, "note": getattr(d, "note", None)}}


def compute(disposals: List[Dict], losses_bf: float, tax_year: str, taxable_income: float, basic_limit: float) -> Dict:
    """The year's gains, losses, annual exempt amount and tax."""
    exempt = rates_for(tax_year)["cgt"]["exempt"]
    rows = [r for r in disposals if r["in_year"]]
    gains = [r for r in rows if r["gain"] > 0]
    current_losses = round(-sum(r["gain"] for r in rows if r["gain"] < 0), 2)
    total_gains = round(sum(r["gain"] for r in gains), 2)
    net = round(total_gains - current_losses, 2)
    bf_used = round(min(losses_bf, max(0.0, net - exempt)), 2)
    exempt_used = round(min(exempt, max(0.0, net - bf_used)), 2)
    loss_cf = round(losses_bf - bf_used + max(0.0, -net), 2)

    # Losses and the exempt amount to the gains at the highest rate first (BADR gains last)
    def top(r):
        return 0.0 if r["rate_class"] == "badr" else r["rates"][r["rate_class"]][1]
    left = current_losses + bf_used + exempt_used
    chunks = []
    for r in sorted(gains, key=top, reverse=True):
        cut = min(left, r["gain"])
        left -= cut
        if r["gain"] - cut > 0:
            chunks.append((r, round(r["gain"] - cut, 2)))
    band = max(0.0, basic_limit - taxable_income)
    lines, tax = [], 0.0
    for r, amount in [c for c in chunks if c[0]["rate_class"] == "badr"]:
        rate = r["rates"]["badr"]
        lines.append({"name": r["name"], "band": "BADR", "amount": amount, "rate": rate, "tax": _down(amount * rate)})
        band = max(0.0, band - amount)
    others = [c for c in chunks if c[0]["rate_class"] != "badr"]
    # The basic rate band to the gains it saves most on
    for r, amount in sorted(others, key=lambda c: c[0]["rates"][c[0]["rate_class"]][1] - c[0]["rates"][c[0]["rate_class"]][0], reverse=True):
        low, high = r["rates"][r["rate_class"]]
        below = min(amount, band)
        band -= below
        for part, rate, name in ((below, low, "basic"), (amount - below, high, "higher")):
            if part > 0:
                lines.append({"name": r["name"], "band": name, "amount": round(part, 2), "rate": rate, "tax": _down(part * rate)})
    tax = _p(sum(l["tax"] for l in lines))
    paid = _p(sum(r["rtt_tax"] for r in rows))
    return {"gains": total_gains, "losses": current_losses, "net": net, "losses_bf": losses_bf, "losses_bf_used": bf_used,
            "exempt": exempt, "exempt_used": exempt_used, "chargeable": round(sum(a for _, a in chunks), 2),
            "loss_cf": loss_cf, "lines": lines, "tax": tax, "paid_60_day": paid, "badr_gains": round(sum(r["gain"] for r in gains if r["badr"]), 2)}


def sections(rows: List[Dict]) -> List[Dict]:
    """SA108 boxes per section."""
    out = []
    for kind, (n, proceeds, costs, gains, losses, code) in BOXES.items():
        mine = [r for r in rows if r["in_year"] and r["kind"] == kind]
        if not mine:
            continue
        sec = [{"box": n, "label": "Number of disposals", "value": str(len(mine))},
               {"box": proceeds, "label": "Disposal proceeds", "value": round(sum(r["proceeds"] for r in mine), 2)},
               {"box": costs, "label": "Allowable costs (including purchase price)", "value": round(sum(r["allowable"] for r in mine), 2)},
               {"box": gains, "label": "Gains in the year, before losses", "value": round(sum(r["gain"] for r in mine if r["gain"] > 0), 2)},
               {"box": losses, "label": "Losses in the year", "value": round(-sum(r["gain"] for r in mine if r["gain"] < 0), 2)}]
        if any(r["relief"] for r in mine):
            sec.append({"box": code, "label": "Claim or election code", "value": "PRR"})
        if kind == "RESIDENTIAL" and any(r["rtt_gain"] or r["rtt_tax"] for r in mine):
            sec.append({"box": "9", "label": "Total gains on UK residential property reported on 60-day returns",
                        "value": round(sum(r["rtt_gain"] for r in mine), 2)})
            sec.append({"box": "10", "label": "Tax on gains in box 9 already charged", "value": round(sum(r["rtt_tax"] for r in mine), 2)})
        out.append({"kind": kind, "label": KINDS[kind], "rows": sec})
    return out


def no_return_when_no_tax(rows: List[Dict], summary: Dict, non_resident: bool = False) -> None:
    """The 60-day UK property return is needed only when there is tax to pay: a
    gain the year's losses and the annual exempt amount cover needs none (a UK resident), so its point becomes a note.
    A person not resident in the UK reports every UK land disposal within 60 days, even with no tax or a loss (HS307)."""
    if summary["tax"] or non_resident:
        return
    for row in rows:
        if any(i["key"].startswith("rtt:") for i in row["issues"]):
            row["issues"] = [i for i in row["issues"] if not i["key"].startswith("rtt:")]
            row["notes"].append(f"{row['name']}: no capital gains tax to pay this year (losses and the annual exempt "
                                f"amount cover it), so no 60-day UK property return was needed.")


def for_job(db, job, calc: Optional[Dict] = None, today: Optional[date] = None) -> Dict:
    """Every disposal of the job and the year's capital gains tax, given the income tax calculation."""
    from backend.app.sa.models import SACapital, SADisposal
    today = today or date.today()
    ds = db.query(SADisposal).filter(SADisposal.job_id == job.id).order_by(SADisposal.contract_date, SADisposal.id).all()
    non_resident = (calc or {}).get("class4_exempt") == "NON_RESIDENT"     # the accountant's 'not UK resident'
    rows = [one(d, job.tax_year, today, non_resident) for d in ds]
    # Sales of shares and crypto worked out from the trades (sharematch.py): their cost by the matching rules
    from backend.app.sa.sharematch import disposals as matched
    sm = matched(db, job)
    for d in sm["disposals"]:
        row = one(d, job.tax_year, today, non_resident)
        row["matched"] = True
        rows.append(row)
    cap = db.get(SACapital, job.id)
    losses_bf = _f(cap.losses_bf) if cap else 0.0
    taxable = sum((calc or {}).get("taxable", {}).values()) if calc else 0.0
    r = rates_for(job.tax_year)
    extension = 0.0
    if calc and "extension" in calc:
        extension = calc["extension"]
    summary = compute(rows, losses_bf, job.tax_year, taxable, r["basic_band"] + extension)
    no_return_when_no_tax(rows, summary, non_resident)
    issues = [i for row in rows for i in row["issues"]]
    for h in sm["holdings"]:
        issues += [{"key": f"holding:{h['holding']}:{n}", "kind": "CLIENT", "block": True,
                    "text": f"{h['holding']}: {t} Please send the contract notes or the broker's statement."}
                   for n, t in enumerate(h["issues"])]
    return {"disposals": rows, "summary": summary, "sections": sections(rows), "holdings": sm["holdings"],
            "issues": issues, "notes": [n for row in rows for n in row["notes"]]}
