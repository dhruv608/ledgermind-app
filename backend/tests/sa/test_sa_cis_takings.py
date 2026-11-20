"""CIS statements as the trade's takings (made-up figures, an in-memory database, R-SA103-10): the gross on each
statement is the turnover when the bank gives the trade no takings; a statement sent twice counts once; another
person's, another year's and a trade with bank takings are left alone."""

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


def session():
    from sqlalchemy import Column, Integer, Table
    if "users" not in Base.metadata.tables:
        Table("users", Base.metadata, Column("id", Integer, primary_key=True))
    engine = create_engine("sqlite://")
    tables = [t for name, t in Base.metadata.tables.items() if name.startswith("sa_") or name == "users"]
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine)()
    db.add(SAJob(id="j", owner_user_id=1, person_name="Pat Builder", tax_year="2024-25"))
    db.commit()
    return db


def statement(n, gross, month="2024-06-05", contractor="Contractor A", status="READ", **more):
    f = {"contractor": contractor, "month_end": month, "gross": gross, "materials": 0, "rate": 20,
         "deducted": round(gross * 0.2, 2), "payable": round(gross * 0.8, 2), **more}
    return SADocument(job_id="j", filename=f"cis{n}.pdf", sha256=str(n), kind="CIS_STATEMENT", status=status,
                      fields=json.dumps(f))


def takings(db):
    return sorted(float(i.amount) for i in db.query(SABusinessItem).filter(SABusinessItem.heading == "TURNOVER"))


def test_cis_gross_is_the_takings_when_there_is_no_bank(monkeypatch):
    db = session()
    db.add_all([statement(1, 1000.0), statement(2, 1000.0, contractor="contractor a"),      # the same one sent again
                statement(3, 2500.0, month="2024-07-05"),
                statement(4, 900.0, other_person=True),                                      # someone else's
                statement(5, 700.0, month="2023-06-05")])                                    # outside the year
    db.commit()
    income.sync_cis_takings(db, db.query(SAJob).first())
    assert takings(db) == [1000.0, 2500.0]
    assert db.query(SABusiness).count() == 1 and "CIS" in db.query(SABusiness).first().note
    income.sync_cis_takings(db, db.query(SAJob).first())                                     # run again: nothing added
    assert takings(db) == [1000.0, 2500.0]


def test_a_trade_with_bank_takings_is_left_to_the_accountant(monkeypatch):
    from backend.app.sa import books
    db = session()
    db.add(SABusiness(job_id="j", name="Building"))
    db.add(statement(1, 1000.0))
    db.commit()
    monkeypatch.setattr(books, "view", lambda db, job, biz: {"totals": [{"heading": "TURNOVER", "amount": 800.0}]})
    income.sync_cis_takings(db, db.query(SAJob).first())
    assert takings(db) == []
