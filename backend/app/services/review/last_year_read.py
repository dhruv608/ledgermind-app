"""Reading last year's trial balance file: amounts, dates, the year's column, codes, the firm-coded lines, and last
year's lines and balances by code."""

import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement
from backend.app.services.review.last_year_common import LastYearLine, SHARE_CAPITAL_NAME, _prior_frame, chart_names, logger



def _amount(v) -> float:
    """A TB cell as a number: blanks, '-' and text are 0; '(1,234.56)' is negative."""
    if isinstance(v, (int, float)):
        return float(v) if v == v else 0.0
    text = str(v or "").strip().replace(",", "").replace("£", "")
    neg = text.startswith("(") and text.endswith(")")
    try:
        n = float(text.strip("()"))
    except ValueError:
        return 0.0
    return -n if neg else n


def _words(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (name or "").lower()))


def firm_coded_lines(df: pd.DataFrame, chart_names: Dict[int, str]) -> Optional[List[LastYearLine]]:
    """Last year's TB in the firm's own codes (the accountant's closing TB: 'Code | Accounts Name | Dr | Cr'), read
    by code. None when it is not one: its codes must be the firm's, which is told by the names agreeing with the
    chart (a Xero TB has numeric codes too, with its own names)."""
    rows = df.values.tolist()
    year = _year_column(rows)
    if year is not None:
        h, col = year
        below = rows[h + 1:]
        # Debit and credit under one date: the next column has no heading of its own and holds amounts
        pair = (col + 1 < len(rows[h]) and _date_of(rows[h][col + 1]) is None and not str(rows[h][col + 1] or "").strip()
                and any(col + 1 < len(r) and isinstance(r[col + 1], (int, float)) and r[col + 1] == r[col + 1]
                        and r[col + 1] != 0 for r in below))
        for code, name, *_ in _columns_without_heading(below):
            lines = (_firm_lines(below, code, name, col, col + 1, None, chart_names) if pair
                     else _firm_lines(below, code, name, None, None, col, chart_names))
            if lines:
                return lines
    for h, head in enumerate(rows[:25]):
        cells = [str(v).strip().lower() if isinstance(v, str) else "" for v in head]
        code = next((j for j, c in enumerate(cells) if c in ("code", "nc", "account code", "nominal code")), None)
        name = next((j for j, c in enumerate(cells) if j != code and re.search(r"name|description|account", c)), None)
        dr = next((j for j, c in enumerate(cells) if c in ("dr", "debit", "debit £", "dr £")), None)
        cr = next((j for j, c in enumerate(cells) if c in ("cr", "credit", "credit £", "cr £")), None)
        bal = next((j for j, c in enumerate(cells) if c in ("balance", "net", "closing balance")), None)
        if code is None or name is None or (dr is None or cr is None) and bal is None:
            continue
        return _firm_lines(rows[h + 1:], code, name, dr, cr, bal, chart_names)
    # No heading row ('4400 | Trade debtors | | | 121073.02'): the columns are told from the lines themselves, in any
    # order; the first layout whose names agree with the chart is the one
    for columns in _columns_without_heading(rows):
        lines = _firm_lines(rows, *columns, chart_names, signed=True)
        if lines:
            return lines
    return None
DATE_TEXT = re.compile(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}$|^\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}$")


def _date_of(v) -> Optional[pd.Timestamp]:
    """A heading cell that is a date (a year-end column): a date value, or '31/03/2025', '31 Mar 2025'."""
    if isinstance(v, pd.Timestamp) or hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day"):
        try:
            return pd.Timestamp(v)
        except (ValueError, TypeError):
            return None
    if isinstance(v, str) and DATE_TEXT.match(v.strip()):
        try:
            return pd.Timestamp(pd.to_datetime(v.strip(), dayfirst=True))
        except (ValueError, TypeError):
            return None
    return None


