"""
The client's VAT summary as the firm keeps it: one row per return with the VAT on sales (Output), on purchases
(Input), what was due, what was paid or refunded and when, what is still outstanding and the net sales, under a
heading that names the VAT basis ('Cash', 'Accruals', 'FRS Accruals'). The layouts vary from client to client:

  Quarter | Output | Input | Due | Paid/(Refund) | Difference | Date | Sales
  Period  | Output Tax | Input Tax | Vat Due | Due | Amount Paid | Date Paid | Period | ... (a second, 'as per
          books' table to the right is ignored)
  (blank) | Outputs VAT | Inputs VAT | Payable / (Refund) | Recd / Paid (paid as a minus) | O/S | Turnover

The periods are written every way ('Q.E. 30.06.2025', 'Q.E. - Nov-2024', '01/12/2024 - 28/02/2025', 'Jun-25 QTR',
"Jan'25-March'25", 'For Apr & May-2025', 'January'); a missing year is the one that puts the return in the
accounting year. An 'Opening' / 'B/fwd' row is last year's return still unpaid when the year began.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

MONTHS = {name: i for i in range(1, 13) for name in
          (calendar.month_name[i].lower(), calendar.month_abbr[i].lower())}
MONTHS["sept"] = 9
# 'Period start | Period end | Output VAT (Box 1) | ... | Input VAT (Box 4) | ...': the dates in two columns
PERIOD_COLUMN = re.compile(r"^period\s*(start|end|from|to)\b|^(start|end)\s*date\b", re.I)
PERIOD_END = re.compile(r"^period\s*(end|to)\b|^end\s*date\b", re.I)
LABEL_HEAD = re.compile(r"^(quarter|particulars|period|qtrs?|return period|vat period)\b", re.I)
OPENING = re.compile(r"opening|b/?fwd|brought forward|prior|^filed$", re.I)
QUARTER_WORDS = re.compile(r"\bq\s*[./_-]?\s*e(?![a-z])|q/e|quarter|qtr|ending|\bend\b", re.I)
# A payments list, notes or a second table ('VAT as per GL', its own Period heading) under the returns: the end
STOP_LABEL = re.compile(r"^(date|total|sales? as per|description|note|vat as per|as per)\b|^(period|quarter|qtrs?|particulars)$",
                        re.I)
FULL_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})")
DAY_MONTH_YEAR = re.compile(r"(?<![\w'])(\d{1,2})[\s-]+([A-Za-z]{3,9})[\s'-]+(\d{2,4})")
MONTH_YEAR = re.compile(r"([A-Za-z]{3,9})\.?(?:['\s_.-]*(\d{4}|\d{2})(?!\d))?")


@dataclass
class SummaryReturn:
    label: str
    start: Optional[date]
    end: Optional[date]
    output: float = 0.0
    input: float = 0.0
    due: Optional[float] = None
    paid: Optional[float] = None
    paid_date: Optional[date] = None
    paid_date_text: str = ""
    outstanding: Optional[float] = None
    sales: Optional[float] = None
    interest: Optional[float] = None
    opening: bool = False


@dataclass
class VatSummary:
    basis: Optional[str]                     # STANDARD (accrual), CASH or FLAT_RATE; None when not said
    returns: List[SummaryReturn] = field(default_factory=list)


def _text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _num(v: Any) -> Optional[float]:
    s = _text(v).replace(",", "").replace("£", "").strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    try:
        n = float(s.strip("()"))
    except ValueError:
        return None
    return -n if negative else n


def header_row(rows: List[List[Any]]) -> Optional[int]:
    """The row with the column headings: text cells naming the output and the input VAT (not a VAT 100 return's
    'Box 1' layout, nor a control account with figures beside the words)."""
    for i, row in enumerate(rows[:20]):
        cells = [_text(c).lower() for c in row]
        words = [c for c in cells if c and _num(c) is None]
        if len(words) < 4:
            continue                                     # 'Input VAT | 0 | Output VAT | 14,574': a control account
        # A table with 'Box 1' in its headings is still a summary when it has a column per period start / end
        boxes = any("box" in c for c in cells) and not any(PERIOD_COLUMN.match(c) for c in cells)
        if any("output" in c for c in cells) and any("input" in c for c in cells) and not boxes:
            return i
    return None


def _columns(head: List[Any]) -> Dict[str, Optional[int]]:
    cells = [_text(c).lower() for c in head]
    output = next(j for j, c in enumerate(cells) if "output" in c)
    # A second table to the right ('As per Books') starts with its own Period / Quarter heading: left out
    stop = next((j for j, c in enumerate(cells) if j > output and LABEL_HEAD.match(c)), len(cells))
    cells = cells[:stop]
    find = lambda test, after=-1: next((j for j, c in enumerate(cells) if j > after and test(c)), None)
    inp = find(lambda c: "input" in c, output)
    due = find(lambda c: bool(re.search(r"\bdue\b|payable", c)) and "date" not in c, inp if inp is not None else output)
    # 'Paid', 'Paid/(Refund)', 'Paid/Claim', 'Recd / Paid' (not 'Payable/reclaimable', the amount due)
    paid = find(lambda c: bool(re.search(r"paid|recd|received|\bclaim\b", c)) and "date" not in c
                and not c.startswith("int") and not re.search(r"payable|reclaimable", c),
                inp if inp is not None else output)
    after = max(j for j in (due, paid, inp, output) if j is not None)
    outstanding = find(lambda c: bool(re.search(r"diff|\bdue\b|o/s|outstanding", c)) and "date" not in c, after)
    label = next((j for j, c in enumerate(cells) if j < output and LABEL_HEAD.match(c)), 0)
    return {"label": label, "output": output, "input": inp, "due": due, "paid": paid, "outstanding": outstanding,
            "date": find(lambda c: "date" in c), "sales": find(lambda c: bool(re.search(r"sales|turnover", c)) and "vat" not in c),
            "interest": find(lambda c: c.startswith("int")),
            "end": next((j for j, c in enumerate(cells) if j < output and PERIOD_END.match(c)), None)}


def _basis(texts: List[str]) -> Optional[str]:
    words = " ".join(texts).lower()
    cash, accrual = len(re.findall(r"\bcash\b", words)), len(re.findall(r"accrual", words))
    if re.search(r"\bflat\b|\bfrs\b", words):
        return "FLAT_RATE_CASH" if cash > accrual else "FLAT_RATE"      # 'FRS Cash': flat rate on cash turnover
    if cash or accrual:
        return "CASH" if cash > accrual else "STANDARD"
    return None


def _year(y: Optional[str]) -> Optional[int]:
    if not y:
        return None
    n = int(y)
    return n + 2000 if n < 100 else n


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _dates(label: str) -> List[date]:
    found: List[Tuple[int, date]] = []
    for m in FULL_DATE.finditer(label):
        try:
            if m.group(1):
                found.append((m.start(), date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
            else:
                found.append((m.start(), date(_year(m.group(6)), int(m.group(5)), int(m.group(4)))))
        except ValueError:
            continue
    for m in DAY_MONTH_YEAR.finditer(label):
        month = MONTHS.get(m.group(2).lower())
        if month:
            try:
                found.append((m.start(), date(_year(m.group(3)), month, int(m.group(1)))))
            except ValueError:
                continue
    return [d for _, d in sorted(found)]


def _in_year(month: int, year: Optional[int], year_end: date, last_day: bool) -> date:
    """A month with no year: the latest year that keeps it within the accounting year (or, failing that, within three
    months after it: a return straddling the year end)."""
    if year:
        return _month_end(year, month) if last_day else date(year, month, 1)
    for limit in (year_end, year_end + timedelta(days=92)):
        for y in (year_end.year + 1, year_end.year, year_end.year - 1):
            d = _month_end(y, month)
            if d <= limit and d > year_end - timedelta(days=366):
                return d if last_day else date(y, month, 1)
    return _month_end(year_end.year - 1, month) if last_day else date(year_end.year - 1, month, 1)


def period(label: str, year_end: date) -> Tuple[Optional[date], Optional[date]]:
    """(start, end) of a return from how the summary writes it; either may be None when the label does not say."""
    dates = _dates(label)
    if len(dates) >= 2:
        start, end = dates[0], dates[-1]
        return (start, end) if start <= end else (end, start)
    if len(dates) == 1:
        d = dates[0]
        if QUARTER_WORDS.search(label) or d.day != 1:
            return None, d
        return d, None                                  # '01/03/2025': the return starting then
    months = [(MONTHS[m.group(1).lower()], _year(m.group(2))) for m in MONTH_YEAR.finditer(label)
              if m.group(1).lower() in MONTHS]
    if not months:
        return None, None
    if len(months) >= 2:
        (m1, y1), (m2, y2) = months[0], months[-1]
        end = _in_year(m2, y2, year_end, True)
        start_year = y1 or (end.year if m1 <= m2 else end.year - 1)
        return date(start_year, m1, 1), end
    m, y = months[0]
    end = _in_year(m, y, year_end, True)
    if QUARTER_WORDS.search(label):
        return None, end
    return date(end.year, end.month, 1), end              # 'January', 'For Sep-2025': one month


def _paid_date(v: Any) -> Tuple[Optional[date], str]:
    text = _text(v)
    if not text:
        return None, ""
    found = _dates(text.replace(" 00:00:00", ""))
    return (found[0] if found else None), text[:100]


def read(rows: List[List[Any]], year_end: date) -> Optional[VatSummary]:
    """The summary's returns, oldest first, or None when the rows are not a VAT summary."""
    h = header_row(rows)
    if h is None:
        return None
    cols = _columns(rows[h])
    cell = lambda r, k: r[cols[k]] if cols.get(k) is not None and cols[k] < len(r) else None
    prior_ye = year_end.replace(year=year_end.year - 1) if (year_end.month, year_end.day) != (2, 29) \
        else date(year_end.year - 1, 2, 28)
    heading = [_text(c) for r in rows[:h] for c in r]
    returns: List[SummaryReturn] = []
    row_basis: List[str] = []
    for r in rows[h + 1:]:
        label = _text(cell(r, "label")).replace(" 00:00:00", "")
        if label and _text(cell(r, "end")):
            label = f"{label} - {_text(cell(r, 'end')).replace(' 00:00:00', '')}"     # 'Period start | Period end'
        if not label or _num(label) is not None:
            continue                                     # a total line or a blank
        if STOP_LABEL.match(label):
            break                                        # a payments list or notes under the table
        nums = {k: _num(cell(r, k)) for k in ("output", "input", "due", "paid", "outstanding", "sales", "interest")}
        row_basis += [_text(c) for c in r if re.fullmatch(r"(?i)cash|accruals?|flat rate", _text(c))]
        paid_on, paid_text = _paid_date(cell(r, "date"))
        due, paid = nums["due"], nums["paid"]
        # 'Recd / Paid' written as a minus against a positive amount due: the same payment
        if due is not None and paid is not None and paid * due < 0:
            o = nums["outstanding"]
            if (o is not None and abs(due + paid - o) < 0.05) or (o is None and abs(abs(due) - abs(paid)) < 0.05):
                paid = -paid
        if OPENING.search(label):
            # Owed at the start of the year: the amount due, else what the 'still due' column shows, else output less input
            owed = due if due else nums["outstanding"] if nums["outstanding"] else (
                (nums["output"] or 0) - (nums["input"] or 0) if nums["output"] is not None else due)
            if owed is None or abs(owed) < 0.005:
                continue
            start, end = period(re.sub(OPENING, " ", label), prior_ye)
            end = end if end and end <= prior_ye else prior_ye
            returns.append(SummaryReturn(label, start, end, nums["output"] or 0.0, nums["input"] or 0.0, owed, paid,
                                         paid_on, paid_text, nums["outstanding"], nums["sales"], nums["interest"], True))
            continue
        if nums["output"] is None and nums["input"] is None:
            continue
        start, end = period(label, year_end)
        if due is None:
            due = round((nums["output"] or 0.0) - (nums["input"] or 0.0), 2)
        returns.append(SummaryReturn(label, start, end, nums["output"] or 0.0, nums["input"] or 0.0, due, paid,
                                     paid_on, paid_text, nums["outstanding"], nums["sales"], nums["interest"]))
    # Fill what the labels left out from the neighbouring returns: a return starts the day after the one before
    # ends; without a neighbour, a quarter
    body = [x for x in returns if not x.opening]
    # The returns are listed in order: one that ends well before the one above it had its year typed wrong
    # ('Q.E 31.03.2025' after 'Q/E 31.12.2025')
    for i, x in enumerate(body[1:], 1):
        prev = body[i - 1].end
        if x.end and prev and x.end < prev - timedelta(days=60):
            later = x.end.replace(year=x.end.year + 1) if (x.end.month, x.end.day) != (2, 29) else date(x.end.year + 1, 2, 28)
            if later > prev and later <= year_end + timedelta(days=183):
                x.end = later
                x.start = x.start.replace(year=x.start.year + 1) if x.start else None
    for i, x in enumerate(body):
        if x.end is None and x.start is not None:
            nxt = next((y.start for y in body[i + 1:] if y.start), None)
            x.end = nxt - timedelta(days=1) if nxt and nxt > x.start else _add_months(x.start, 3) - timedelta(days=1)
    for i, x in enumerate(body):
        if x.start is None and x.end is not None:
            prev = body[i - 1].end if i > 0 else None
            if prev and prev < x.end and (x.end - prev).days <= 124:
                x.start = prev + timedelta(days=1)
            else:
                x.start = _add_months(x.end + timedelta(days=1), -3)
        # A year typed wrong ('Q.E. 30.09.2026' in a year to 31.03.2026): back a year
        if x.end and x.end > year_end + timedelta(days=92):
            x.end = x.end.replace(year=x.end.year - 1)
            x.start = x.start.replace(year=x.start.year - 1) if x.start else None
    returns = [x for x in returns if x.end is not None]
    returns.sort(key=lambda x: (not x.opening, x.end))
    return VatSummary(_basis(heading + row_basis), returns)
