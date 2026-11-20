"""Opening, movement and the TB check by firm code: last year's filed
TB is the opening (balance sheet codes; last year's profit and the reserve's movements in 8000; last year's additions
and depreciation charge in cost and depreciation brought forward), the general ledger is the movement and the client's
TB only checks them. B1-ETB (workbook/core_tabs.py) and the Data check (setup/extraction_checks.py) read the same
figures from here.

Debit positive throughout. Codes are the workbook's text codes ("4400")."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, GLTransaction, TBRecord
from backend.app.services.mapping.chart_lookup import ChartLookup, account_name_keys
from backend.app.services.workbook.context import format_std_code


@dataclass
class LedgerTie:
    kind: str = ""                                          # "movement" / "closing" TB
    votes: Dict[str, int] = field(default_factory=dict)     # balance sheet accounts: movement / closing / neither
    source: str = ""                                        # where last year's figures came from
    filed: Dict[str, float] = field(default_factory=dict)   # opening per last year's filed TB
    gl_move: Dict[str, float] = field(default_factory=dict) # the year's ledger movement
    closing: Dict[str, float] = field(default_factory=dict) # the books' closing balance (the app's TB)
    uploaded: Dict[str, float] = field(default_factory=dict)  # the TB as uploaded (the TTB tab)
    opening: Dict[str, float] = field(default_factory=dict) # the books' (software's) opening
    adjust: Dict[str, float] = field(default_factory=dict)  # opening adjustment: books' opening less filed
    not_in_gl: Dict[str, float] = field(default_factory=dict)  # the TB the ledger does not explain (B1-ETB column S)


def gl_movement(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session) -> Dict[str, float]:
    """The year's ledger movement by firm code, each ledger account taking its TB account's code (as the General
    Ledger Detail tab shows them)."""
    gl_codes = ChartLookup.gl_account_codes(tb_records)
    out: Dict[str, float] = {}
    for name, dr, cr in db.execute(select(GLTransaction.raw_account_name, GLTransaction.debit_amount,
                                          GLTransaction.credit_amount).where(GLTransaction.engagement_id == engagement.id)):
        code = next((str(gl_codes[k]) for k in account_name_keys(name or "") if k in gl_codes), "")
        if code:
            key = format_std_code(code)
            out[key] = out.get(key, 0.0) + float(dr or 0.0) - float(cr or 0.0)
    return out


def opening_code(code: int, chart: ChartLookup) -> str:
    """The code a balance in last year's TB opens on this year (B1-ETB's opening). Balance sheet codes only: last
    year's profit and the reserve's movements (dividends, prior year adjustments) are the reserve brought forward;
    last year's additions and depreciation charge are this year's cost and depreciation brought forward."""
    from backend.app.services.review.opening_balances import FIXED_ASSETS, _group, _post_code
    if code < 4000 or 8000 <= code <= 8099:
        return "8000"
    if code in FIXED_ASSETS:
        return format_std_code(_post_code(_group(code, chart), chart))
    return format_std_code(code)


def ledger_tie(engagement: ClientEngagement, tb_records: List[TBRecord], db: Session,
               gl_move: Optional[Dict[str, float]] = None) -> LedgerTie:
    """Every figure B1-ETB shows by code. gl_move: the movement by code when the caller already has the ledger lines
    (the workbook's), else read from the database."""
    from backend.app.services.review.opening_balances import last_year_closing
    tie = LedgerTie()
    tie.source, last = last_year_closing(engagement, db)
    chart = ChartLookup(db)
    for c, v in (last or {}).items():
        key = opening_code(c, chart)
        tie.filed[key] = tie.filed.get(key, 0.0) + float(v)
    tie.gl_move = gl_move if gl_move is not None else gl_movement(engagement, tb_records, db)
    for tb in tb_records:
        key = format_std_code(tb.std_code)
        tie.closing[key] = tie.closing.get(key, 0.0) + float(tb.net_amount or 0.0)
        tie.uploaded[key] = tie.uploaded.get(key, 0.0) + float(tb.debit_amount or 0.0) - abs(float(tb.credit_amount or 0.0))
    filed, closing, uploaded, moved = tie.filed, tie.closing, tie.uploaded, tie.gl_move

    # Movement TB or closing TB: balance sheet accounts vote; the TB is the year's ledger movement, or
    # the opening (last year's filed TB, else the opening the TB was given) plus that movement
    votes = {"movement": 0, "closing": 0, "neither": 0}
    for key in set(uploaded) | set(moved):
        if not key.isdigit() or not 4000 <= int(key) <= 7999:
            continue
        tb_now, mv = uploaded.get(key, 0.0), moved.get(key, 0.0)
        op = filed.get(key, closing.get(key, 0.0) - tb_now) if filed else closing.get(key, 0.0) - tb_now
        if abs(op) < 1 or abs(tb_now) < 0.005 and abs(mv) < 0.005:
            continue                    # no opening, or nothing at all: cannot tell the two apart
        if abs(tb_now - mv) < 1:
            votes["movement"] += 1
        elif abs(tb_now - (op + mv)) < 1:
            votes["closing"] += 1
        else:
            votes["neither"] += 1
    movement_tb = (votes["movement"] > votes["closing"] if votes["movement"] != votes["closing"]
                   else any(abs(closing.get(k, 0.0) - uploaded.get(k, 0.0)) >= 0.005 for k in closing))
    tie.kind, tie.votes = ("movement" if movement_tb else "closing"), votes

    # The books' opening (the software's): a movement TB's opening part, else the closing less the year's ledger
    # movement
    keys = set(closing) | set(moved)
    if movement_tb:
        opening = {k: closing.get(k, 0.0) - uploaded.get(k, 0.0) for k in keys}
        not_in_gl = {k: round(uploaded.get(k, 0.0) - moved.get(k, 0.0), 2) for k in keys}
    else:
        # P&L accounts start the year at nil: what of a P&L balance the ledger does not explain is a TB line with no
        # ledger behind it (column S), never an opening
        pl = {k for k in keys if k.isdigit() and int(k) < 4000}
        opening = {k: closing.get(k, 0.0) - moved.get(k, 0.0) for k in keys - pl}
        not_in_gl = {k: round(closing.get(k, 0.0) - moved.get(k, 0.0), 2) for k in pl}
    tie.opening = {k: round(v, 2) for k, v in opening.items() if abs(v) >= 0.005}
    tie.not_in_gl = {k: v for k, v in not_in_gl.items() if abs(v) >= 0.005}
    # Opening adjustment = software opening - filed opening, in its own column
    adjust = {k: round(tie.opening.get(k, 0.0) - filed.get(k, 0.0), 2) for k in set(tie.opening) | set(filed)}
    tie.adjust = {k: v for k, v in adjust.items() if abs(v) >= 0.005}
    return tie
