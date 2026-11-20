"""The points a sole trade raises for the accountant (R-SA103-03, -09, -11, -14), never a change to the figures:

  loss          a loss: carry it forward or set it against other income (ITA s64), with the commerciality test (s66)
  stopped       the period ends before the tax year does: the cessation date is the last day of trading, not the last
                receipt; money in after it is a post-cessation receipt, not turnover
  construction  a building trade with no CIS statements: is it under the Construction Industry Scheme?
  cash basis    on entry to the cash basis, the unrelieved value of plant other than cars is deducted"""

import json
import re
from typing import Dict, List

# Fares and taxis (R-SA103-12: each journey classified); 'commute' or 'to work' on the line is disallowed until decided
FARES = re.compile(r"\btaxi|\buber\b|\bbolt\b|\btrain|\brail|\bfare|\bbus\b|\btfl\b|transport for london|\bcoach\b", re.I)
SHARED = re.compile(r"\bsplit (with|between)\b|\bshared? with\b|\bhalf (to|with|for)\b|\bjointly with\b|"
                    r"\bin partnership\b|\bwith my (sister|brother|wife|husband|partner|son|daughter|mother|father)\b", re.I)
COMMUTE_WORDS = re.compile(r"\bcommut|\bto work\b", re.I)
BUILDING = re.compile(r"build|construct|plaster|drylin|joiner|carpent|electric|plumb|roof|labour|scaffold|bricklay|"
                      r"decorat|tiler|groundwork|landscap", re.I)


# A vehicle's running costs (the flat rate replaces them; parking, tolls and congestion charges are not in it)
VEHICLE_RUNNING = re.compile(r"\bfuel\b|petrol|diesel|\bshell\b|\besso\b|\btexaco\b|\bbp\b|\bpfs\b|pay ?at ?pump|"
                             r"\bgarage\b|\bmot\b|\btyres?\b|kwik fit|halfords|service station|filling station|"
                             r"car insurance|motor insurance|\bdvla\b|vehicle tax", re.I)
VAT_THRESHOLD = 90000.0          # from 1 April 2024 (VAT Notice 700/1); each year's figure in the rates table if set


def vehicle_points(lines: List[Dict], biz, row: Dict) -> List[Dict]:
    """A vehicle's running costs from the bank against the mileage flat rate: one method per
    vehicle. Parking and tolls go with either, so they are left out of the actual costs."""
    actual = round(sum(l["out"] - l["in"] for l in lines if l["heading"] == "TRAVEL"
                       and VEHICLE_RUNNING.search(l["description"] or "")), 2)
    if actual < 1:
        return []
    flat = float(row.get("mileage") or 0)
    if flat:
        return [{"key": f"vehicle-both:{biz.id}", "kind": "DECISION", "block": False,
                 "text": f"{biz.name}: actual vehicle running costs £{actual:,.2f} (fuel, repairs, insurance, MOT) v the "
                         f"mileage flat rate £{flat:,.2f}. Choose one method per vehicle and keep it: the flat rate covers "
                         f"the running costs, so both cannot be claimed (BIM75005; SOP S17, S18)."}]
    return []


def private_use_points(lines: List[Dict], biz, pcts: Dict) -> List[Dict]:
    """A mixed-use cost with no business % given: the client is asked the %; for a vehicle the flat rate
    by business miles is the other way. Done once the % is entered on the bank page."""
    from backend.app.sa.books import mixed_use
    out = []
    for m in mixed_use(lines, pcts):
        if m["business_pct"] is not None:
            continue
        extra = (" Or give the business miles for the year (from a log or a signed estimate): the flat rate of 45p / 25p a "
                 "mile may be used instead of the running costs (SOP S18)." if m["kind"] == "VEHICLE" else "")
        out.append({"key": f"pu:{biz.id}:{m['kind']}", "kind": "CLIENT", "block": False,
                    "text": f"{m['label']} of £{m['amount']:,.2f} for {biz.name}: what percentage is business use? Only "
                            f"the business share is allowed (SOP X2, S13).{extra}"})
    return out


