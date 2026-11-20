"""Next year's ledger for a job, used for post-year-end checks. Read with the general ledger reader; only lines in the
nine months after the year end are kept (s458 looks nine months on, other checks six). Each line gets the firm code its
account has in this year's books, matched by name. Stored apart from the year's own books; a new upload replaces it."""

import io
from datetime import date, timedelta
from typing import Dict, List, NamedTuple, Optional

import pandas as pd
from sqlalchemy.orm import Session

WINDOW_DAYS = 275           # nine months after the year end (s455 repaid in time, s458); others read six


class NextLine(NamedTuple):
    when: date
    code: Optional[int]
    account: str
    debit: float
    credit: float
    description: str
    source: str
    reference: str


def _number(v) -> float:
    try:
        return 0.0 if v is None or pd.isna(v) else round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


def read_lines(filename: str, content: bytes) -> pd.DataFrame:
    from backend.app.services.ingestion.ingestion_service import IngestionService
    if filename.lower().endswith(".csv"):
        raw = pd.read_csv(io.BytesIO(content), header=None, dtype=str)
    else:
        xl = pd.ExcelFile(io.BytesIO(content))
        raw = xl.parse(xl.sheet_names[0], header=None)
    return IngestionService._clean_universal_gl(raw, "OTHER")


def store_next_year(engagement_id: str, filename: str, content: bytes, db: Session) -> int:
    from backend.app.models.database import ClientEngagement, TBRecord
    from backend.app.models.post_year_end import PostYearEndLine
    from backend.app.services.mapping.chart_lookup import account_name_keys
    eng = db.get(ClientEngagement, engagement_id)
    if eng is None or eng.period_end_date is None:
        return 0
    df = read_lines(filename, content)
    if df.empty or "Date" not in df.columns:
        return 0
    end = eng.period_end_date
    codes: Dict[str, int] = {}
    for t in db.query(TBRecord).filter(TBRecord.engagement_id == engagement_id).all():
        if t.std_code is not None:
            for k in account_name_keys(t.raw_account_name or ""):
                codes.setdefault(k, int(t.std_code))
    db.query(PostYearEndLine).filter(PostYearEndLine.engagement_id == engagement_id).delete(synchronize_session=False)
    n = 0
    for _, r in df.iterrows():
        when = pd.to_datetime(r.get("Date"), errors="coerce", dayfirst=True)
        if pd.isna(when):
            continue
        when = when.date()
        if not (end < when <= end + timedelta(days=WINDOW_DAYS)):
            continue
        account = str(r.get("Parent_Account") or "").strip()
        code = next((codes[k] for k in account_name_keys(account) if k in codes), None)
        debit, credit = _number(r.get("Debit")), _number(r.get("Credit"))
        if not debit and not credit:
            continue
        db.add(PostYearEndLine(engagement_id=engagement_id, when=when, account=account[:255], code=code,
                               source=str(r.get("Source") or "")[:80], description=str(r.get("Description") or "")[:500],
                               reference=str(r.get("Reference") or "")[:120], debit=debit, credit=credit))
        n += 1
    db.commit()
    return n


def next_year_lines(engagement_id: str, db: Session) -> List[NextLine]:
    """The stored lines, oldest first (empty when none was uploaded)."""
    from backend.app.models.post_year_end import PostYearEndLine
    rows = db.query(PostYearEndLine).filter(PostYearEndLine.engagement_id == str(engagement_id)).order_by(
        PostYearEndLine.when, PostYearEndLine.id).all()
    return [NextLine(r.when, r.code, r.account or "", float(r.debit or 0), float(r.credit or 0), r.description or "",
                     r.source or "", r.reference or "") for r in rows]
