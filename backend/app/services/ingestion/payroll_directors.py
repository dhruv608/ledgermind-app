"""Directors' pay in the client's payroll file, kept apart from the staff wages (the accountant shows directors'
remuneration on its own line in the accounts and in the directors' remuneration note).

Payroll files show it in one of these ways:
  - a total line: 'Director Salary 9,960', "Less: Director's wages 10,600.01", 'Total Directors Pay 19,530',
    "Director's Remuneration 110,153.58 ... Director's NI 14,114.85", 'Dr Director Salary 13,830' (a journal block);
  - a block per director: 'Director- Mr J Smith', 'Jane Doe (Director)', 'Director Payroll | John Doe',
    then the director's months under Gross / ER NI / ER Pension headings;
  - a column: 'Director wages' beside 'Employee wages', or 'Directors' beside 'Admin Staff'.
A total line wins (it is the accountant's own figure); else the director column; else the director blocks.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

# 'Director Salary', "Director's wages", 'Total Directors Pay', "Less: Director's Remuneration", 'Directors'
TOTAL_LABEL = re.compile(r"^(?:less\s*:?\s*)?(?:total\s+)?directors?'?s?'?(?:\s+(?:salar(?:y|ies)|wages?|pay|"
                         r"remuneration|gross(?:\s+pay)?))?\s*:?$", re.IGNORECASE)
NI_LABEL = re.compile(r"^(?:total\s+)?directors?'?s?'?\s+(?:er'?s?\s+|employer'?s?\s+)?(?:ni|nic|nics|"
                      r"national\s+insurance)$", re.IGNORECASE)
PENSION_LABEL = re.compile(r"^(?:total\s+)?directors?'?s?'?\s+(?:er'?s?\s+|employer'?s?\s+)?(?:pensions?|nest)$",
                           re.IGNORECASE)
# 'Director - Jane Doe', 'Director- Mr J Smith', 'Director-John Doe'; 'Jane Doe (Director)'
PERSON_BEFORE = re.compile(r"^directors?\s*[-–:]\s*(?:payroll\s*[-–:]?\s*)?(.+)$", re.IGNORECASE)
PERSON_AFTER = re.compile(r"^(.+?)\s*\(\s*director\s*\)$", re.IGNORECASE)
PERSON_HEADING = re.compile(r"^directors?'?\s+(?:payroll|pay)\s*:?$", re.IGNORECASE)    # 'Director Payroll | John Doe'
SKIP_CELLS = {"dr", "cr", "less", "less:", "add", "add:"}
GROSS_HEAD = re.compile(r"\bgross\b", re.IGNORECASE)
ER_NI_HEAD = re.compile(r"^(?:er'?s?|employer'?s?)\s*(?:ni|nic|nics)\b", re.IGNORECASE)
ER_PENSION_HEAD = re.compile(r"^(?:er'?s?|employer'?s?)\s*(?:pensions?|nest)\b", re.IGNORECASE)
DIRECTOR_COLUMN = re.compile(r"^directors?'?s?'?(?:\s+(?:wages?|salar(?:y|ies)|pay|gross))?$", re.IGNORECASE)
STAFF_COLUMN = re.compile(r"\b(?:employees?|staff|admin)\b", re.IGNORECASE)
NOT_A_NAME = re.compile(r"\b(?:employees?|staff|admin|total|wages?|salar(?:y|ies)|gross|net|pay|average|bonus)\b",
                        re.IGNORECASE)
MONTH = re.compile(r"^\d{4}-\d{2}-\d{2}|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$|^[A-Za-z]{3,9}[\s'-]*\d{2,4}"
                   r"(?:\s*[-–]\s*[A-Za-z]{3,9}[\s'-]*\d{2,4})?$")


@dataclass
class DirectorsPay:
    gross: float
    employer_nic: Optional[float] = None
    pension_employer: Optional[float] = None
    people: Dict[str, float] = field(default_factory=dict)      # director -> gross, when the file names them
    how: str = ""                                                 # 'total line', 'director column', 'director blocks'
    months: Dict[date, float] = field(default_factory=dict)      # month end -> directors' gross, when the file has months


def _number(text: str) -> Optional[float]:
    t = (text or "").replace("£", "").replace(",", "").strip()
    neg = t.startswith("(") and t.endswith(")")
    try:
        n = float(t.strip("()"))
    except ValueError:
        return None
    return -n if neg else n


def _value_after(row: List[str], i: int) -> Optional[float]:
    """The first number to the right of cell i; None when text (a name, a heading) comes first."""
    for c in row[i + 1:]:
        c = c.strip()
        if not c:
            continue
        n = _number(c)
        return n if n is not None else None
    return None


def _is_month(text: str) -> bool:
    return bool(MONTH.match((text or "").strip()))


def _month_end(text: str) -> Optional[date]:
    """The month a payroll line is for, as its month end ('30/04/2024', '2024-04-30', 'Apr-24', 'April 2024'); UK day
    first for a date typed as text."""
    import pandas as pd
    t = (text or "").strip()
    t = re.sub(r"^[A-Za-z]{3,9}[\s'-]*\d{2,4}\s*[-–]\s*(?=[A-Za-z]{3,9}[\s'-]*\d{2,4}$)", "", t)  # 'Apr24-Mar25'
    short = re.fullmatch(r"([A-Za-z]{3,9})[\s'-]*(\d{2}|\d{4})", t)
    try:
        d = (pd.to_datetime(f"1 {short.group(1)} {short.group(2)}", dayfirst=True) if short
             else pd.to_datetime(t, dayfirst=bool(re.match(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", t))))
    except (ValueError, TypeError):
        return None
    if pd.isna(d):
        return None
    return (d + pd.offsets.MonthEnd(0)).date()


def _row_month(r: List[str]) -> Optional[date]:
    return next((m for m in (_month_end(c) for c in r[:3] if _is_month(c)) if m is not None), None)


def _total_lines(rows: List[List[str]]) -> Optional[DirectorsPay]:
    gross = ni = pension = None
    for row in rows:
        for i, cell in enumerate(row):
            c = cell.strip()
            if not c or c.lower() in SKIP_CELLS:
                continue
            for pattern, kind in ((TOTAL_LABEL, "gross"), (NI_LABEL, "ni"), (PENSION_LABEL, "pension")):
                if not pattern.match(c):
                    continue
                v = _value_after(row, i)
                if v is None or abs(v) < 0.005:
                    continue
                # the first figure given (the same total is often repeated further down the sheet)
                if kind == "gross" and gross is None:
                    gross = v
                elif kind == "ni" and ni is None:
                    ni = v
                elif kind == "pension" and pension is None:
                    pension = v
    if gross is None:
        return None
    return DirectorsPay(gross=round(gross, 2), employer_nic=ni, pension_employer=pension, how="total line")


def _column(rows: List[List[str]]) -> Optional[DirectorsPay]:
    """A 'Director wages' column beside the staff's: its months in the first table (the company's)."""
    for h, row in enumerate(rows):
        cells = [c.strip() for c in row]
        at = next((i for i, c in enumerate(cells) if DIRECTOR_COLUMN.match(c)), None)
        if at is None or not any(STAFF_COLUMN.search(c) for i, c in enumerate(cells) if i != at):
            continue
        total, seen, months = 0.0, False, {}
        for r in rows[h + 1:]:
            if not any(_is_month(c) for c in r[:3]):
                if seen:
                    break
                continue
            seen = True
            if at < len(r):
                v = _number(r[at]) or 0.0
                total += v
                when = _row_month(r)
                if when is not None and abs(v) >= 0.005:
                    months[when] = round(months.get(when, 0.0) + v, 2)
        if seen and abs(total) >= 0.005:
            return DirectorsPay(gross=round(total, 2), how="director column", months=months)
        return None
    return None


def _looks_like_name(text: str) -> bool:
    return (bool(re.fullmatch(r"[A-Za-z][A-Za-z.' -]{2,60}", text or "")) and 1 <= len(text.split()) <= 5
            and not NOT_A_NAME.search(text))


def _person(row: List[str]) -> Optional[str]:
    cells = [c.strip() for c in row]
    for i, c in enumerate(cells[:4]):
        if not c:
            continue
        m = PERSON_AFTER.match(c)
        if m:
            return m.group(1).strip()
        m = PERSON_BEFORE.match(c)
        if m and not TOTAL_LABEL.match(c):
            return m.group(1).strip(" -:")
        if PERSON_HEADING.match(c) or TOTAL_LABEL.match(c):
            name = next((x for x in cells[i + 1:] if x), "")
            if _looks_like_name(name):
                return name
        return None
    return None


def _heading(row: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, c in enumerate(row):
        c = c.strip()
        if "gross" not in out and GROSS_HEAD.search(c):
            out["gross"] = i
        elif "ni" not in out and ER_NI_HEAD.match(c):
            out["ni"] = i
        elif "pension" not in out and ER_PENSION_HEAD.match(c):
            out["pension"] = i
    return out


def _blocks(rows: List[List[str]]) -> Optional[DirectorsPay]:
    people: Dict[str, List[float]] = {}
    months: Dict[date, float] = {}
    for p, row in enumerate(rows):
        name = _person(row)
        if not name:
            continue
        # The headings: just below the name (or just above when the months start on the name's own row)
        inline = any(_is_month(c) for c in row[:3])
        near = range(p - 1, max(p - 4, -1), -1) if inline else range(p + 1, min(p + 3, len(rows)))
        cols, h = {}, None
        for k in near:
            cols = _heading(rows[k])
            if "gross" in cols:
                h = k
                break
        if "gross" not in cols:
            cols = {"gross": 1}                     # 'Directors Pay: | John Doe' then the months, the pay beside
        first = p if inline else (h + 1 if h is not None else p + 1)
        sums, seen = [0.0, 0.0, 0.0], False
        for r in rows[first:]:
            if not any(_is_month(c) for c in r[:3]):
                if seen:
                    break
                continue
            seen = True
            for n, key in enumerate(("gross", "ni", "pension")):
                if key in cols and cols[key] < len(r):
                    sums[n] += _number(r[cols[key]]) or 0.0
            when = _row_month(r)
            if when is not None and cols["gross"] < len(r):
                months[when] = round(months.get(when, 0.0) + (_number(r[cols["gross"]]) or 0.0), 2)
        if seen:
            got = people.setdefault(name, [0.0, 0.0, 0.0])
            for n in range(3):
                got[n] += sums[n]
    people = {k: v for k, v in people.items() if abs(v[0]) >= 0.005}
    if not people:
        return None
    total = lambda n: round(sum(v[n] for v in people.values()), 2)
    return DirectorsPay(gross=total(0), employer_nic=total(1) or None, pension_employer=total(2) or None,
                        people={k: round(v[0], 2) for k, v in people.items()}, how="director blocks",
                        months={k: v for k, v in months.items() if abs(v) >= 0.005})


def read(rows: List[List[str]]) -> Optional[DirectorsPay]:
    """Directors' pay for the year in the payroll file, or None when the file does not say."""
    rows = [["" if c is None else str(c) for c in r] for r in rows]
    blocks = _blocks(rows)
    column = _column(rows)
    found = _total_lines(rows) or column or blocks
    # The months, from the column or the blocks, when they add up to the directors' pay found
    for source in (column, blocks):
        if found is not None and source is not None and source.months and not found.months                 and abs(sum(source.months.values()) - found.gross) < 1:
            found.months = dict(source.months)
    if found is not None and blocks is not None and found is not blocks:
        found.people = blocks.people
        if found.employer_nic is None and blocks.employer_nic:
            found.employer_nic = blocks.employer_nic
        if found.pension_employer is None and blocks.pension_employer:
            found.pension_employer = blocks.pension_employer
    return found