def bank_points(db, job, biz, row: Dict = None) -> List[Dict]:
    """The bank statements' own checks: statements that do not cover the period (Missing), a balance that does not
    carry on (Error: a page or statement missing), a transfer with no matching line in another account (Missing),
    lines left for the client; then personal-looking payees in the costs. Raised as open points, not blocks: an account
    opened in the year has no statements to upload, so a block could not be cleared."""
    from backend.app.sa import books
    try:
        accts = books.accounts(db, job)
        start, end = books.period(job, biz)
        lines = books.sort_lines(accts, job.person_name, start, end, books.choices_of(db, job), books.remittances(db, job),
                                 books.employers(db, job), lets=books.lets_property(db, job))
    except Exception:
        return []
    out = []
    from datetime import date as _dt
    short, chains = [], []
    for acct, bank, a in accts:
        if str(acct).startswith("file "):
            continue                    # a file with no account number (a receipt, one page): its dates prove nothing
        name = f"{bank or 'Bank'} {acct}"
        # The dates are the first and last lines', not the statements' own: a month's grace either end (a quiet first
        # week is not a missing statement)
        late = a.first and (_dt.fromisoformat(a.first) - _dt.fromisoformat(start)).days > 31
        early = a.last and (_dt.fromisoformat(end) - _dt.fromisoformat(a.last)).days > 31
        if late or early:
            short.append(f"{name} " + (f"from {a.first}" if late else "from the start") + (f" to {a.last}" if early else ""))
        breaks = [c for c in a.checks if "the page before ends at" in c]
        if breaks:
            chains.append(f"{name} ({breaks[0][:110]})")
    if short:
        out.append({"key": f"stmt-cover:{biz.id}", "kind": "CLIENT", "block": False,
                    "text": f"The statements do not cover {start} to {end}: " + "; ".join(short[:4])
                            + (f" and {len(short) - 4} more" if len(short) > 4 else "") + ". Please upload the missing "
                            "statements, or tell us when an account opened or closed (SOP S01)."})
    if chains:
        out.append({"key": f"stmt-chain:{biz.id}", "kind": "CLIENT", "block": False,
                    "text": "The balance does not carry on between statements: " + "; ".join(chains[:3])
                            + ". A statement or page is missing: please send it (SOP S02)."})
    lone = [l for l in lines if l["heading"] == books.TRANSFER and not l["sure"] and not l["chosen"]]
    if lone:
        eg = "; ".join(f"{l['on']} '{l['description'][:40]}' £{(l['in'] or l['out']):,.2f}" for l in lone[:3])
        out.append({"key": f"stmt-transfer:{biz.id}", "kind": "CLIENT", "block": False,
                    "text": f"{len(lone)} transfer(s) go to or come from an account we do not have ({eg}). Upload its "
                            f"statements or tell us what they were for (SOP S03)."})
    # A selling platform's payouts as the takings with no report of its own: sales are net of its fees
    payouts = [l for l in lines if l["heading"] == "TURNOVER" and not l["chosen"]
               and (l["how"] or "").startswith(("a payout from a selling platform", "a payout from a selling platform in"))]
    if payouts:
        named = sorted({w for l in payouts for w in re.findall(r"[a-z]{3,}", l["description"].lower())
                        if w in books.PAYOUT_PLATFORMS})
        total = round(sum(l["in"] for l in payouts), 2)
        out.append({"key": f"stmt-platform:{biz.id}", "kind": "CLIENT", "block": False,
                    "text": f"Sales of £{total:,.2f} are payouts from {', '.join(named) or 'a selling platform'}, net of its "
                            f"fees. Please upload the platform's yearly report so the gross sales and the fees can be "
                            f"shown (SOP T1, S05)."})
    ask = [l for l in lines if l["heading"] == books.ASK and not l["chosen"]]
    if ask:
        out.append({"key": f"stmt-ask:{biz.id}", "kind": "CLIENT", "block": False,
                    "text": f"{len(ask)} bank transaction(s) need your answer before the return can be finished: "
                            + "; ".join(f"{l['on']} '{l['description'][:40]}'" for l in ask[:3]) + " (SOP S04)."})
    pu = [] if (row or {}).get("trading_allowance") else private_use_points(lines, biz, books.private_use(db, job, biz))
    if (row or {}).get("mileage"):
        pu = [p for p in pu if not p["key"].endswith(":VEHICLE")]     # the flat rate is used: the vehicle point decides it
    return out + personal_points(lines, biz) + vehicle_points(lines, biz, row or {}) + pu


