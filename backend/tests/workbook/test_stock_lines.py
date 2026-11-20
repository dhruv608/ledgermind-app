"""Closing stock lines: saved as a list, total net of impairment against the books."""

from backend.app.api.endpoints import stock_lines as sl
from backend.app.core.database import SessionLocal


def test_save_and_total(monkeypatch):
    db = SessionLocal()
    monkeypatch.setattr(db, "get", lambda *a: object())
    out = sl.save_stock_lines("stock-test", sl.StockLinesIn(verified_by="CLIENT", lines=[
        sl.StockLineIn(code=4300, stock_type="Finished goods", description="Shop stock", amount=1000, impairment=100),
        sl.StockLineIn(description="", amount=0)]), db)
    assert len(out["lines"]) == 1 and out["total"] == 900 and out["verified_by"] == "CLIENT"
    out = sl.save_stock_lines("stock-test", sl.StockLinesIn(lines=[]), db)
    assert out["lines"] == [] and out["difference"] is None
    db.close()
