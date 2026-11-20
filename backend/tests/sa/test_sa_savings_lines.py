"""Savings lines from interest certificates (made-up figures, an in-memory database): a page with no dates giving to the
penny an account's interest on the year's certificate is that certificate again, not a second account (R-SAV-02)."""

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

from backend.app.core.database import Base                                  # noqa: E402
from backend.app.sa.models import SADocument, SAJob, SALine                 # noqa: E402
from backend.app.sa.income import sync_savings_lines                        # noqa: E402


def session():
    from sqlalchemy import Column, Integer, Table
    if "users" not in Base.metadata.tables:          # the returns point at users: a stand-in table for the test
        Table("users", Base.metadata, Column("id", Integer, primary_key=True))
    engine = create_engine("sqlite://")
    tables = [t for name, t in Base.metadata.tables.items() if name.startswith("sa_") or name == "users"]
    Base.metadata.create_all(engine, tables=tables)
    return sessionmaker(bind=engine)()


def certificate(n, provider, interest, start=None, end=None, name="Saver"):
    return SADocument(job_id="j", filename=f"c{n}.pdf", sha256=str(n), kind="INTEREST_STATEMENT", status="READ",
                      fields=json.dumps({"provider": provider, "period_from": start, "period_to": end, "holders": [],
                                         "accounts": [{"account_last4": None, "account_name": name, "isa": False,
                                                       "joint": False, "interest_gross": interest, "tax_deducted": 0}]}))


def test_an_undated_page_repeating_the_certificate_is_not_counted_again():
    db = session()
    db.add(SAJob(id="j", owner_user_id=1, person_name="Pat Saver", tax_year="2024-25"))
    db.add_all([certificate(1, "Bank A", 264.88, "2024-04-06", "2025-04-05"),
                certificate(2, "BA", 264.88, name="Certificate of Interest"),          # the same, no dates
                certificate(3, "Bank B", 100.05, name="Other saver")])                  # another account: kept
    db.commit()
    sync_savings_lines(db, db.get(SAJob, "j"))
    amounts = sorted(float(l.amount) for l in db.query(SALine).filter(SALine.source == "SAVINGS"))
    assert amounts == [100.05, 264.88]


def test_a_bank_page_naming_the_certificates_account_is_not_counted_again():
    db = session()
    db.add(SAJob(id="j", owner_user_id=1, person_name="Pat Saver", tax_year="2024-25"))
    db.add(certificate(1, "Platform", 1066.25, "2024-04-06", "2025-04-05", name="Platform Active Savings Account"))
    page = {"lines": [["2024-04-15", "Interest paid Bank C Active Savings", 423.45, 0.0, None]]}
    other = {"lines": [["2024-05-01", "GROSS INTEREST", 12.5, 0.0, None]]}
    db.add_all([SADocument(job_id="j", filename="p14.pdf", sha256="b1", kind="BANK_STATEMENT", status="READ",
                           fields=json.dumps({"account_last4": None, "pages": [page]})),
                SADocument(job_id="j", filename="cur.pdf", sha256="b2", kind="BANK_STATEMENT", status="READ",
                           fields=json.dumps({"account_last4": "1234", "pages": [other]}))])
    db.commit()
    sync_savings_lines(db, db.get(SAJob, "j"))
    amounts = sorted(float(l.amount) for l in db.query(SALine).filter(SALine.source == "SAVINGS"))
    assert amounts == [12.5, 1066.25]


def test_the_same_dated_statement_on_two_pages_is_counted_once():
    db = session()
    db.add(SAJob(id="j", owner_user_id=1, person_name="Pat Saver", tax_year="2024-25"))
    db.add_all([certificate(1, "Society A", 536.54, "2023-07-19", "2024-07-18", name="Annual saver"),
                certificate(2, "Bank B", 536.54, "2023-07-19", "2024-07-18", name="Annual saver"),     # read again
                certificate(3, "Society A", 120.00, "2023-07-19", "2024-07-18", name="Other saver")])
    db.commit()
    sync_savings_lines(db, db.get(SAJob, "j"))
    sync_savings_lines(db, db.get(SAJob, "j"))                     # again, as opening the return does: no change
    amounts = sorted(float(l.amount) for l in db.query(SALine).filter(SALine.source == "SAVINGS"))
    assert amounts == [120.0, 536.54]


def test_a_brokers_certificate_gives_dividend_lines_once():
    from backend.app.sa.income import sync_dividend_lines
    db = session()
    db.add(SAJob(id="j", owner_user_id=1, person_name="Pat Saver", tax_year="2024-25"))
    doc = certificate(1, "Broker A", 109.35, "2024-04-06", "2025-04-05", name="UK deposit interest")
    f = json.loads(doc.fields)
    f["dividends"] = [{"company": "UK companies dividends", "amount": 607.29, "overseas": False},
                      {"company": "Overseas unit trust dividends", "amount": 641.19, "overseas": True}]
    doc.fields = json.dumps(f)
    db.add(doc)
    db.commit()
    for _ in range(2):                             # as opening the return does, again and again: no second copy
        sync_savings_lines(db, db.get(SAJob, "j"))
        sync_dividend_lines(db, db.get(SAJob, "j"))
    lines = db.query(SALine).filter(SALine.source == "DIVIDENDS").all()
    assert sorted(float(l.amount) for l in lines) == [607.29, 641.19]
    assert [l.note for l in lines if float(l.amount) == 641.19][0].startswith("Overseas")
    assert [float(l.amount) for l in db.query(SALine).filter(SALine.source == "SAVINGS")] == [109.35]
