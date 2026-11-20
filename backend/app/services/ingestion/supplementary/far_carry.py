"""Last year's asset register carried forward from the client's previous job in LedgerMind.

When this year has no asset register uploaded and the previous year is a job with a finished workbook, that workbook's
C1-1-FA detail tab is read and rolled forward: last year's carried-forward cost and depreciation become this year's
brought forward, and assets disposed of last year are dropped. An uploaded register always takes precedence."""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, FixedAssetRecord, GeneratedWorkpaper

logger = logging.getLogger(__name__)


def carry_assets_from_last_year(engagement: ClientEngagement, db: Session) -> int:
    """How many assets were carried forward (0: nothing to do or nothing found)."""
    if db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == engagement.id).first() is not None:
        return 0
    from backend.app.services.review.last_year_common import last_year_job
    last = last_year_job(engagement, db)
    if last is None:
        return 0
    paper: Optional[GeneratedWorkpaper] = (db.query(GeneratedWorkpaper)
                                           .filter(GeneratedWorkpaper.engagement_id == last.id)
                                           .order_by(GeneratedWorkpaper.generated_at.desc()).first())
    if paper is None:
        return 0
    try:
        from backend.app.core.s3 import s3_service
        from backend.app.services.ingestion.supplementary_parser import SupplementaryParserService as P
        content = s3_service.download_file_bytes(paper.storage_path)
        rows = P._far_sheet_rows(paper.filename, content)
        # The tab opens with a summary by class (totals, not assets): read only the asset table from its
        # 'Particulars' heading
        first = next((i for i, r in enumerate(rows) if any(str(c).strip().lower() == "particulars" for c in r)), None)
        if first is None:
            return 0
        rows = [[""] * len(r) if i < first else r for i, r in enumerate(rows)]
        if not P._far_headers(rows):
            return 0
        return P._parse_far_schedule(str(engagement.id), rows, db, last_year=True)
    except Exception:
        logger.exception("Last year's asset list not carried forward")
        return 0
