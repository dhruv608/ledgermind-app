"""Foreign income (SA106 pages F2-F3; R-SA106-01..07), source by source, in pounds.

  kinds     interest is savings income and dividends are dividend income (their own rates and allowances); a foreign
            pension is taxed in full from 6 April 2017 (ITEPA s575, EIM75500; the old 10% 'exemption' in column F
            ended then); benefits and other income as non-savings
  treaty    the firm's treaty table (parameters/treaties.json): UK_ONLY means no credit, the foreign tax is reclaimed
            in that country (R-SA106-02); BOTH with a treaty rate limits the credit to that rate; a country and kind
            not in the table is an accountant decision before the credit is relied on
  credit    Foreign Tax Credit Relief, source by source: the lower of the foreign tax (as the treaty allows) and the
            UK tax on that income, worked out as the tax with it less the tax without it (R-SA106-04, HS263); without
            a claim the foreign tax is deducted from the income instead
  years     a country whose tax year is not 6 April to 5 April: its figures are time-apportioned (R-SA106-05)
  unknown   income from abroad said Yes, but nothing entered: a Block (R-SA106-07)"""

import copy
import json
from pathlib import Path
from typing import Dict, List

from backend.app.sa.engine.calc import calculate

TABLE = json.loads((Path(__file__).parent / "parameters" / "treaties.json").read_text(encoding="utf-8"))
KINDS = {"INTEREST": "Interest and other income from overseas savings", "DIVIDEND": "Dividends from foreign companies",
         "PENSION": "Overseas pension", "BENEFIT": "Overseas social security benefit", "OTHER": "Other overseas income"}


def pension_taxed(tax_year: str) -> float:
    """The part of an overseas pension that is taxed: all of it from 6 April 2017 (ITEPA s575 as amended by FA 2017
    Sch 3; EIM75500: 90% only for payments before then)."""
    from backend.app.sa.engine.calc import rates_for
    return float(rates_for(tax_year).get("foreign_pension_taxed", 1.0))


# SA106 page F3: the column F total box for each section
F_BOX = {"INTEREST": "4", "DIVIDEND": "6", "PENSION": "9", "BENEFIT": "9", "OTHER": "9"}
SECTION = {"INTEREST": "Interest and other income from overseas savings", "DIVIDEND": "Dividends from foreign companies",
           "PENSION": "Overseas pensions, social security benefits and royalties",
           "BENEFIT": "Overseas pensions, social security benefits and royalties",
           "OTHER": "Overseas pensions, social security benefits and royalties"}


def name_of(code: str) -> str:
    return TABLE["names"].get(code, code)


def treaty(country: str, kind: str):
    k = "PENSION" if kind == "PENSION" else kind
    return next((r for r in TABLE["rows"] if r["country"] == country and r["kind"] == k), None)


def one(f, tax_year: str = "2025-26") -> Dict:
    share = float(f.share if f.share is not None else 1)
    gross = round(float(f.amount or 0) * share, 2)
    tax = round(float(f.foreign_tax or 0) * share, 2)
    exempt = round(gross * (1 - pension_taxed(tax_year)), 2) if f.kind == "PENSION" else 0.0
    t = treaty(f.country, f.kind)
    issues: List[Dict] = []
    notes: List[str] = []
    where = f"{f.payer or KINDS[f.kind]} ({name_of(f.country)})"
    creditable = 0.0
    if f.claim:
        taxable = round(gross - exempt, 2)
        if t and t["taxed_in"] == "UK_ONLY":
            if tax:
                issues.append({"key": f"reclaim:{f.id}", "kind": "CLIENT", "block": False,
                               "text": f"{where}: {name_of(f.country)} took £{tax:,.2f} tax, but under the treaty only the UK may tax "
                                       f"it, so no UK credit is given. Please reclaim it from {name_of(f.country)} (we can help)."})
        elif t and t.get("max_rate") is not None:
            creditable = min(tax, round(gross * t["max_rate"], 2))
        else:
            creditable = tax
            if tax:
                # The UK has treaties with most countries: a note, not a decision for every country
                notes.append(f"{where}: credit for the foreign tax paid, up to the UK tax on it; if it is more than the "
                             f"treaty rate, the excess is reclaimed in {name_of(f.country)}.")
    else:
        taxable = round(gross - exempt - tax, 2)          # deduction relief: the foreign tax comes off the income
    if f.country in TABLE["tax_years"]:
        notes.append(f"{where}: {name_of(f.country)}'s tax year runs {TABLE['tax_years'][f.country]}: the figures are "
                     f"time-apportioned to 6 April to 5 April (R-SA106-05).")
    return {"id": f.id, "country": f.country, "country_name": name_of(f.country), "kind": f.kind, "kind_label": KINDS[f.kind],
            "payer": f.payer, "gross": gross, "foreign_tax": tax, "exempt": exempt, "taxable": taxable, "claim": bool(f.claim),
            "creditable": creditable, "credit": 0.0, "treaty": t["article"] if t else None, "issues": issues, "notes": notes,
            "doc_id": f.doc_id,
            "input": {"country": f.country, "kind": f.kind, "payer": f.payer, "amount": float(f.amount or 0),
                      "foreign_tax": float(f.foreign_tax or 0), "share": share, "claim": bool(f.claim), "note": f.note}}


