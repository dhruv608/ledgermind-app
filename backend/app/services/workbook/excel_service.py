"""The workbook builder's entry point for the rest of the app. The builder itself is in
services/workbook/: builder.py (the order of the steps) and one file per part of the workbook."""

from typing import Any, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, GeneratedWorkpaper, TBRecord
from backend.app.services.workbook.builder import build_master_workpapers


class ExcelPopulatorService:
    @staticmethod
    def generate_master_workpapers(
        engagement: ClientEngagement,
        tb_records: List[TBRecord],
        gl_df: Optional[pd.DataFrame] = None,
        journals: Optional[Any] = None,
        db: Optional[Session] = None,
        draft_note: Optional[str] = None,
    ) -> GeneratedWorkpaper:
        return build_master_workpapers(engagement, tb_records, gl_df, journals, db, draft_note)


excel_service = ExcelPopulatorService()