def _year_column(rows: list) -> Optional[Tuple[int, int]]:
    """A TB printed with last year's comparative ('Account | Description | 31/03/2025 | | 31/03/2024 | | Variance'):
    the heading row and the column of the latest year end. Only that column is last year's closing balance; the
    other is the year before, and adding it in would roughly double every balance."""
    for h, head in enumerate(rows[:25]):
        dated = [(d, j) for j, v in enumerate(head) if (d := _date_of(v)) is not None]
        if len(dated) >= 2:
            return h, max(dated)[1]
    return None


def _code_of(v) -> Optional[int]:
    """A firm code in a cell: 4400, 4400.0 or '5400 A' (a second director's loan account); None otherwise."""
    if isinstance(v, str) and re.fullmatch(r"\d+(\s*[A-Za-z]{1,2})?", v.strip()):
        return int(re.match(r"\d+", v.strip()).group())
    if isinstance(v, (int, float)) and v == v and float(v) == int(v):
        return int(v)
    return None


def _columns_without_heading(rows: list) -> List[Tuple[int, int, Optional[int], Optional[int], Optional[int]]]:
    """Possible (code, name, debit, credit, balance) columns of a TB with no heading row, in any order: a column
    holding a code on most lines, a text column, and the other columns with amounts (two: debit and credit, left one
    first; one: a balance). An amount column of whole numbers can pass for codes too, so each code column is a try."""
    width = max((len(r) for r in rows[:200]), default=0)
    lines = [r for r in rows[:200] if any(v is not None and v == v and str(v).strip() for v in r)]
    if len(lines) < 3 or width < 3:
        return []
    share = lambda j, test: sum(1 for r in lines if j < len(r) and test(r[j])) / len(lines)
    codes = [j for j in range(width) if share(j, lambda v: _code_of(v) is not None and 0 <= _code_of(v) <= 9999) >= 0.7]
    names = [j for j in range(width) if share(j, lambda v: isinstance(v, str) and v.strip() and _code_of(v) is None) >= 0.7]
    out = []
    for code in codes:
        for name in names:
            amounts = [j for j in range(width) if j not in (code, name)
                       and share(j, lambda v: isinstance(v, (int, float)) and v == v and v != 0) > 0]
            if len(amounts) >= 2:
                out.append((code, name, amounts[0], amounts[1], None))
            elif len(amounts) == 1:
                out.append((code, name, None, None, amounts[0]))
    return out


def _firm_lines(rows: list, code: int, name: int, dr: Optional[int], cr: Optional[int], bal: Optional[int],
                chart_names: Dict[int, str], signed: bool = False) -> Optional[List[LastYearLine]]:
    """signed: with no heading row, which of two amount columns is the credit is not known; when the file already
    shows credits as minus figures, each amount is taken with its own sign."""
    if signed and dr is not None and cr is not None:
        signed = any(_amount(r[j]) < 0 for r in rows for j in (dr, cr) if j < len(r))
    lines, agree, named = [], 0, 0
    heading = None              # a code whose line has no amount: its balance is on the named lines under it
    for r in rows:
        c = _code_of(r[code]) if code < len(r) else None
        label = str(r[name]).strip() if name < len(r) and isinstance(r[name], str) else ""
        cell = lambda j: r[j] if j is not None and j < len(r) else None
        if dr is not None and cr is not None:
            amount = _amount(cell(dr)) + _amount(cell(cr)) if signed else _amount(cell(dr)) - abs(_amount(cell(cr)))
        else:
            amount = _amount(cell(bal))
        if c is None:
            # '5400 Directors loan account' with no amount, then 'Mr A Director | -29.04' and 'Unallocated |
            # -1,700.51' with no code: each is a line of 5400
            if heading is not None and label and abs(amount) >= 0.005 and not re.match(r"^(grand\s+)?totals?\b", label, re.I):
                lines.append(LastYearLine(label, heading, round(amount, 2)))
            continue
        blank = all(cell(j) is None or cell(j) != cell(j) or str(cell(j)).strip() == "" for j in (dr, cr, bal) if j is not None)
        heading = c if blank else None
        # A bank account carries the bank's name, never the chart's ('4804 Shopify', '4805 Revolut GBP'): not a test of
        # whose codes these are (a TB with many bank lines would otherwise fail the test)
        if label and not 4800 <= c <= 4830:
            named += 1
            firm, own = _words(chart_names.get(c, "")), _words(label)
            agree += bool(firm and own and (firm == own or firm.startswith(own) or own.startswith(firm)))
        lines.append(LastYearLine(label or chart_names.get(c, ""), c, round(amount, 2)))
    if len(lines) >= 3 and named and agree / named >= 0.6:
        return lines
    # The preparer's own wording ('CT', 'Creditors', 'Other debtor') with the firm's codes: nearly every code in the
    # chart and the lines adding up to nil is the firm's TB too (a Xero TB's own numbers are mostly not firm codes)
    coded = [l for l in lines if l.code is not None]
    if (len(coded) >= 3 and chart_names and sum(l.code in chart_names for l in coded) >= 0.9 * len(coded)
            and abs(sum(l.amount for l in lines)) <= 1.0):
        return lines
    return None


