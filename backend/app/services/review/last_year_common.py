"""Last year's figures, the shared basics: the line and comparison records, last year's job in the app, the uploaded
last year's TB as a table, the firm chart's names and picking this year's account for a line."""

import io
import re
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord

logger = logging.getLogger(__name__)
TB_PRIOR = "TB_PRIOR"           # upload role of last year's TB for a Xero / QuickBooks client
MIN_PERIOD_DAYS, MAX_PERIOD_DAYS = 28, 549      # a real earlier period end: a month to 18 months before (CA 2006 s392)


def last_year_end(df: pd.DataFrame, period_end) -> Optional[date]:
    """The date on last year's TB ('As of 31 Mar, 2026', read as the upload reads a TB's date): the end of the period
    before this one, so the period starts the day after (a short or long period after a change of year end:
    last year's TB as of 31 March, period to 30 September = six months). None when the TB carries no date, or one
    that is not a real earlier period end (the period is then taken as 12 months)."""
    from datetime import datetime
    from backend.app.services.ingestion.ingestion_service import ingestion_service
    if period_end is None or df is None:
        return None
    try:
        when = ingestion_service._extract_header_metadata(df.head(15))[1]
    except Exception:
        logger.exception("Last year's TB date not read (the period is taken as 12 months)")
        return None
    if isinstance(when, datetime):
        when = when.date()
    if when is None or not hasattr(when, "year") or not MIN_PERIOD_DAYS <= (period_end - when).days <= MAX_PERIOD_DAYS:
        return None
    return when


@dataclass
class LastYearLine:
    name: str
    code: Optional[int]
    amount: float               # net, debit positive


@dataclass
class Comparison:
    source: str = ""                                            # where last year's figures came from ("" = none)
    by_account: Dict[str, Optional[float]] = field(default_factory=dict)  # this year's account -> last year (None: not known)
    gone: List[LastYearLine] = field(default_factory=list)      # last year's balances with no account this year
    # This year's TB holds the year's movements only (last year's closing TB in the firm's codes gave the opening
    # balances): a balance this year is last year's plus the movement
    movements: bool = False


def last_year_job(engagement: ClientEngagement, db: Session) -> Optional[ClientEngagement]:
    from backend.app.services.review.setup_checks import _last_year
    return _last_year(engagement, db)


def _from_job(last: ClientEngagement, db: Session) -> List[LastYearLine]:
    return [LastYearLine(t.raw_account_name, t.std_code, float(t.net_amount or 0.0))
            for t in db.execute(select(TBRecord).where(TBRecord.engagement_id == last.id)).scalars()]


def _prior_frame(engagement: ClientEngagement) -> Optional[Tuple[str, pd.DataFrame]]:
    """Last year's TB uploaded with this year's files (Xero / QuickBooks / Sage clients), as read from the file."""
    return role_frame(engagement, TB_PRIOR)


RESERVES_BF = 8000          # profit and loss b/fwd


CODE_HEADING = re.compile(r"^\s*(code|nc|n/c|account code|nominal code|nominal)\s*$", re.I)


def _has_codes(df: pd.DataFrame) -> bool:
    """The TB has a code on its lines: a 'Code' heading with a number under it."""
    rows = df.values.tolist()
    for h, head in enumerate(rows[:25]):
        col = next((j for j, v in enumerate(head) if isinstance(v, str) and CODE_HEADING.match(v)), None)
        if col is not None:
            return any(col < len(r) and ((isinstance(r[col], (int, float)) and r[col] == r[col])
                                         or (isinstance(r[col], str) and r[col].strip().split(".")[0].isdigit()))
                       for r in rows[h + 1:])
    return False