def personal_points(lines: List[Dict], biz) -> List[Dict]:
    """Payees that look personal (a supermarket, a gym, streaming) with PERSONAL_REGULAR or more lines under a business
    cost heading: 'looks personal, confirm it was for the business'. Nothing is moved."""
    from backend.app.sa import books
    from backend.app.sa.trade import HEADINGS
    by: Dict[str, List[Dict]] = {}
    for l in lines:
        h = l["heading"]
        d = l["description"] or ""
        # A supermarket's petrol station ('TESCO PAY AT PUMP') or a phone bill ('SKY MOBILE') is a mixed-use cost (asked
        # as a business %), not a personal shop
        if any(words.search(d) for _, _, words in books.MIXED.values()):
            continue
        if l["out"] > 0 and h in HEADINGS and HEADINGS[h][2] == "cost" and books.PERSONAL_PAYEE.search(d):
            by.setdefault(books.payee_word(l["description"]) or l["description"][:20].lower(), []).append(l)
    out = []
    for payee, ls in sorted(by.items()):
        if len(ls) >= books.PERSONAL_REGULAR:
            total = round(sum(l["out"] for l in ls), 2)
            heads = ", ".join(sorted({HEADINGS[l["heading"]][0] for l in ls}))
            out.append({"key": f"personal:{biz.id}:{payee[:30]}", "kind": "DECISION", "block": False,
                        "text": f"{biz.name}: '{ls[0]['description'][:50]}' looks personal: {len(ls)} payments, £{total:,.2f}, "
                                f"under {heads}. Confirm it was for the business, or move it to drawings on the bank page "
                                f"(wholly and exclusively, ITTOIA 2005 s34; SOP check S14)."})
    return out


