"""A trade's points (made-up figures, a stand-in database): a loss, a business that stopped, building work with no CIS
statements, cash basis entry (R-SA103-03, -09, -11, -14)."""

import sys
import types

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

if "backend.app.core.database" not in sys.modules:
    _db = types.ModuleType("backend.app.core.database")
    _db.Base, _db.engine, _db.create_table = declarative_base(), create_engine("sqlite://"), lambda table: None
    _db.SessionLocal, _db.get_db = sessionmaker(bind=_db.engine), lambda: None
    sys.modules["backend.app.core.database"] = _db

from backend.app.sa import trade_points as T                                # noqa: E402


class Biz:
    def __init__(self, **kw):
        self.id, self.name, self.description, self.period_end, self.cash_basis, self.cis_deducted = 1, "Plastering", None, None, 1, 0
        self.period_start, self.car_miles = None, None          # as the real SABusiness has them
        self.__dict__.update(kw)


class Allowance:
    kind, amount = "MAIN", 2000


class DB:
    def __init__(self, biz, allowances=(), cis=0):
        self.biz, self.allowances, self.cis = biz, list(allowances), cis

    def query(self, model):
        db = self
        name = getattr(model, "__name__", "")

        class Q:
            def filter(self, *a):
                return self

            def order_by(self, *a):
                return self

            def count(self):
                return db.cis

            def __iter__(self):
                return iter([db.biz] if name == "SABusiness" else db.allowances if name == "SAAllowance" else [])
        return Q()


def test_points_for_a_trade(monkeypatch):
    monkeypatch.setattr("backend.app.sa.books.accounts", lambda db, job: [])
    job = types.SimpleNamespace(id="j", tax_year="2025-26")
    calc = {"trade": {"businesses": [{"id": 1, "loss_year": 1200.0, "loss_cf": 1200.0}]}}
    keys = [p["key"] for p in T.points(DB(Biz(period_end="2025-12-31"), [Allowance()]), job, calc)]
    assert keys == ["loss:1", "stopped:1", "cis:1", "cashentry:1"]
    keys = [p["key"] for p in T.points(DB(Biz(name="Design work"), cis=1), job, {"trade": {"businesses": []}})]
    assert keys == []


def test_vat_threshold_and_registered_with_gross_figures(monkeypatch):
    """N8 / S24: turnover over £90,000 and no VAT registration known; N7 / S25: registered but no VAT returns."""
    from types import SimpleNamespace
    from backend.app.sa import signals
    job = SimpleNamespace(id="j", tax_year="2025-26")
    row = {"id": 1, "headings": {"TURNOVER": {"amount": 95000.0}}}
    monkeypatch.setattr(signals, "_answers", lambda db, job: {})
    keys = [p["key"] for p in T.points(DB(Biz(cash_basis=0)), job, {"trade": {"businesses": [row]}})]
    assert "vat-over:1" in keys
    small = {"id": 1, "headings": {"TURNOVER": {"amount": 40000.0}}}
    assert "vat-over:1" not in [p["key"] for p in T.points(DB(Biz(cash_basis=0)), job, {"trade": {"businesses": [small]}})]
    monkeypatch.setattr(signals, "_answers", lambda db, job: {"q:vat": SimpleNamespace(value="YES")})
    keys = [p["key"] for p in T.points(DB(Biz(cash_basis=0)), job, {"trade": {"businesses": [row]}})]
    assert "vat-over:1" not in keys


def test_regular_personal_payee_in_costs_is_a_point(monkeypatch):
    """S14: a supermarket paid every month under a cost heading is to confirm; under drawings it is not."""
    shop = [{"description": f"TESCO STORES 2041 {i:02d}", "out": 62.5, "heading": "COST_OF_SALES"} for i in range(4)]
    gym = [{"description": "PUREGYM LTD", "out": 25.0, "heading": "DRAWINGS"} for _ in range(12)]
    pts = T.personal_points(shop + gym, Biz())
    assert len(pts) == 1 and "TESCO" in pts[0]["text"] and "4 payments" in pts[0]["text"]