def prior_uploaded(engagement: ClientEngagement) -> bool:
    """Last year's TB was uploaded (whether or not it could be used)."""
    try:
        return _prior_frame(engagement) is not None
    except Exception:
        logger.exception("Last year's TB could not be read")
        return True


def prior_shows_share_capital(engagement: ClientEngagement) -> bool:
    """Last year's TB was uploaded and shows share capital (by name, or code 7000-7999 in the firm's codes)."""
    try:
        frame = _prior_frame(engagement)
    except Exception:
        logger.exception("Last year's TB could not be read")
        return False
    if frame is None:
        return False
    rows = frame[1].values.tolist()
    if any(isinstance(v, str) and SHARE_CAPITAL_NAME.search(v) for r in rows for v in r):
        return True
    return any(r and _code_of(r[0]) is not None and 7000 <= _code_of(r[0]) <= 7999 for r in rows)


def prior_lines(engagement: ClientEngagement, db: Session) -> List[LastYearLine]:
    """Last year's TB lines when it was uploaded in the firm's codes; empty otherwise."""
    from backend.app.services.bank_only.books import is_books_client
    if is_books_client(engagement):
        return []
    try:
        frame = _prior_frame(engagement)
        names = chart_names(db)
        lines = (firm_coded_lines(frame[1], names) if frame else None) or []
        return [in_chart(line, names) for line in lines]
    except Exception:
        logger.exception("Last year's TB could not be read")
        return []


