"""Every payee on the subcontractor accounts, companies too, with gross, CIS deducted and net (made-up figures;
the G6.4 tab lists subcontractors that are companies)."""

import os
import sys
import types
from datetime import date
from types import SimpleNamespace as NS

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Never a real database: the models make their tables on import, so a stand-in database module first
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["DATABASE_SECRET_ARN"] = ""
if "backend.app.core.database" not in sys.modules:
    _db = types.ModuleType("backend.app.core.database")
    _db.Base, _db.engine, _db.create_table = declarative_base(), create_engine("sqlite://"), lambda table: None
    _db.SessionLocal, _db.get_db = sessionmaker(bind=_db.engine), lambda: None
    sys.modules["backend.app.core.database"] = _db

from backend.app.services.review import subcontractors as sc                # noqa: E402


class Query(list):
    def filter(self, *a):
        return self

    def first(self):
        return None

    def all(self):
        return list(self)


def line(account, payee, debit=0.0, credit=0.0):
    return NS(raw_account_name=account, description=f"{payee} - work", debit_amount=debit, credit_amount=credit,
              transaction_date=date(2025, 6, 1))


def test_companies_on_subcontractor_accounts_are_listed_with_cis():
    lines = [line("Subcontractor costs", "Alpha Build Ltd", debit=1000), line("Subcontractor costs", "Alpha Build Ltd", debit=500),
             line("Subcontractor costs", "Alpha Build Ltd", credit=100),           # a credit note
             line("CIS deducted", "Alpha Build Ltd", credit=280),                  # 20% held back, owed to HMRC
             line("CIS deducted", "HMRC", debit=280),                              # paid over: not a subcontractor
             line("CIS suffered", "Big Main Contractor Ltd", debit=50),            # the other side: not deducted
             line("Subcontractor costs", "Beta Services", debit=300)]

    class DB:
        def query(self, model):
            name = getattr(model, "__name__", "")
            return Query(lines if name == "GLTransaction" else [])

    found = sc.individuals(NS(id="e1"), [], DB())
    rows = {s["name"]: s for s in found["subcontractors"]}
    assert rows["ALPHA BUILD LTD"] == {"name": "ALPHA BUILD LTD", "gross": 1400.0, "cis": 280.0, "payments": 2,
                                      "not_labour": ""}
    assert rows["BETA SERVICES"]["gross"] == 300.0 and rows["BETA SERVICES"]["cis"] == 0.0
    assert "HMRC" not in rows and "BIG MAIN CONTRACTOR LTD" not in rows
    assert found["subcontractor_accounts"] == ["Subcontractor costs"]
