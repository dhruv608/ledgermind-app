"""A client TB that gives the firm code beside its own ('Taxcalc Code' / 'Final code'): read, and
used before any guess, so banks, wages and reserves are never coded by guesswork."""
import pandas as pd

from backend.app.services.ingestion import column_layouts
from backend.app.services.ingestion.ledger_files.cleaning import LedgerCleaning
from backend.app.services.ingestion.ledger_files.common import firm_code_of

HEAD = ["Account", None, "Account Code", "Account Type", "Debit", "Credit", "Balance", "Taxcalc Code"]
ROWS = [["Natwest Current Account 9017", None, 1200, "Bank", 6314402.70, 6293417.90, 20984.80, 4802],
        ["Natwest Business Credit Card", None, 1210, "Bank", 234558.38, 216499.21, 18059.17, 5354],
        ["Payroll - Admin Wages", None, 7003, "Overhead", 302682.22, 2238.56, 300443.66, 3000],
        ["DLA - R Scales", None, 2152, "Current Asset", 715.00, 2364.66, -1649.66, "5400 B"]]


def test_firm_code_values():
    assert [firm_code_of(v) for v in (4802, "4802", 4802.0, "5400 A", None, float("nan"), "n/a", 0)] == \
        [4802, 4802, 4802, 5400, None, None, None, 0]


def test_xero_style_tb_reads_the_firm_code_column():
    df = LedgerCleaning._clean_xero_tb(pd.DataFrame([["Client: X"] + [None] * 7, HEAD] + ROWS))
    assert list(df["raw_account_name"])[:2] == ["1200 - Natwest Current Account 9017", "1210 - Natwest Business Credit Card"]
    assert list(df["firm_code"]) == [4802, 5354, 3000, 5400]


def test_column_layout_reader_takes_taxcalc_code_as_the_firm_code_not_the_account_code():
    rows = [HEAD] + ROWS
    header, mapping = column_layouts.guess("TB", rows)
    assert mapping["code"] == 2 and mapping["firm_code"] == 7
    df = column_layouts.read_tb(pd.DataFrame(rows), header, mapping)
    assert list(df["firm_code"]) == [4802, 5354, 3000, 5400]


def test_mapper_uses_the_clients_firm_code_first(monkeypatch):
    from types import SimpleNamespace as N
    from backend.app.services.mapping.mapping_service import MappingService
    chart = {c: N(std_code=c, std_name=n, financial_class=fc, category=cat) for c, n, fc, cat in (
        (4800, "Bank current account", "Balance Sheet", "Bank"), (4802, "Bank current account (3)", "Balance Sheet", "Bank"),
        (5354, "Other creditors (4)", "Balance Sheet", "Creditors"), (3000, "Wages and salaries", "Profit and Loss", "Staff"),
        (5330, "Net wages", "Balance Sheet", "Creditors"), (3010, "Directors' salaries", "Profit and Loss", "Staff"))}
    rows = [{"name": "1210 - Natwest Business Credit Card", "account_type": "Bank", "net": 18059.17, "firm_code": 5354},
            {"name": "7003 - Payroll - Admin Wages", "account_type": "Overhead", "net": 300443.66, "firm_code": 3000},
            {"name": "6007 - Directors Remuneration - MMP & RS", "account_type": "Overhead", "net": 26716.29, "firm_code": 3000}]

    class Q:                     # a database that knows only the chart (its first query); nothing remembered
        calls = 0

        def execute(self, *_a, **_k):
            Q.calls += 1
            found = list(chart.values()) if Q.calls == 1 else []
            return N(scalars=lambda: N(all=lambda: found))
    for name in ("_owner_of", "_client_name_key", "_company_of"):
        monkeypatch.setattr(MappingService, name, staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(MappingService, "_client_codes", staticmethod(lambda *a, **k: {}))
    monkeypatch.setattr(MappingService, "last_year_codes", staticmethod(lambda *a, **k: {}))
    monkeypatch.setattr(MappingService, "_client_uses_firm_codes", staticmethod(lambda *a, **k: False))
    monkeypatch.setattr("backend.app.services.mapping.firm_examples.habits", lambda db: {})
    monkeypatch.setattr("backend.app.services.mapping.mapping_service.load_rules", lambda db, owner: [])
    out = MappingService._map_rows(rows, Q(), None)
    assert [(r["std_code"], r["match_source"]) for r in out] == [(5354, "CLIENT_FIRM_CODE"), (3000, "CLIENT_FIRM_CODE"),
                                                                    (3010, "CLIENT_FIRM_CODE")]   # directors' pay: s412
