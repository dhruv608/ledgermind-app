"""The workbook written sheet by sheet, and each version of the pack made and kept."""

import io
from typing import Dict, Optional

from openpyxl import Workbook

from backend.app.sa.pack.style import DRAFT, FINAL, _money
from backend.app.sa.pack.law import rules_sheet
from backend.app.sa.pack.income_sheets import (capital_gains, foreign_sheet, paye, property_abroad_sheet,
                                               property_sheet, savings_dividends, self_employment)
from backend.app.sa.pack.review_sheets import (client_info, decisions, evidence, export, last_year, queries, summary,
                                               tax_computation)
from backend.app.sa.pack.gather import gather


SHEETS = (summary, client_info, paye, self_employment, property_sheet, property_abroad_sheet, savings_dividends, foreign_sheet, capital_gains, last_year, tax_computation,
          queries, decisions, evidence, rules_sheet, export)


def workbook(d: Dict) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for make in SHEETS:
        make(wb, d)
    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.protection.sheet = True                 # R-OUT-02: kept as made (no password: the firm can unprotect)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make(db, job, final: bool, note: Optional[str], who: Optional[str]):
    """A new version of the pack, kept as made. A FINAL pack is refused while a Block is open (R-OUT-01)."""
    from backend.app.core.s3 import s3_service
    from backend.app.sa.models import SAPack
    from backend.app.sa.queries import queries as all_queries
    counts = all_queries(db, job)["counts"]
    if final and counts["blocks"]:
        raise ValueError(f"{counts['blocks']} block{'s' if counts['blocks'] > 1 else ''} open: answer "
                         f"{'them' if counts['blocks'] > 1 else 'it'} on Queries first, or make a draft.")
    last = db.query(SAPack).filter(SAPack.job_id == job.id).order_by(SAPack.version.desc()).first()
    version = (last.version if last else 0) + 1
    kind = FINAL if final else DRAFT
    d = gather(db, job, kind, version, note, counts)
    data = workbook(d)
    key = s3_service.upload_file_bytes(data, f"sa_uploads/{job.id}/pack/v{version}.xlsx")
    row = SAPack(job_id=job.id, version=version, kind=kind, note=note, blocks=counts["blocks"],
                 balance=d["result"]["balance"], storage_key=key, size=len(data), made_by=who)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def file_name(job, row) -> str:
    safe = "".join(ch for ch in job.person_name if ch.isalnum() or ch in " -").strip().replace(" ", "_")
    return f"{safe}_{job.tax_year}_WP_v{row.version}{'_DRAFT' if row.kind == DRAFT else ''}.xlsx"


def out(row) -> Dict:
    return {"id": row.id, "version": row.version, "kind": row.kind, "note": row.note, "blocks": row.blocks,
            "balance": _money(row.balance), "size": row.size, "made_by": row.made_by,
            "created_at": row.created_at.isoformat() if row.created_at else None}
