"""Receipts and invoices on a sole trader's trade (made-up figures, an in-memory database): each money once, a receipt
paid from the bank being that payment's evidence; personal spending out, capital items left for the allowances,
entertaining disallowed (s45); VAT out only for a VAT-registered business (BIM31535)."""

import json
import sys
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

if "backend.app.core.database" not in sys.modules:
    _db = types.ModuleType("backend.app.core.database")
    _db.Base, _db.engine, _db.create_table = declarative_base(), create_engine("sqlite://"), lambda table: None
    _db.SessionLocal, _db.get_db = sessionmaker(bind=_db.engine), lambda: None
    sys.modules["backend.app.core.database"] = _db

from backend.app.core.database import Base                                            # noqa: E402
from backend.app.sa.models import SABusiness, SABusinessItem, SADocument, SAJob       # noqa: E402
from backend.app.sa import income                                                     # noqa: E402
from backend.app.sa.extract import invoice                                            # noqa: E402


def session():
    from sqlalchemy import Column, Integer, Table
    if "users" not in Base.metadata.tables:
        Table("users", Base.metadata, Column("id", Integer, primary_key=True))
    engine = create_engine("sqlite://")
    tables = [t for name, t in Base.metadata.tables.items() if name.startswith("sa_") or name == "users"]
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine)()
    db.add(SAJob(id="j", owner_user_id=1, person_name="Pat Trader", tax_year="2024-25"))
    db.commit()
    return db


def bill(issuer, on, total, heading="OTHER", kind="PURCHASE", vat=0.0, customer=None):
    return {"kind": kind, "issuer": issuer, "customer": customer, "date": on, "number": None, "total": total, "vat": vat,
            "paid_by": None, "what": "goods", "heading": heading}


def receipt(n, *bills, status="READ"):
    return SADocument(job_id="j", filename=f"r{n}.jpg", sha256=str(n), kind="INVOICE", status=status,
                      fields=json.dumps({"bills": list(bills)}))


def items(db):
    return sorted((i.heading, float(i.amount), float(i.disallowed)) for i in db.query(SABusinessItem))


def no_bank(monkeypatch, lines=(), takings=0.0):
    from backend.app.sa import books
    monkeypatch.setattr(books, "view", lambda db, job, biz: {"lines": list(lines),
                                                             "totals": [{"heading": "TURNOVER", "amount": takings}]})


def test_reader_clean_and_checks():
    f = invoice.clean({"bills": [{"kind": "purchase", "issuer": "Shop A", "date": "2024-06-01", "total": "1,200.00",
                                  "vat": "200", "heading": "fuel?"}, {"total": 0}]})
    assert f["bills"] == [{"kind": "PURCHASE", "issuer": "Shop A", "customer": None, "date": "2024-06-01", "number": None,
                           "total": 1200.0, "vat": 200.0, "paid_by": None, "what": "", "heading": "OTHER",
                           "self_billed": False}]
    assert invoice.checks(f, "2024-25") == ("READ", [])
    assert invoice.checks({"bills": []}, "2024-25")[0] == "FILED"
    assert invoice.checks(invoice.clean({"bills": [bill("Shop A", "2021-06-01", 5.0)]}), "2024-25")[0] == "OTHER_YEAR"
    status, notes = invoice.checks(f, "2024-25", second={"bills": [{"total": 120.0}]})
    assert status == "CHECK" and "disagree" in notes[0]