def test_statement_points(monkeypatch):
    """S01-S04: a statement gap, a balance that does not carry on, a lone transfer, a line for the client."""
    from types import SimpleNamespace
    from backend.app.sa import books
    acc = SimpleNamespace(first="2025-06-10", last="2026-04-05",
                          checks=["Page 3 (2025-09-01) starts at £10.00 but the page before ends at £90.00: a line missing"])
    job = SimpleNamespace(id="j", tax_year="2025-26", person_name="Pat Trader")
    lines = [{"heading": books.TRANSFER, "sure": False, "chosen": False, "on": "2025-06-01", "description": "TFR TO 1234",
              "in": 0, "out": 300.0},
             {"heading": books.ASK, "sure": False, "chosen": False, "on": "2025-07-01", "description": "CASH DEPOSIT",
              "in": 900.0, "out": 0}]
    monkeypatch.setattr(books, "accounts", lambda db, job: [("1234", "Bank", acc)])
    monkeypatch.setattr(books, "period", lambda job, biz: ("2025-04-06", "2026-04-05"))
    for name in ("choices_of", "remittances", "employers", "lets_property"):
        monkeypatch.setattr(books, name, lambda *a, **k: [])
    monkeypatch.setattr(books, "sort_lines", lambda *a, **k: lines)
    monkeypatch.setattr(books, "private_use", lambda db, job, biz: {})
    keys = [p["key"].split(":")[0] for p in T.bank_points(None, job, Biz())]
    assert keys == ["stmt-cover", "stmt-chain", "stmt-transfer", "stmt-ask"]


def test_vehicle_costs_against_the_flat_rate():
    """S17 / S18: running costs and the flat rate both claimed; or running costs in full with no miles given."""
    lines = [{"heading": "TRAVEL", "description": "SHELL PETROL 0412", "out": 80.0, "in": 0},
             {"heading": "TRAVEL", "description": "NCP CAR PARK", "out": 12.0, "in": 0}]
    both = T.vehicle_points(lines, Biz(car_miles=4000), {"mileage": 1800.0})
    assert [p["key"] for p in both] == ["vehicle-both:1"] and "£80.00" in both[0]["text"]
    assert T.vehicle_points(lines, Biz(), {"mileage": 0}) == []
    asked = T.private_use_points(lines, Biz(), {})
    assert [p["key"] for p in asked] == ["pu:1:VEHICLE"] and "£80.00" in asked[0]["text"]
    assert T.private_use_points(lines, Biz(), {"VEHICLE": 60.0}) == []
    assert T.vehicle_points(lines[1:], Biz(), {}) == []                     # parking alone goes with either method


def test_private_use_share_is_disallowed():
    from backend.app.sa.books import mixed_use
    lines = [{"heading": "OFFICE", "description": "VODAFONE LTD DD", "out": 40.0, "in": 0} for _ in range(12)]
    m = mixed_use(lines, {"PHONE": 70.0})
    assert m[0]["amount"] == 480 and m[0]["disallowed"] == 144.0
    assert mixed_use(lines, {})[0]["disallowed"] == 0.0             # no % given: nothing taken off until answered


def test_cash_business_with_no_cash_takings(monkeypatch):
    """T2 / S07: the client takes cash not banked, and no cash takings are on the business."""
    from types import SimpleNamespace
    from backend.app.sa import signals
    job = SimpleNamespace(id="j", tax_year="2025-26")
    monkeypatch.setattr(signals, "_answers", lambda db, job: {"q:cash": SimpleNamespace(value="YES")})
    keys = [p["key"] for p in T.points(DB(Biz(cash_basis=0)), job, {"trade": {"businesses": [{"id": 1}]}})]
    assert "cash:1" in keys
    monkeypatch.setattr(signals, "_answers", lambda db, job: {})
    assert "cash:1" not in [p["key"] for p in T.points(DB(Biz(cash_basis=0)), job, {"trade": {"businesses": [{"id": 1}]}})]