def codes_not_in_chart(engagement: ClientEngagement, db: Session) -> List[Tuple[str, int, int, float]]:
    """Last year's TB lines on a code the firm chart does not have, opened on its parent code (in_chart):
    (name, last year's code, the code used, amount). The parent is a first choice, not a certainty (a 5501 loan
    may belong on 5351 rather than 5500), so it is shown to confirm."""
    from backend.app.services.bank_only.books import is_books_client
    if is_books_client(engagement):
        return []
    try:
        frame = _prior_frame(engagement)
        names = chart_names(db)
        lines = (firm_coded_lines(frame[1], names) if frame else None) or []
    except Exception:
        return []
    return [(line.name, line.code, line.code // 10 * 10, line.amount) for line in lines
            if names and line.code is not None and line.code not in names and line.code // 10 * 10 in names
            and abs(line.amount or 0) >= 0.005]


def in_chart(line: LastYearLine, names: Dict[int, str]) -> LastYearLine:
    """A code the firm chart does not have (e.g. 5501, a sub-code of 5500 bank loans) takes its parent code in the same
    ten, keeping its own name, so its balance opens this year instead of being lost (every code in last year's TB keeps
    a line)."""
    if not names or line.code is None or line.code in names:
        return line
    parent = line.code // 10 * 10
    return LastYearLine(line.name, parent, line.amount) if parent in names else line


def prior_balances_by_code(engagement: ClientEngagement, db: Session) -> Dict[int, float]:
    """Last year's closing balances by firm code, when last year's TB was uploaded in the firm's codes: this year's
    opening balances (b/fwd) for a client whose ledger has no opening lines. Empty otherwise."""
    out: Dict[int, float] = {}
    for line in prior_lines(engagement, db):
        out[line.code] = round(out.get(line.code, 0.0) + line.amount, 2)
    return out or _names_by_this_years_codes(engagement, db)


def _names_by_this_years_codes(engagement: ClientEngagement, db: Session) -> Dict[int, float]:
    """Last year's TB with names only (an empty Code column): each line takes the code of this
    year's account of the same name (the upload adds last year's accounts to this year's TB by name, so each has one),
    so last year's filed balances fill the ETB's opening columns. Only when every line finds its account
    and the lines still add up to nil; otherwise nothing (no part-opening)."""
    from sqlalchemy import select
    from backend.app.models.database import TBRecord
    if db is None:
        return {}
    try:
        _src, lines = _from_files(engagement, db)
    except Exception:
        logger.exception("Last year's TB could not be read")
        return {}
    records = db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars().all()
    return code_names_only(lines, records)


def code_names_only(lines, records) -> Dict[int, float]:
    """{code: balance} for last year's name-only lines coded by this year's accounts of the same name; {} unless
    every line is found and they add up to nil."""
    from backend.app.services.mapping.chart_lookup import account_name_keys
    lines = [l for l in lines if l.code is None and abs(l.amount) >= 0.005]
    if not lines or abs(sum(l.amount for l in lines)) >= 1.0:
        return {}
    code_of: Dict[str, int] = {}
    for t in records:
        if t.std_code is not None and t.raw_account_name:
            for key in account_name_keys(t.raw_account_name):
                code_of.setdefault(key, t.std_code)
    out: Dict[int, float] = {}
    for line in lines:
        code = next((code_of[k] for k in account_name_keys(line.name or "") if k in code_of), None)
        if code is None:
            return {}
        out[code] = round(out.get(code, 0.0) + line.amount, 2)
    return out


def _from_files(engagement: ClientEngagement, db: Optional[Session] = None) -> Tuple[str, List[LastYearLine]]:
    from backend.app.services.bank_only.books import client_files, is_books_client
    files, roles = client_files(engagement.id)
    if is_books_client(engagement):
        from backend.app.services.bank_only.books import opening_coder
        from backend.app.services.bank_only.input_files import read_input_files
        raw = read_input_files(files, roles, code_names=opening_coder(engagement, db) if db is not None else None,
                               year_end=engagement.period_end_date)
        # Movements (P&L, additions, depreciation charge) against last year's movements; brought-forward accounts
        # against what last year carried into them (the closed TB)
        from backend.app.services.bank_only.input_files import brought_forward_code
        given = {c: a for c, a in raw.last_year_tb.items() if brought_forward_code(c) != c}
        lines = [LastYearLine(raw.opening_names.get(c, ""), c, a) for c, a in {**raw.opening_tb, **given}.items()]
        return ("last year's TB in the uploaded files", lines) if lines else ("", [])
    from backend.app.services.ingestion.ingestion_service import IngestionService
    frame = _prior_frame(engagement)
    if frame is None:
        return "", []
    name, df = frame
    # In the firm's codes (the accountant's own closing TB): matched to this year's accounts by code
    coded = firm_coded_lines(df, chart_names(db)) if db is not None else None
    if coded:
        return f"last year's TB ({name})", coded
    tb = IngestionService._clean_xero_tb(df)
    lines = [LastYearLine(r["raw_account_name"], None, float(r["net"] or 0.0)) for _, r in tb.iterrows()]
    return (f"last year's TB ({name})", lines) if lines else ("", [])
