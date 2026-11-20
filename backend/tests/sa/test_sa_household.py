"""Household links (made-up clients, an in-memory database): named on documents, the spouse, the same let property,
the same postcode (R-IN-06)."""

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
from backend.app.sa.models import SADocument, SAFamily, SAJob, SAProperty   # noqa: E402
from backend.app.sa.household import links                                  # noqa: E402


def session():
    from sqlalchemy import Column, Integer, Table
    if "users" not in Base.metadata.tables:          # the returns point at users: a stand-in table for the test
        Table("users", Base.metadata, Column("id", Integer, primary_key=True))
    engine = create_engine("sqlite://")
    tables = [t for name, t in Base.metadata.tables.items() if name.startswith("sa_") or name == "users"]
    Base.metadata.create_all(engine, tables=tables)
    return sessionmaker(bind=engine)()


def test_links_between_two_clients():
    db = session()
    a = SAJob(id="a", owner_user_id=1, person_name="Kay Writer", tax_year="2025-26")
    b = SAJob(id="b", owner_user_id=1, person_name="Sam Singer", tax_year="2025-26")
    c = SAJob(id="c", owner_user_id=1, person_name="Lee Other", tax_year="2025-26")
    db.add_all([a, b, c])
    db.add(SADocument(job_id="a", filename="s.pdf", sha256="1", kind="BANK_STATEMENT", status="READ",
                      fields=json.dumps({"postcode": "CV21 2ER", "pages": []})))
    db.add(SADocument(job_id="b", filename="t.pdf", sha256="2", kind="BANK_STATEMENT", status="READ",
                      fields=json.dumps({"postcode": "cv212er", "pages": []})))
    db.add(SADocument(job_id="a", filename="i.pdf", sha256="3", kind="INTEREST_STATEMENT", status="READ",
                      fields=json.dumps({"holders": ["Mrs Kay Writer", "Mr L Other"]})))
    db.add(SAFamily(job_id="a", spouse_name="Sam Singer"))
    db.add(SAProperty(job_id="a", name="8, Elm Close, Townley"))
    db.add(SAProperty(job_id="c", name="8 Elm Close"))
    db.commit()
    got = {l["person"]: l["why"] for l in links(db, a)}
    assert set(got) == {"Sam Singer", "Lee Other"}
    assert any("spouse" in w for w in got["Sam Singer"]) and any("postcode" in w for w in got["Sam Singer"])
    assert any("named on this client's documents" in w for w in got["Lee Other"])
    assert any("8, Elm Close" in w for w in got["Lee Other"])
