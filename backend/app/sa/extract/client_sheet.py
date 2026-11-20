"""The client's own income and expenses sheet read (the firm's 'Profit and Loss' template a sole trader fills in: date,
income or expense, detail, client or supplier, income, expense, mileage). Each row becomes an income or a cost of the
trade under its SA103 heading; a row outside the period is left out. Two kinds of row are left to the accountant
rather than allowed (R-SA103-12):

  commuting   travel between home and a regular place of work is not a cost of the trade (BIM37605, Newsom v
              Robertson): kept, disallowed pending a decision
  study       a course or a new qualification is not wholly for the trade as it is: kept, disallowed pending a decision

The sheet's mileage column is never turned into a mileage claim by itself: whether the miles are business travel or
commuting is a decision."""

import io
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

HEADER_WORDS = (re.compile(r"income\s*/\s*expen|income or expen", re.I), re.compile(r"total income", re.I),
                re.compile(r"total expen", re.I))
COMMUTE = re.compile(r"\bcommut", re.I)
STUDY = re.compile(r"\bstudy\b|\bstudies\b|\bmsc\b|\bdegree\b|\bcourse\b|\buniversity\b|\btuition\b", re.I)
HEADINGS = (
    (re.compile(r"train|rail|bus\b|taxi|uber|fuel|petrol|diesel|parking|toll|hotel|accommodation|travel|flight|mileage", re.I), "TRAVEL"),
    (re.compile(r"phone|mobile|internet|broadband|software|licen[cs]e|subscription|microsoft|google|adobe|stationery|"
                r"postage|printing|computer|laptop|cloud", re.I), "OFFICE"),
    (re.compile(r"accountan|taxassist|bookkeep|legal|solicitor", re.I), "PROFESSIONAL"),
    (re.compile(r"repair", re.I), "REPAIRS"),
    (re.compile(r"advert|marketing|website|social media", re.I), "ADVERTISING"),
    (re.compile(r"rent\b|rates\b|insurance|electric|gas\b|power", re.I), "PREMISES"),
    (re.compile(r"bank charge|card fee|stripe|paypal fee|sumup", re.I), "FINANCE"),
    (re.compile(r"materials|stock|goods for resale|supplies", re.I), "COST_OF_SALES"),
)


def looks_like(text: str) -> bool:
    """A spreadsheet with the template's header row."""
    return all(w.search(text or "") for w in HEADER_WORDS)


def _num(v: Any) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return round(float(str(v).replace(",", "").replace("£", "").strip()), 2)
    except ValueError:
        return 0.0


def _day(v: Any) -> Optional[str]:
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    iso = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if iso:
        return iso.group(0).strip()
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def heading(text: str) -> str:
    return next((h for rx, h in HEADINGS if rx.search(text or "")), "OTHER")


def read(data: bytes) -> Dict[str, Any]:
    """The rows of every sheet with the template's header: {'rows': [...]} (an .xlsx file)."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    rows: List[Dict[str, Any]] = []
    for ws in wb.worksheets:
        cols = None
        for r in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in r]
            if cols is None:
                line = " | ".join(cells)
                if all(w.search(line) for w in HEADER_WORDS):
                    find = lambda rx: next((i for i, c in enumerate(cells) if re.search(rx, c, re.I)), None)
                    # 'Date of Income / Expense' is the date column, not the type column
                    typ = next((i for i, c in enumerate(cells) if re.search(r"income\s*/\s*expen|income or expen", c, re.I)
                                and not re.search(r"date|detail", c, re.I)), None)
                    cols = {"date": find(r"date"), "type": typ,
                            "detail": find(r"detail"), "party": find(r"client|supplier"), "income": find(r"total income"),
                            "expense": find(r"total expen"), "miles": find(r"mileage|miles")}
                continue
            get = lambda k: r[cols[k]] if cols.get(k) is not None and cols[k] < len(r) else None
            detail = str(get("detail") or "").strip()
            if re.match(r"\s*(total|net profit)", " ".join(cells[:3]), re.I):
                continue
            income, expense = _num(get("income")), _num(get("expense"))
            party = str(get("party") or "").strip()
            # Words in a column with no heading (the client's own note beside the row)
            note = " ".join(c.strip() for i, c in enumerate(cells) if i not in cols.values() and c.strip())[:200]
            detail = detail or note
            if not income and not expense:
                # An income row with words but no figure ('invoice shared with a relative'): kept so it is asked about
                kind = str(get("type") or "").strip().lower()
                if kind.startswith("income") and detail:
                    rows.append({"on": _day(get("date")), "detail": detail[:200], "party": party[:120], "income": 0.0,
                                 "expense": 0.0, "miles": 0.0, "no_amount": True})
                continue
            rows.append({"on": _day(get("date")), "detail": detail[:200], "party": party[:120], "income": income,
                         "expense": expense, "miles": _num(get("miles"))})
    return {"rows": rows}


def lines(rows: List[Dict], start: str, end: str) -> Dict[str, Any]:
    """The business items from the rows in the period, and what was left out or left to decide."""
    items, outside, decisions, miles = [], 0, [], 0.0
    for r in rows:
        if r["on"] and not (start <= r["on"] <= end):
            outside += 1
            continue
        text = f"{r['detail']} {r['party']}"
        miles += r["miles"]
        if r["income"]:
            items.append({"heading": "TURNOVER", "description": text.strip()[:255], "amount": r["income"], "disallowed": 0.0})
        if r["expense"]:
            disallowed, why = 0.0, None
            if r.get("decide"):
                # Use of home and mileage are simplified expenses: the accountant works them out (R-SA103-12, -13)
                disallowed, why = r["expense"], r["decide"]
            elif COMMUTE.search(text):
                disallowed, why = r["expense"], "commuting"
            elif STUDY.search(text):
                disallowed, why = r["expense"], "study"
            items.append({"heading": heading(text), "description": text.strip()[:255], "amount": r["expense"],
                          "disallowed": disallowed})
            if why:
                decisions.append((why, text.strip(), r["expense"]))
    return {"items": items, "outside": outside, "decisions": decisions, "miles": round(miles, 1)}