def points(db, job, calc: Dict) -> List[Dict]:
    from backend.app.sa.books import accounts
    from backend.app.sa.income import tax_year_dates
    from backend.app.sa.models import SAAllowance, SABusiness, SADocument
    out: List[Dict] = []
    _, year_end = (d.isoformat() for d in tax_year_dates(job.tax_year))
    has_cis = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "CIS_STATEMENT").count() > 0
    rows = {r["id"]: r for r in calc["trade"]["businesses"]}
    sheet_income = 0.0
    for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "CLIENT_ACCOUNTS",
                                         SADocument.status.in_(("READ", "CHECK"))):
        sheet_income += sum(float(r.get("income") or 0) for r in (json.loads(d.fields or "{}").get("rows") or []))
    has_bank = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "BANK_STATEMENT").count() > 0
    has_vat = db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "VAT_RETURN").count() > 0
    from backend.app.sa.signals import _answers
    _kept = _answers(db, job)
    _vat, _cash = _kept.get("q:vat"), _kept.get("q:cash")
    vat_answer = _vat.value if _vat else None
    cash_answer = _cash.value if _cash else None
    for biz in db.query(SABusiness).filter(SABusiness.job_id == job.id):
        row = rows.get(biz.id) or {}
        # The client's own sheet against the bank's takings (the sheet is not added when the bank gives the trade)
        bank_income = float(row.get("income") or 0)
        if has_bank and sheet_income and bank_income and abs(sheet_income - bank_income) > 0.05 * max(sheet_income, bank_income):
            out.append({"key": f"sheet:{biz.id}", "kind": "DECISION", "block": False,
                        "text": f"{biz.name}: the client's own sheet shows income of £{sheet_income:,.2f}, the bank statements "
                                f"£{bank_income:,.2f}. Find the difference (income not banked, other accounts, or money in "
                                f"that is not takings)."})
        # The client's sheet: costs left for a decision, and miles not yet set on the business (R-SA103-12, -13)
        from backend.app.sa.books import period
        from backend.app.sa.extract import client_sheet
        sheet_rows = [r for d in db.query(SADocument).filter(SADocument.job_id == job.id, SADocument.kind == "CLIENT_ACCOUNTS",
                                                              SADocument.status.in_(("READ", "CHECK")))
                      for r in (json.loads(d.fields or "{}").get("rows") or [])]
        # A second version of the sheet repeats the first one's rows: each row once (as sync_client_sheets does)
        seen_rows: set = set()
        sheet_rows = [r for r in sheet_rows if not ((k := (r.get("on"), r.get("income"), r.get("expense"),
                                                            (r.get("detail") or "").lower())) in seen_rows or seen_rows.add(k))]
        if sheet_rows:
            sheet = client_sheet.lines(sheet_rows, *period(job, biz))
            if sheet["miles"] and biz.car_miles is None:
                out.append({"key": f"miles:{biz.id}", "kind": "DECISION", "block": False,
                            "text": f"{biz.name}: {sheet['miles']:,.0f} miles on the client's sheet. Which are business journeys "
                                    f"and which are home to a regular place of work (commuting, not allowed: BIM37605)? Enter "
                                    f"the business miles for the flat rate (R-SA103-12)."})
            # Income shared with another person ('invoice shared with a relative'): a partnership or a sole trade? (R-SA103-15)
            unpriced = [r for r in sheet_rows if r.get("no_amount")]
            if unpriced:
                out.append({"key": f"sheet-noamt:{biz.id}", "kind": "CLIENT", "block": True,
                            "text": "Your sheet lists income with no amount: " + "; ".join(f"'{(r.get('detail') or '')[:80]}'"
                                    for r in unpriced[:3]) + ". How much was received, and when?"})
            shared = [r for r in sheet_rows if (r.get("income") or r.get("no_amount"))
                      and SHARED.search(f"{r.get('detail') or ''} {r.get('party') or ''}")]
            if shared:
                what = "; ".join(f"'{(r.get('detail') or '')[:70]}'" + (f" £{r['income']:,.2f}" if r.get("income") else "")
                                 for r in shared[:3])
                out.append({"key": f"split-q:{biz.id}", "kind": "CLIENT", "block": False,
                            "text": f"Your sheet shows income shared with someone else ({what}). Who is it shared with, what "
                                    f"share is theirs, and is there an agreement to work together? (R-SA103-15)"})
                out.append({"key": f"split:{biz.id}", "kind": "DECISION", "block": True,
                            "text": f"{biz.name}: income shared with another person on the client's sheet. Decide: a "
                                    f"partnership (each partner's share on SA104) or the client's own trade with a payment "
                                    f"to the other person as a cost (R-SA103-15)."})
            # The same item paid in instalments ('University Fee' each month) is one point, with how many and the total
            grouped: Dict = {}
            for why, text, amount in sheet["decisions"]:
                g = grouped.setdefault((why, text), [0, 0.0])
                g[0] += 1
                g[1] += amount
            for (why, text), (count, amount) in grouped.items():
                if count > 1:
                    text = f"{text} ({count} payments)"
                out.append({"key": f"sheetdec:{biz.id}:{why}:{text[:40]}", "kind": "DECISION", "block": False,
                            "text": f"{biz.name}: '{text[:80]}' £{amount:,.2f} on the client's sheet is not allowed until "
                                    f"decided ({why}: R-SA103-12 / -13 / -14)."})
        # VAT-registered: the returns cover the period, and their net sales agree with the net takings (R-SA103-16)
        from backend.app.sa.income import vat_returns
        returns = []
        if has_vat:
            start, end = period(job, biz)
            returns = vat_returns(db, job, start, end)
        if returns:
            from datetime import date as _d
            days = (_d.fromisoformat(end) - _d.fromisoformat(start)).days + 1
            covered = set()
            for f in returns:
                a, b = max(f["period_from"], start), min(f["period_to"], end)
                covered |= {(_d.fromisoformat(a).toordinal() + i) for i in range((_d.fromisoformat(b) - _d.fromisoformat(a)).days + 1)}
            if len(covered) < 0.95 * days:
                out.append({"key": f"vat-cover:{biz.id}", "kind": "CLIENT", "block": False,
                            "text": f"The VAT returns sent cover {len(covered)} of the {days} days of the trade's year. Please send "
                                    f"the VAT returns for the missing quarters (R-SA103-16)."})
            net_sales = round(sum((f.get("box6") or 0) * f["part"] for f in returns), 2)
            from backend.app.sa.books import FROM_BANK
            from backend.app.sa.models import SABusinessItem as _BI
            bank_based = db.query(_BI).filter(_BI.business_id == biz.id, _BI.description == FROM_BANK).count() > 0
            turnover = float(row.get("income") or 0)
            if not bank_based:
                out.append({"key": f"vat-sheet:{biz.id}", "kind": "DECISION", "block": False,
                            "text": f"{biz.name} is VAT registered and its figures are not from the bank: check they are net of "
                                    f"VAT (the returns' net sales are £{net_sales:,.2f}) (R-SA103-16)."})
            elif net_sales and turnover and abs(turnover - net_sales) > 0.05 * net_sales:
                out.append({"key": f"vat-rec:{biz.id}", "kind": "DECISION", "block": False,
                            "text": f"{biz.name}: takings net of VAT are £{turnover:,.2f}, the VAT returns' net sales £{net_sales:,.2f} "
                                    f"for the same period. Find the difference (sales not banked, money in that is not "
                                    f"sales, or a return missing) (R-SA103-16)."})
        if row.get("loss_year"):
            # This year's loss: done once the choice is made on Tax calculation
            chosen = (calc["trade"].get("loss_claim") or {}).get("claim")
            out.append({"key": f"loss:{biz.id}", "kind": "DECISION", "block": False, "page": "tax", "done": bool(chosen),
                        "text": f"{biz.name}: a loss of £{row['loss_year']:,.2f}. Set it against other income this year or "
                                f"last (ITA 2007 s64; capped at the greater of £50,000 or 25% of adjusted total income, "
                                f"s24A), only if the trade is run commercially with a view to profit (s66), or carry it "
                                f"forward against the same trade (s83). Choose it on Tax calculation (SOP N1, S22)."})
        # VAT: over the registration threshold and not registered; registered with no VAT returns, so the bank's figures
        # still include VAT
        from backend.app.sa.engine.calc import rates_for
        threshold = rates_for(job.tax_year).get("vat_threshold", VAT_THRESHOLD)
        turnover = float(row.get("headings", {}).get("TURNOVER", {}).get("amount") or 0)
        registered = has_vat or vat_answer == "YES"
        if turnover > threshold and not registered:
            out.append({"key": f"vat-over:{biz.id}", "kind": "DECISION", "block": False,
                        "text": f"{biz.name}: turnover £{turnover:,.2f} is over the VAT registration threshold of "
                                f"£{threshold:,.0f} and no VAT registration is known. Check the rolling 12 months' taxable "
                                f"turnover: VAT registration may be required (BIM31515, SOP N8, S24). Set 'VAT registered' "
                                f"on This year if it is."})
        if vat_answer == "YES" and not has_vat:
            from backend.app.sa.books import FROM_BANK
            from backend.app.sa.models import SABusinessItem as _BI2
            if db.query(_BI2).filter(_BI2.business_id == biz.id, _BI2.description == FROM_BANK).count():
                out.append({"key": f"vat-gross:{biz.id}", "kind": "CLIENT", "block": True,
                            "text": f"You are VAT registered: income and expenses must be net of VAT, and the figures for "
                                    f"{biz.name} come from the bank (VAT included). Please send the VAT returns for the "
                                    f"year (SOP N7, S25)."})
        # A cash business with no cash takings entered: the turnover from the bank leaves
        # out the cash kept back; added as a turnover line on the business
        if cash_answer == "YES":
            from backend.app.sa.books import FROM_BANK
            from backend.app.sa.income import VAT_OUT
            from backend.app.sa.models import SABusinessItem as _BI3
            hand = db.query(_BI3).filter(_BI3.business_id == biz.id, _BI3.heading == "TURNOVER",
                                         ~_BI3.description.in_((FROM_BANK, VAT_OUT))).count()
            if not hand:
                out.append({"key": f"cash:{biz.id}", "kind": "CLIENT", "block": False,
                            "text": f"Cash takings not paid into the bank must be added to {biz.name}'s turnover. Please "
                                    f"give the total for the year, or send the till record (SOP T2, S07)."})
        # Regular personal-looking payees sorted as business costs: to confirm
        if has_bank:
            out.extend(bank_points(db, job, biz, row))
        if biz.period_end and biz.period_end < year_end:
            later = 0.0
            try:
                for _acct, _bank, acc in accounts(db, job):
                    later += sum(l.money_in for l in acc.lines if l.on and biz.period_end < l.on <= year_end)
            except Exception:
                pass
            extra = (f" £{later:,.2f} came into the bank after it: post-cessation receipts (other income), not turnover."
                     if later else "")
            out.append({"key": f"stopped:{biz.id}", "kind": "DECISION", "block": False,
                        "text": f"{biz.name}: the period ends {biz.period_end}, before the tax year does. Confirm the last day "
                                f"of trading (the cessation date, not the last receipt) and that the records reach it."
                                + extra + " (R-SA103-09)"})
        # The bank lines of the trade: building work paid in ('casual labour', a builder), and fares and taxis to classify
        try:
            from backend.app.sa.books import view
            bank = view(db, job, biz)["lines"]
        except Exception:
            bank = []
        building_in = [l for l in bank if l["heading"] == "TURNOVER" and l["in"] and BUILDING.search(l["description"] or "")]
        fares = [l for l in bank if l["heading"] == "TRAVEL" and l["out"] and FARES.search(l["description"] or "")]
        if fares:
            to_work = [l for l in fares if COMMUTE_WORDS.search(l["description"] or "")]
            out.append({"key": f"fares:{biz.id}", "kind": "DECISION", "block": bool(to_work),
                        "text": f"{biz.name}: {len(fares)} taxi and fare payments (£{sum(l['out'] for l in fares):,.2f}). Classify "
                                f"each journey: from a home base or to a temporary workplace is allowed; home to a regular "
                                f"workplace is commuting, not allowed" + (f" ({len(to_work)} say 'to work': disallowed until "
                                f"decided)" if to_work else "") + " (R-SA103-12)."})
        if ((BUILDING.search(f"{biz.name} {biz.description or ''}") or building_in) and not has_cis
                and not float(biz.cis_deducted or 0)):
            out.append({"key": f"cis:{biz.id}", "kind": "CLIENT", "block": False,
                        "text": f"Is your work for {biz.name} construction work under the Construction Industry Scheme (CIS)? "
                                f"If so, please send the payment and deduction statements from each contractor (R-SA103-11)."})
        # Costs paid to individuals for their work (a subcontractor, a helper): their invoices; one of the client's own
        # family name is a related party (R-SA103-17)
        from backend.app.sa.books import from_a_person
        people = [l for l in bank if l["out"] and l["heading"] in ("SUBCONTRACTORS", "STAFF", "OTHER", "COST_OF_SALES")
                  and from_a_person(l["description"] or "")]
        if sum(l["out"] for l in people) >= 250:                # small sums are not worth a question
            out.append({"key": f"people:{biz.id}", "kind": "CLIENT", "block": False,
                        "text": f"{biz.name}: {len(people)} payments to individuals as costs (£{sum(l['out'] for l in people):,.2f}). "
                                f"Please send their invoices or a note of the work each did (R-SA103-17)."})
            names = [w for w in (job.person_name or "").split() if w.isalpha() and w.upper() not in ("MIKE", "E2E", "MR", "MRS", "MS", "MISS")]
            surname = names[-1].lower() if len(names) >= 2 else None
            family = [l for l in people if surname and re.search(rf"\b{re.escape(surname)}\b", l["description"] or "", re.I)]
            if family:
                out.append({"key": f"family:{biz.id}", "kind": "DECISION", "block": False,
                            "text": f"{biz.name}: £{sum(l['out'] for l in family):,.2f} paid as costs to someone of the client's "
                                    f"family name: a related party. Is the work real and paid at a market rate? Otherwise "
                                    f"not a cost of the trade (R-SA103-17)."})
        pools = [a for a in db.query(SAAllowance).filter(SAAllowance.business_id == biz.id)
                 if (a.kind or "") in ("MAIN", "SPECIAL") and float(a.amount or 0)]
        if biz.cash_basis and pools:
            out.append({"key": f"cashentry:{biz.id}", "kind": "DECISION", "block": False,
                        "text": f"{biz.name} is on the cash basis with a capital allowance pool for plant: if this is its "
                                f"first cash basis year, the unrelieved value of plant other than cars is deducted as a cost "
                                f"instead (R-SA103-03)."})
    return out