def prior_tb_frame(files: List[Tuple[str, bytes]], db=None) -> Optional[Tuple[str, pd.DataFrame]]:
    """Last year's TB as a sheet of rows, from the files set as last year's TB. A plain TB is preferred when several
    are set; a full working paper (an ETB tab: the firm's final WP set as last year's TB) is
    read from its ETB final balances, not its first sheet (the index): codes 4000-9999 as they are, and the year's P&L
    (codes below 4000) closed into 8000 profit and loss b/fwd, as last year's profit is in this year's reserves."""
    from backend.app.services.ingestion.last_year_adjustments import etb_final
    papers, plain = {}, []
    for name, data in files:
        etb = None
        if name.lower().endswith((".xlsx", ".xlsm")):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
                try:
                    etb = etb_final(wb)
                finally:
                    wb.close()
            except Exception:
                etb = None
        if etb is not None and etb[1]:
            papers[name] = etb[1]
        else:
            plain.append((name, data))
    frames = []
    for name, data in plain:
        try:
            frames.append((name, pd.read_csv(io.BytesIO(data), header=None) if name.lower().endswith(".csv")
                           else pd.read_excel(io.BytesIO(data), header=None)))
        except Exception:
            continue
    # A plain TB with codes wins; one with names only (its Code column empty) cannot give the
    # opening by code, so the final paper's ETB is read instead when one was set too
    coded = [f for f in frames if _has_codes(f[1])]
    if coded:
        return coded[0]
    if not papers:
        return frames[0] if frames else None
    name, finals = next(iter(papers.items()))
    names = chart_names(db) if db is not None else {}
    balances = {int(k): v for k, v in finals.items() if str(k).isdigit()}
    rows = {c: v for c, v in balances.items() if c >= 4000}
    rows[RESERVES_BF] = round(rows.get(RESERVES_BF, 0.0) + sum(v for c, v in balances.items() if c < 4000), 2)
    lines = [["Code", "Account", "Debit", "Credit"]] + [
        [c, names.get(c, f"Account {c}"), round(v, 2) if v > 0 else 0.0, round(-v, 2) if v < 0 else 0.0]
        for c, v in sorted(rows.items()) if abs(v) >= 0.005]
    return f"{name} (ETB final balances)", pd.DataFrame(lines)


def role_frame(engagement: ClientEngagement, role: str) -> Optional[Tuple[str, pd.DataFrame]]:
    """The uploaded file taken as this role ('GL', TB_PRIOR...), first sheet, no headings; last year's TB by
    prior_tb_frame (a working paper set as last year's TB is read from its ETB)."""
    from backend.app.services.bank_only.books import client_files
    files, roles = client_files(engagement.id)
    if role == TB_PRIOR:
        chosen = [(n, b) for n, b in files if roles.get(n) == role]
        if chosen:
            try:
                from backend.app.core.database import SessionLocal
                db = SessionLocal()
                try:
                    return prior_tb_frame(chosen, db)
                finally:
                    db.close()
            except Exception:
                return prior_tb_frame(chosen)
    prior = next(((n, b) for n, b in files if roles.get(n) == role), None)
    if prior is not None:
        name, data = prior
        return name, (pd.read_csv(io.BytesIO(data), header=None) if name.lower().endswith(".csv")
                      else pd.read_excel(io.BytesIO(data), header=None))
    # A tab of one combined workbook ('<tab>.xlsx' in the roles)
    tabs = {k[:-5] for k, v in roles.items() if v == role and k.lower().endswith(".xlsx")}
    found = next(((n, b, s) for n, b in files if n.lower().endswith((".xlsx", ".xlsm"))
                  for s in pd.ExcelFile(io.BytesIO(b)).sheet_names if s in tabs), None)
    if found is None:
        return None
    name, data, sheet = found
    return f"{sheet} tab", pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=None)
# Share capital: it does not move in a normal year, so a TB still showing it holds closing balances. (Not the reserves:
# a TB of the year's movements shows them too, when last year's dividends are closed into retained earnings.)
SHARE_CAPITAL_NAME = re.compile(r"share capital|shares? issued|ordinary( [ab])? shares|called up", re.I)


def chart_names(db: Session) -> Dict[int, str]:
    from backend.app.models.database import MasterCOA
    return {c.std_code: c.std_name for c in db.execute(select(MasterCOA)).scalars()}
GENERIC_WORDS = {"account", "accounts", "loan", "directors", "director", "current", "other", "and", "the", "miss",
                 "mrs", "mr", "ms", "dr", "ltd", "limited", "bank", "creditors", "debtors"}


def _words_of(name: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (name or "").lower()) if len(w) > 2 and w not in GENERIC_WORDS}


def pick_account(line: LastYearLine, same: List[TBRecord], by_opening: bool = False) -> TBRecord:
    """Which of this year's accounts on the line's code takes last year's line: the one sharing a name word
    (a director's loan account per director), else the one that took the opening, else the biggest."""
    own = _words_of(line.name)
    named = [t for t in same if own & _words_of(t.raw_account_name)]
    pool = named or same
    # The same name first, then the most name words in common ('Funding Circle Loan' to 'Funding Circle loan', not to
    # 'Funding Circle Loan 3' or 'Bounce Back Loan', which share only 'loan'), then the size
    from backend.app.services.mapping.chart_lookup import account_name_keys
    keys = set(account_name_keys(line.name or ""))
    fit = lambda t: (bool(keys & set(account_name_keys(t.raw_account_name or ""))),
                     len(own & _words_of(t.raw_account_name)) - len(_words_of(t.raw_account_name) - own))
    if by_opening:
        return max(pool, key=lambda t: (fit(t), abs(float(t.opening_amount or 0)), abs(float(t.net_amount or 0))))
    return max(pool, key=lambda t: (fit(t), abs(float(t.net_amount or 0.0))))
