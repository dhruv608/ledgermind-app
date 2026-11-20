"""A bank account's statement lines against its ledger lines: Matched, Unmatched and Unrecorded.

Reading: a statement uploaded on the bank area's Evidence uses the Self Assessment readers
(sa/documents._read_statement): a bank's CSV export by code, a PDF page by page (text, else the AI reads the image),
with each page's balances chained to check the reading. A spreadsheet is turned into a CSV first. The lines are stored
against the account's firm code (bank_statement_lines), so a file is read once.

Matching: a statement line and a ledger line match when the money is the same (in = debit, out = credit) and the dates
are within MATCH_DAYS; each line is used once, the nearest date first. Only the dates the statement covers are compared,
so a statement for part of the year does not make the rest of the ledger 'unmatched'.
  Matched     the pairs
  Unmatched   ledger lines in the statement's dates with no statement line (recorded, not on the bank)
  Unrecorded  statement lines with no ledger line (on the bank, not in the books): each needs a journal
"""

import io
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models.area_evidence import AreaEvidence
from backend.app.models.bank_statement import BankStatementLine
from backend.app.models.database import ClientEngagement, TBRecord

MATCH_DAYS = 5
TOLERANCE = 0.01


def _as_csv(name: str, data: bytes) -> bytes:
    """A spreadsheet's first sheet as CSV, for the CSV reader."""
    import pandas as pd
    frame = pd.read_excel(io.BytesIO(data), sheet_name=0, header=None, dtype=str)
    return frame.fillna("").to_csv(index=False, header=False).encode("utf-8")


def _day(text: Optional[str]) -> Optional[date]:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date() if text else None
    except ValueError:
        return None


def read_statement(engagement: ClientEngagement, db: Session, evidence_id: int, code: int) -> Dict[str, Any]:
    """Read an uploaded statement into its lines, kept against the bank code (a new read replaces the old one)."""
    from backend.app.sa.documents import _read_statement
    from backend.app.sa.intake import intake
    from backend.app.core.s3 import s3_service

    ev = db.get(AreaEvidence, evidence_id)
    if ev is None or ev.engagement_id != str(engagement.id):
        raise ValueError("That file is not on this client")
    data = s3_service.download_file_bytes(ev.stored)
    name = ev.filename
    if name.lower().endswith((".xlsx", ".xls")):
        data, name = _as_csv(name, data), name.rsplit(".", 1)[0] + ".csv"
    if not name.lower().endswith((".csv", ".pdf")):
        raise ValueError("Read a statement as a PDF, a CSV or a spreadsheet")
    items = intake([(name, data)])
    if not items:
        raise ValueError("The file could not be opened")
    fields, status, notes, read_by = _read_statement(items[0])
    lines = [l for p in fields.get("pages", []) for l in p["lines"]]
    db.execute(delete(BankStatementLine).where(BankStatementLine.engagement_id == str(engagement.id),
                                               BankStatementLine.code == code, BankStatementLine.evidence_id == evidence_id))
    for on, desc, money_in, money_out, balance in lines:
        db.add(BankStatementLine(engagement_id=str(engagement.id), code=code, evidence_id=evidence_id, line_date=_day(on),
                                 description=(desc or "")[:500], money_in=float(money_in or 0), money_out=float(money_out or 0),
                                 balance=None if balance is None else float(balance)))
    db.commit()
    return {"lines": len(lines), "notes": notes, "read_by": read_by, "status": status}


def _ledger_lines(engagement: ClientEngagement, db: Session, code: int) -> List[Dict[str, Any]]:
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.sop.common import code_matcher, ledger_rows
    tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    code_of = code_matcher(ChartLookup.gl_account_codes(tb))
    return [{"id": f"gl:{tx.id}", "date": tx.transaction_date, "description": tx.description or "", "type": tx.source or "",
             "amount": round(float(tx.debit_amount or 0) - float(tx.credit_amount or 0), 2)}
            for tx in ledger_rows(str(engagement.id), db) if code_of(tx.raw_account_name) == code]


def match_lines(stmt: List[Dict[str, Any]], ledger: List[Dict[str, Any]]):
    """(matched pairs, unmatched ledger lines, unrecorded statement lines): each statement line to the nearest-dated
    ledger line of the same money within MATCH_DAYS, each line used once."""
    free = {g["id"]: g for g in ledger}
    matched, unrecorded = [], []
    for s in sorted(stmt, key=lambda x: (x["date"] or date.min)):
        best = None
        for g in free.values():
            if abs(g["amount"] - s["amount"]) > TOLERANCE:
                continue
            gap = abs((g["date"] - s["date"]).days) if g["date"] and s["date"] else MATCH_DAYS
            if gap <= MATCH_DAYS and (best is None or gap < best[0]):
                best = (gap, g)
        if best:
            matched.append({"statement": s, "ledger": best[1], "days": best[0]})
            del free[best[1]["id"]]
        else:
            unrecorded.append(s)
    return matched, sorted(free.values(), key=lambda g: (g["date"] or date.min)), unrecorded


def statement_match(engagement: ClientEngagement, db: Session, code: int) -> Dict[str, Any]:
    stmt = [{"id": f"st:{l.id}", "date": l.line_date, "description": l.description,
             "amount": round(float(l.money_in or 0) - float(l.money_out or 0), 2), "balance": l.balance}
            for l in db.execute(select(BankStatementLine).where(BankStatementLine.engagement_id == str(engagement.id),
                                                                BankStatementLine.code == code)).scalars()]
    files = sorted(set(db.execute(select(BankStatementLine.evidence_id).where(
        BankStatementLine.engagement_id == str(engagement.id), BankStatementLine.code == code)).scalars()))
    if not stmt:
        return {"read": False, "files": [], "matched": [], "unmatched": [], "unrecorded": [], "from": None, "to": None}
    dated = [s["date"] for s in stmt if s["date"]]
    start, end = (min(dated), max(dated)) if dated else (None, None)
    ledger = [g for g in _ledger_lines(engagement, db, code)
              if g["date"] is None or start is None or start <= g["date"] <= end]

    matched, unmatched, unrecorded = match_lines(stmt, ledger)
    iso = lambda x: {**x, "date": x["date"].isoformat() if x["date"] else None}
    return {
        "read": True, "files": files, "from": start.isoformat() if start else None, "to": end.isoformat() if end else None,
        "matched": [{"statement": iso(m["statement"]), "ledger": iso(m["ledger"]), "days": m["days"]} for m in matched],
        "unmatched": [iso(g) for g in unmatched],
        "unrecorded": [iso(s) for s in unrecorded],
        "statement_lines": len(stmt), "ledger_lines": len(ledger),
    }