def test_receipts_with_no_bank_are_the_costs(monkeypatch):
    db = session()
    no_bank(monkeypatch)
    db.add_all([receipt(1, bill("Fuel Co", "2024-05-01", 60.0, "TRAVEL")),
                receipt(2, bill("fuel co", "2024-05-01", 60.0, "TRAVEL")),                     # sent again
                receipt(3, bill("Grocer", "2024-05-02", 80.0, "PERSONAL"),                     # two on one page
                        bill("Cafe", "2024-05-02", 30.0, "ENTERTAINING")),
                receipt(4, bill("Van Dealer", "2024-06-01", 9000.0, "CAPITAL")),
                receipt(5, bill("Shop B", "2023-01-01", 40.0)),                                # before the year
                receipt(6, bill("Shop C", "2024-07-01", 99.0), status="CHECK"),                # readers disagree
                receipt(7, bill("Pat Trader", "2024-08-01", 500.0, kind="SALE", customer="Customer A"))])
    db.commit()
    income.sync_receipt_items(db, db.query(SAJob).first())
    assert items(db) == [("ADVERTISING", 30.0, 30.0), ("TRAVEL", 60.0, 0.0), ("TURNOVER", 500.0, 0.0)]
    biz = db.query(SABusiness).one()
    assert "receipts" in biz.note and "capital item" in biz.note
    income.sync_receipt_items(db, db.query(SAJob).first())                                     # again: nothing added
    assert len(items(db)) == 3


def test_a_receipt_paid_from_the_bank_is_that_payments_evidence(monkeypatch):
    db = session()
    db.add(SABusiness(job_id="j", name="Shop"))
    no_bank(monkeypatch, lines=[{"on": "2024-05-04", "in": 0.0, "out": 60.0}, {"on": "2024-08-02", "in": 500.0, "out": 0.0}],
            takings=500.0)
    db.add_all([receipt(1, bill("Fuel Co", "2024-05-01", 60.0, "TRAVEL")),                      # in the bank 3 days on
                receipt(2, bill("Fuel Co", "2024-05-20", 60.0, "TRAVEL")),                      # cash: a cost
                receipt(3, bill("Pat Trader", "2024-08-01", 500.0, kind="SALE"))])              # bank takings: evidence
    db.commit()
    income.sync_receipt_items(db, db.query(SAJob).first())
    assert items(db) == [("TRAVEL", 60.0, 0.0)]


def test_vat_registered_costs_are_net(monkeypatch):
    db = session()
    no_bank(monkeypatch)
    db.add_all([receipt(1, bill("Tools Ltd", "2024-05-01", 120.0, "OTHER", vat=20.0)),
                SADocument(job_id="j", filename="vat.pdf", sha256="v", kind="VAT_RETURN", status="READ")])
    db.commit()
    income.sync_receipt_items(db, db.query(SAJob).first())
    assert items(db) == [("OTHER", 100.0, 0.0)]


def test_a_self_billing_pay_statement_is_a_sale_and_money_in_is_never_a_cost(monkeypatch):
    f = invoice.clean({"bills": [{"kind": "PURCHASE", "issuer": "Courier Co Ltd", "customer": "Pat Trader",
                                  "date": "2024-04-16", "total": 590.0, "self_billed": True}]})
    invoice.checks(f, "2024-25", "Pat Trader")
    assert f["bills"][0]["kind"] == "SALE" and f["bills"][0]["heading"] == "TURNOVER"
    db = session()
    db.add(SABusiness(job_id="j", name="Driving"))
    no_bank(monkeypatch, lines=[{"on": "2024-04-19", "in": 590.0, "out": 0.0}], takings=590.0)
    db.add(receipt(1, bill("Courier Co Ltd", "2024-04-16", 590.0, customer="Pat Trader")))   # misread as a purchase
    db.commit()
    income.sync_receipt_items(db, db.query(SAJob).first())
    assert items(db) == []


def test_a_bill_the_person_issued_is_a_sale():
    f = invoice.clean({"bills": [{"kind": "PURCHASE", "issuer": "Pat Trader", "customer": "Customer A",
                                  "date": "2024-06-23", "total": 2178.05, "heading": "OTHER"}]})
    invoice.checks(f, "2024-25", "Pat Trader")
    assert f["bills"][0]["kind"] == "SALE" and f["bills"][0]["heading"] == "TURNOVER"