def property_row(c: Dict) -> Dict:
    """An overseas property country as a source for the credit: its profit is already in the income; the foreign tax
    on it is creditable (the country where the land is may tax it)."""
    taxable = max(0.0, c["profit"])
    return {"id": f"property-{c['country']}", "country": c["country"], "country_name": name_of(c["country"]),
            "kind": "PROPERTY", "kind_label": "Overseas property", "payer": "Property income", "gross": taxable,
            "foreign_tax": c["foreign_tax"], "exempt": 0.0, "taxable": taxable, "claim": True,
            "creditable": c["foreign_tax"], "credit": 0.0, "treaty": None, "issues": [], "notes": [], "doc_id": None}


def _add(inc, r: Dict, sign: float = 1.0) -> None:
    if r["kind"] == "INTEREST":
        inc.savings += sign * r["taxable"]
    elif r["kind"] == "DIVIDEND":
        inc.dividends += sign * r["taxable"]
    else:
        inc.foreign += sign * r["taxable"]


def apply(inc, rows: List[Dict]) -> None:
    """The foreign income into the engine's input; then the credit, source by source, on the finished input."""
    for r in rows:
        _add(inc, r)


def credits(inc, rows: List[Dict]) -> float:
    base = calculate(inc).income_tax_due
    total = 0.0
    for r in rows:
        if not r["creditable"]:
            continue
        without = copy.copy(inc)
        _add(without, r, -1.0)
        uk_on_it = max(0.0, round(base - calculate(without).income_tax_due, 2))
        r["uk_tax"] = uk_on_it
        r["credit"] = round(min(r["creditable"], uk_on_it), 2)
        if r["foreign_tax"] > r["credit"]:
            r["notes"].append(f"{r['payer'] or r['kind_label']} ({r['country_name']}): £{r['foreign_tax'] - r['credit']:,.2f} of the "
                              f"foreign tax is not relieved in the UK (more than the UK tax on it, or above the treaty rate).")
        total += r["credit"]
    inc.foreign_tax_credit = round(min(total, base), 2)
    return inc.foreign_tax_credit


def boxes(rows: List[Dict], property_credit: float = 0.0) -> List[Dict]:
    """SA106 pages F2 and F3: a row per source (columns A, B, C, E, F) and the column F totals; box 2 the credit (with
    the credit on overseas property income)."""
    if not rows and not property_credit:
        return []
    out = []
    for kind in ("INTEREST", "DIVIDEND", "PENSION"):
        mine = [r for r in rows if (r["kind"] == kind if kind != "PENSION" else r["kind"] in ("PENSION", "BENEFIT", "OTHER"))]
        if not mine:
            continue
        for r in mine:
            out.append({"box": "A-F", "label": f"{SECTION[r['kind']]}: {r['country']} {r['payer']}".strip(),
                        "value": r["taxable"], "note": f"B £{r['gross']:,.2f}, C £{r['foreign_tax']:,.2f}"
                                                         f"{', E X' if r['claim'] and r['credit'] else ''}"
                                                         f"{', exemption 10%' if r['exempt'] else ''}", "doc_id": r["doc_id"]})
        out.append({"box": F_BOX[mine[0]["kind"]], "label": f"{SECTION[mine[0]['kind']]}: total of column F",
                    "value": round(sum(r["taxable"] for r in mine), 2), "note": "", "doc_id": None})
    credit = round(sum(r["credit"] for r in rows) + property_credit, 2)
    if credit:
        out.insert(0, {"box": "2", "label": "Total Foreign Tax Credit Relief on income", "value": credit,
                       "note": "Only if you work out the tax (HS263)", "doc_id": None})
    return [{"form": "SA106", "title": "Foreign", "rows": out}]


def load(db, job) -> List[Dict]:
    from backend.app.sa.models import SAForeign
    return [one(f, job.tax_year) for f in db.query(SAForeign).filter(SAForeign.job_id == job.id).order_by(SAForeign.id).all()]
