"""Supplier bills over 90 days are read the same way as debtors (U-CRD-090). Made-up report."""
import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from backend.app.services.ingestion.ageing_reports import AgeingReport, over_90_days, _grand_total


def test_ap_report_over_90_days():
    rows = [["Aged Payables Summary"], ["As at 31 January 2026"],
            ["Contact", "Current", "< 1 Month", "1 Month", "2 Months", "3 Months", "Older", "Total"],
            ["Acme Supplies", 100.0, 0, 0, 0, 250.0, 400.0, 750.0],
            ["Bright Print", 80.0, 0, 0, 0, 0, 0, 80.0],
            ["Total", 180.0, 0, 0, 0, 250.0, 400.0, 830.0]]
    rep = AgeingReport("AP", "AP.xlsx", rows, date(2026, 1, 31), _grand_total(rows))
    old = over_90_days(rep, date(2026, 1, 31))
    assert round(sum(old.values()), 2) == 650.0 and "Acme Supplies" in old and "Bright Print" not in old
