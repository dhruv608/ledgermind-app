"""A scanned bundle cut into its parts (page kinds faked, no AI): split only with two real kinds; an odd page inside
one kind stays with it."""

import sys
import types

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# documents.py imports the app's models, which make their tables on import: a stand-in database for this test
if "backend.app.core.database" not in sys.modules:
    _db = types.ModuleType("backend.app.core.database")
    _db.Base, _db.engine, _db.create_table = declarative_base(), create_engine("sqlite://"), lambda table: None
    _db.SessionLocal, _db.get_db = sessionmaker(bind=_db.engine), lambda: None
    sys.modules["backend.app.core.database"] = _db

from backend.app.sa import documents as D                                   # noqa: E402
from backend.app.sa.intake import Item                                      # noqa: E402


def pdf(n):
    doc = fitz.open()
    for _ in range(n):
        doc.new_page()
    data = doc.tobytes()
    return Item("pack.pdf", data, "x", pages=n, image=True)


def test_a_bundle_is_cut_into_its_parts(monkeypatch):
    monkeypatch.setattr(D, "page_kinds", lambda item: ["OTHER", "BANK_STATEMENT", "OTHER", "BANK_STATEMENT",
                                                       "LETTING_STATEMENT", "INVOICE"])
    parts = D.split_mixed(pdf(6))
    assert [(p.kind_hint, p.pages) for p in parts] == [("OTHER", 1), ("BANK_STATEMENT", 3), ("LETTING_STATEMENT", 1), ("INVOICE", 1)]
    assert parts[1].name == "pack (pages 2-4).pdf" and len({p.sha256 for p in parts}) == 4


def test_one_kind_with_odd_pages_stays_whole(monkeypatch):
    monkeypatch.setattr(D, "page_kinds", lambda item: ["BANK_STATEMENT", "OTHER", "BANK_STATEMENT", "OTHER"])
    item = pdf(4)
    assert D.split_mixed(item) == [item]


def test_the_same_bundle_sent_twice_is_a_duplicate(monkeypatch):
    # The AI may cut two copies differently: the whole file decides
    calls = iter([["OTHER", "BANK_STATEMENT", "LETTING_STATEMENT"], ["BANK_STATEMENT", "BANK_STATEMENT", "LETTING_STATEMENT"]])
    monkeypatch.setattr(D, "page_kinds", lambda item: next(calls))
    seen_split = []
    monkeypatch.setattr(D, "intake", lambda files: [pdf(3), pdf(3)])
    real = D.split_mixed
    monkeypatch.setattr(D, "split_mixed", lambda it: seen_split.append(it) or real(it))
    class Q:                                  # a stand-in query: no documents yet
        def filter(self, *a): return self
        def all(self): return []
    class DB:
        def query(self, *a): return Q()
    try:
        D.add_documents(DB(), type("J", (), {"id": "j", "tax_year": "2025-26"})(), [("a", b""), ("b", b"")])
    except Exception:
        pass                                  # stops at storage: the split decision is what is tested
    assert len(seen_split) == 1
