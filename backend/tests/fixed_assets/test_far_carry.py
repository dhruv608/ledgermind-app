"""Last year's asset list from last year's LM job, rolled forward; LM's own class summary at the top
of C1-1 is not read as assets; an uploaded register wins."""
import io
import os
import tempfile
from datetime import date, datetime

import openpyxl

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/carry.db"

from backend.app.core.database import Base, SessionLocal, engine
from backend.app.models.database import ClientEngagement, FixedAssetRecord, GeneratedWorkpaper
from backend.app.services.ingestion.supplementary import far_carry

Base.metadata.create_all(engine)

HEADS = ["Particulars", "Date of purchase", "Cost b/fwd", "Additions", "Disposals", "Cost c/fwd", "Depn b/fwd", "Rate",
         "SLM/RBM", "Charge for the year", "Depn on disposal", "Depn c/fwd", "NBV this year", "NBV last year"]


def _lm_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "C1-1-FA detail"
    # LM's class summary first (must not be read as assets)
    ws.cell(row=6, column=2, value="Tangible fixed assets by class")
    for c, h in enumerate(HEADS, 2):
        ws.cell(row=7, column=c, value=h.replace("Particulars", "Class"))
    for c, v in enumerate(["Computer equipment", None, 1000, 500, 0, 1500, 200, None, None, 300, 0, 500, 1000, 800], 2):
        ws.cell(row=8, column=c, value=v)
    ws.cell(row=42, column=2, value="Asset register (one row per asset)")
    for c, h in enumerate(HEADS, 2):
        ws.cell(row=43, column=c, value=h)
    ws.cell(row=45, column=2, value="Computer equipment - 25% RBM")
    rows = [["Laptop", datetime(2023, 5, 1), 1000, 0, 0, 1000, 200, "25%", "RBM", 200, 0, 400, 600, 800],
            ["Monitor", datetime(2024, 6, 1), 0, 500, 0, 500, 0, "25%", "RBM", 100, 0, 100, 400, 0],
            ["Old printer", datetime(2019, 1, 1), 300, 0, 300, 0, 300, 0.25, "RBM", 0, 300, 0, 0, 0]]
    for r, values in enumerate(rows, 46):
        for c, v in enumerate(values, 2):
            ws.cell(row=r, column=c, value=v)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_carried_from_last_years_job(monkeypatch):
    db = SessionLocal()
    last = ClientEngagement(client_name="Carry Co", period_end_date=date(2025, 3, 31), source_system="QuickBooks")
    this = ClientEngagement(client_name="Carry Co", period_end_date=date(2026, 3, 31), source_system="QuickBooks")
    db.add_all([last, this])
    db.commit()
    db.add(GeneratedWorkpaper(engagement_id=last.id, filename="WP_Carry.xlsx", storage_path="x/WP_Carry.xlsx"))
    db.commit()
    content = _lm_workbook()
    import backend.app.core.s3 as s3
    monkeypatch.setattr(s3.s3_service, "download_file_bytes", lambda path: content)
    from backend.app.services.review import last_year_common
    monkeypatch.setattr(last_year_common, "last_year_job", lambda e, d: last)

    assert far_carry.carry_assets_from_last_year(this, db) == 2           # the printer went last year
    assets = {a.description: a for a in db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == this.id)}
    assert set(assets) == {"Laptop", "Monitor"}
    assert (float(assets["Laptop"].cost_bwd), float(assets["Laptop"].depr_bwd)) == (1000.0, 400.0)
    assert (float(assets["Monitor"].cost_bwd), float(assets["Monitor"].depr_bwd)) == (500.0, 100.0)
    # A register already there (uploaded) wins: nothing carried again
    assert far_carry.carry_assets_from_last_year(this, db) == 0
    db.close()
