"""The screen's extra papers in the workbook: stock lines under D2.2, prepayments / accruals with their invoices under E3 /
G10, an added reconciliation under its area's tab with its difference; nothing when the job has none; one paper that
fails leaves a note and the rest are written."""
from datetime import date
from types import SimpleNamespace as N

import openpyxl

from backend.app.core.database import SessionLocal
import backend.app.models.database  # noqa: F401 (the engagements table the adjustments point to)
from backend.app.models.custom_papers import CustomPaper
from backend.app.models.stock_lines import StockLine
from backend.app.models.yearend_adjustments import YearEndAdjustment
from backend.app.services.workbook import screen_papers as sp

EID = "screen-papers-test"


def _wb():
    wb = openpyxl.Workbook()
    wb.active.title = "D2.2 - Stock details"
    for t in ("E3 - Prepayments", "G10 - Accruals", "G4 - Loans & HP"):
        wb.create_sheet(t)
    return wb


def _texts(ws):
    return [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]


def test_papers_written_under_their_tabs():
    db = SessionLocal()
    try:
        db.add(StockLine(engagement_id=EID, code=4300, stock_type="Finished goods", description="Boxes", amount=500,
                         impairment=50, verified_by="US"))
        db.add(YearEndAdjustment(engagement_id=EID, kind="PREPAYMENT", period="THIS_YEAR", description="Insurance",
                                 cost_code=3260, amount=300, invoice_number="INV-1", invoice_date=date(2025, 1, 10),
                                 invoice_amount=1200))
        db.add(YearEndAdjustment(engagement_id=EID, kind="ACCRUAL", period="THIS_YEAR", description="Audit fee",
                                 cost_code=3301, amount=900))
        db.add(CustomPaper(engagement_id=EID, area="loans", kind="RECONCILIATION", name="Loan to statement",
                           lines='[{"side": "DEBIT", "label": "Per books", "amount": 1000},'
                                 ' {"side": "CREDIT", "label": "Per statement", "amount": 950}]'))
        db.commit()
        wb = _wb()
        ctx = N(wb=wb, db=db, engagement=N(id=EID), report_notes=[])
        sp.stock_lines_paper(ctx)
        sp.yearend_adjustment_papers(ctx)
        sp.added_papers(ctx)
        assert "Stock lines (as on the screen)" in _texts(wb["D2.2 - Stock details"])
        assert "INV-1" in _texts(wb["E3 - Prepayments"])
        assert "Audit fee" in _texts(wb["G10 - Accruals"])
        loans = wb["G4 - Loans & HP"]
        assert any("Reconciliation added: Loan to statement" == t for t in _texts(loans))
        diff = next(r for r in loans.iter_rows() if r[0].value == "Difference: debit less credit (must be nil)")
        assert diff[2].value == 50
    finally:
        for model in (StockLine, YearEndAdjustment, CustomPaper):
            db.query(model).filter(model.engagement_id == EID).delete()
        db.commit()
        db.close()


def test_nothing_without_data_and_a_failure_is_noted(monkeypatch):
    db = SessionLocal()
    try:
        wb = _wb()
        ctx = N(wb=wb, db=db, engagement=N(id=EID + "-none"), report_notes=[])
        sp.stock_lines_paper(ctx)
        sp.yearend_adjustment_papers(ctx)
        sp.added_papers(ctx)
        assert all(not _texts(ws) for ws in wb.worksheets)

        def broken(ctx):
            raise RuntimeError("no data")
        monkeypatch.setattr(sp, "PAPERS", [broken, sp.stock_lines_paper])
        assert sp.add_screen_papers(ctx) == 1
        assert ctx.report_notes and "could not be added" in ctx.report_notes[0]
    finally:
        db.close()
