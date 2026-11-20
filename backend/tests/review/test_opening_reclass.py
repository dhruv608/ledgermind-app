"""Opening balances on another code from last year's (made-up figures): a reclass journal back to last year's code is
proposed for each pair, never posted until approved."""

import os
import sys
import types
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

from backend.app.services.review import opening_balances as ob             # noqa: E402


class Chart:
    accounts = {4804: None, 4420: None, 8000: None}

    def name(self, code, default=""):
        return {4804: "Bank B", 4420: "Other debtor", 8000: "Reserves"}.get(code, default)

    def is_pl(self, code):
        return code is not None and code < 4000


def test_the_same_money_on_another_code_gets_a_proposed_reclass(monkeypatch):
    import backend.app.services.bank_only.books as books
    import backend.app.services.sop.common as common
    monkeypatch.setattr(books, "is_books_client", lambda e: False)
    monkeypatch.setattr(common, "ledger_rows", lambda eid, db: [])
    monkeypatch.setattr(ob, "last_year_journals", lambda e, db: [])
    # Last year: 3,713.23 on 4420; this year's books open it on 4804. The reserves agree
    monkeypatch.setattr(ob, "last_year_closing", lambda e, db: ("last year's TB", {4420: 3713.23, 8000: -3713.23}))
    tb = [NS(std_code=4804, net_amount=3713.23, opening_amount=3713.23, raw_account_name="Bank B"),
          NS(std_code=4420, net_amount=0.0, opening_amount=0.0, raw_account_name="Other debtor"),
          NS(std_code=8000, net_amount=-3713.23, opening_amount=-3713.23, raw_account_name="Reserves")]
    findings, journals, compared = ob.opening_points(NS(id="job-1"), tb, Chart(), None, [1])
    assert compared and any(f.procedure_ref == "U-OB-003" for f in findings)
    assert len(journals) == 1
    j = journals[0]
    assert j.status == "PROPOSED" and round(j.amount, 2) == 3713.23
    lines = {l.account_code: (l.debit, l.credit) for l in j.lines}
    assert lines == {4420: (3713.23, 0.0), 4804: (0.0, 3713.23)}      # back to last year's code


class FAChart:
    accounts = {4120: None, 4123: None, 4150: None, 4153: None, 8000: None}
    NAMES = {4120: "Plant and equipment - cost", 4123: "Plant and equipment - depreciation b/fwd",
             4150: "Computer equipment - cost", 4153: "Computer equipment - depreciation b/fwd", 8000: "Reserves"}

    def name(self, code, default=""):
        return self.NAMES.get(code, default)

    def is_pl(self, code):
        return code is not None and code < 4000


def test_fixed_asset_class_with_only_last_years_money_is_remapped(monkeypatch):
    """A remap, never a journal: computer equipment opened on 4150 / 4153 with no movement,
    last year's TB had it in plant and equipment 4120 / 4123: the accounts take last year's codes, no journal."""
    import backend.app.services.bank_only.books as books
    import backend.app.services.sop.common as common
    monkeypatch.setattr(books, "is_books_client", lambda e: False)
    monkeypatch.setattr(common, "ledger_rows", lambda eid, db: [NS(raw_account_name="Bank", net_amount=0.0)])
    monkeypatch.setattr(ob, "code_matcher", lambda codes: (lambda name: None), raising=False)
    monkeypatch.setattr(ob, "last_year_journals", lambda e, db: [])
    monkeypatch.setattr(ob, "last_year_closing",
                        lambda e, db: ("last year's TB", {4120: 500.0, 4123: -200.0, 8000: -300.0}))
    tb = [NS(std_code=4150, net_amount=500.0, raw_account_name="Computer equipment cost", match_source="RULE",
             std_name="", mapping_reason=""),
          NS(std_code=4153, net_amount=-200.0, raw_account_name="Computer equipment dep b/f", match_source="RULE",
             std_name="", mapping_reason=""),
          NS(std_code=8000, net_amount=-300.0, raw_account_name="Reserves", match_source="RULE", std_name="",
             mapping_reason="")]
    findings, journals, _ = ob.opening_points(NS(id="job-1"), tb, FAChart(), None, [1])
    assert [t.std_code for t in tb] == [4120, 4123, 8000]
    assert not journals
    assert any("moved to last year's code" in f.finding_title for f in findings)
