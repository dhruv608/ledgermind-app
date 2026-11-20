"""Open invoices with no VAT while the contact's other invoices carry VAT."""

from datetime import date
from types import SimpleNamespace

from backend.app.services.ingestion.ageing_reports import OutstandingItem
from backend.app.services.queries.vat_rules import open_item_vat_queries
from backend.app.services.sop.common import GLLine
from backend.app.services.tax.open_items import (contacts_with_vat, documents_by_day, find_document, ledger_documents,
                                                 missing_vat)

VAT = 5300


def _invoice(when, customer, net, vat):
    lines = [GLLine(when, 4400, "Debtors", net + vat, 0.0, f"{customer} - INV", "Receivable Invoice"),
             GLLine(when, 1000, "Sales", 0.0, net, f"{customer} - INV", "Receivable Invoice")]
    if vat:
        lines.append(GLLine(when, VAT, "VAT", 0.0, vat, f"{customer} - INV", "Receivable Invoice"))
    return lines


GL = (_invoice(date(2025, 6, 1), "Customer A Ltd", 100.0, 20.0)
      + _invoice(date(2025, 12, 20), "Customer A Ltd", 500.0, 0.0)          # open, no VAT: flagged
      + _invoice(date(2025, 12, 21), "Customer B Ltd", 300.0, 0.0)          # B never charged VAT: not flagged
      + _invoice(date(2025, 12, 22), "Customer A Ltd", 200.0, 40.0))        # open with VAT: not flagged
OPEN = [OutstandingItem("Customer A Ltd", date(2025, 12, 20), "INV-2", 500.0),
        OutstandingItem("Customer B Ltd", date(2025, 12, 21), "INV-3", 300.0),
        OutstandingItem("Customer A Ltd", date(2025, 12, 22), "INV-4", 240.0)]


def test_missing_vat_only_where_the_contact_charges_vat():
    docs = ledger_documents(GL, VAT)
    by_day, with_vat = documents_by_day(docs, "AR"), contacts_with_vat(docs, "AR")
    flagged = [i.number for i in OPEN if missing_vat(i, find_document(i, by_day), with_vat)]
    assert flagged == ["INV-2"]


def test_vt02_only_on_cash_accounting(monkeypatch):
    from backend.app.services.ingestion import ageing_reports
    report = SimpleNamespace(as_at=date(2025, 12, 31))
    monkeypatch.setattr(ageing_reports, "read_ageing_reports", lambda *a, **k: {"AR": report})
    monkeypatch.setattr(ageing_reports, "outstanding_items", lambda r: OPEN)
    eng = SimpleNamespace(id="x", period_end_date=date(2025, 12, 31))
    cash = SimpleNamespace(is_vat_registered=True, vat_scheme="CASH")
    out = open_item_vat_queries(eng, cash, [], GL)
    assert len(out) == 1 and out[0]["ref"] == "VT-02" and "INV-2" in out[0]["detail"] and "INV-3" not in out[0]["detail"]
    accruals = SimpleNamespace(is_vat_registered=True, vat_scheme="STANDARD")
    assert open_item_vat_queries(eng, accruals, [], GL) == []
