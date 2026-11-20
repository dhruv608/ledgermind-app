"""The working paper pack written from made-up figures (no database): the firm's header on every sheet, the standard
sheets, DRAFT marked, firm rows first on Queries, document numbers carried."""

import io
from datetime import date

from openpyxl import load_workbook

from backend.app.sa import pack


def _data(kind="FINAL", blocks=0):
    heads = {"TURNOVER": {"label": "Turnover", "box": 15, "kind": "income", "amount": 20000.0, "disallowed": 0.0},
             "OFFICE": {"label": "Phone, stationery and office costs", "box": 23, "kind": "cost", "amount": 300.0, "disallowed": 100.0}}
    calc = {"total_income": 49800.0, "net_income": 49800.0, "adjusted_net_income": 49800.0, "personal_allowance": 12570.0,
            "lines": [{"kind": "non_savings", "band": "basic", "amount": 37230.0, "rate": 0.2, "tax": 7446.0}],
            "income_tax": 7446.0, "reductions": {}, "income_tax_due": 7446.0, "class4": 790.0, "class2": 0.0, "hicbc": 0.0,
            "student_loan": 0.0, "liability": 8236.0, "tax_deducted": 3486.0, "balance": 4750.0, "poa_each": 2375.0,
            "due_31_january": 7125.0}
    inc = {k: 0.0 for k in ("employment", "self_employment", "property", "pensions", "foreign", "other", "savings", "dividends", "reliefs")}
    inc.update(employment=30000.0, self_employment=19800.0)
    return {
        "person": "Client A", "tax_year": "2025-26", "year_end": pack.year_end_words("2025-26"), "kind": kind, "version": 3,
        "note": "After the client's answers", "blocks": blocks, "counts": {"client": 1, "decisions": 0, "blocks": blocks},
        "made": date(2026, 11, 3), "utr": "•••••••123", "ni": None, "first_return": False, "company": None,
        "sources": ["Employment", "Self Employment"],
        "sections": [{"label": "Employment", "amount": 30000.0, "state": "done", "from": "1 P60"}],
        "result": {k: calc[k] for k in ("income_tax_due", "class4", "class2", "liability", "tax_deducted", "balance", "poa_each", "due_31_january")},
        "deadlines": pack.deadlines("2025-26"),
        "employments": [{"name": "Employer A", "ref": "123/AB456", "pay": 30000.0, "tax": 3486.0, "doc_id": 7, "note": None}],
        "income": [], "reliefs": [{"name": "Gift Aid", "amount": 100.0, "gross": 125.0, "doc_id": None, "note": ""}],
        "savings": [], "dividends": [],
        "businesses": [{"name": "Trade A/B", "cash_basis": True, "page": "SA103S", "headings": heads, "income": 20000.0, "costs": 300.0,
                        "disallowed": 100.0, "accounts_profit": 19700.0, "use_of_home": 0.0, "mileage": 0.0, "capital_allowances": 0.0,
                        "balancing_charges": 0.0, "trading_allowance": 0.0, "adjusted_profit": 19800.0, "losses_used": 0.0,
                        "taxable_profit": 19800.0, "loss_cf": 0.0, "cis_deducted": 0.0, "warnings": [],
                        "items": [{"description": "From the bank statements", "heading": "Turnover", "amount": 20000.0, "disallowed": 0.0, "doc_id": None}],
                        "bank": [{"description": "Receipt from customer", "on": "2025-05-01", "in": 500.0, "out": 0.0, "heading": "Turnover", "doc_id": 9}]}],
        "property": None,
        "last_year": {"lines": [{"source_label": "Employment", "name": "Employer A", "last_amount": 20000.0, "this_amount": 30000.0,
                                 "status_label": "Changed", "answer": "Pay rise", "ended": None, "note": None}], "new": []},
        "calc": calc, "inc": inc, "notes": [],
        "queries": [{"kind": "CLIENT", "text": "Please send your P60.", "block": True, "answer": None, "status": "OPEN"},
                    {"kind": "DECISION", "text": "Decide the treatment.", "block": False, "answer": "Not taxable: letter seen", "status": "DONE"}],
        "evidence": [{"id": 7, "file": "p60.pdf", "kind": "P60", "tax_year": "2025-26", "status": "Read", "in_year": "Yes",
                      "answers": "Employment: Employer A", "read_by": "text"}],
        "boxes": {"pages": [{"form": "SA102", "title": "Employment: Employer A",
                             "rows": [{"box": "1", "label": "Pay from this employment", "value": 30000.0, "note": "", "doc_id": 7}]}],
                  "left": []},
    }


def _open(d):
    return load_workbook(io.BytesIO(pack.workbook(d)))


def test_sheets_in_order_with_the_firm_header():
    wb = _open(_data())
    assert wb.sheetnames == ["Summary", "Client info", "PAYE", "SE Trade A B", "Bank 1", "Last year vs this year", "Tax computation",
                             "Queries", "Accountant decisions", "Evidence map", "Rules and law", "Export"]
    for ws in wb.worksheets:
        assert ws["A1"].value == "Clients Name: Client A" and ws["D1"].value == "Year ending: 5th April 2026"
        assert ws.protection.sheet                               # kept as made
    paye = wb["PAYE"]
    row = next(r for r in paye.iter_rows(values_only=True) if r[0] == "Employer 1 :")
    assert row[1:8] == ("Employer A", "PAYE Ref:", "123/AB456", 30000, 3486, None, 7)


def test_draft_marked_on_every_sheet():
    wb = _open(_data("DRAFT", 2))
    assert all(ws["A3"].value == "DRAFT version 3: 2 block(s) open. Not for filing." for ws in wb.worksheets)
    assert _open(_data())["Summary"]["A3"].value is None


def test_queries_firm_rows_first_and_decisions_apart():
    wb = _open(_data())
    rows = [r for r in wb["Queries"].iter_rows(min_row=4, values_only=True) if r[0] is not None]
    assert rows[0][:2] == ("No.", "Query")
    assert [r[1] for r in rows[1:]] == ["Money Laundering ID all in place?", "Letter of engagement?", "Please send your P60. [Block]"]
    dec = [r for r in wb["Accountant decisions"].iter_rows(min_row=5, values_only=True) if r[0] is not None]
    assert dec[0][:4] == (1, "Decide the treatment.", "Not taxable: letter seen", "Done")


def test_summary_and_export_figures():
    wb = _open(_data())
    s = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    assert s["Pack"] == "Final version 3" and s["Balance to pay (refund if negative)"] == 4750
    assert s["Online return, balancing payment and first payment on account"].date() == date(2027, 1, 31)
    exp = [r for r in wb["Export"].iter_rows(values_only=True) if r[1] == "1"]
    assert exp == [(None, "1", "Pay from this employment", 30000, None)]
    ly = [r for r in wb["Last year vs this year"].iter_rows(values_only=True) if r[1] == "Employer A"][0]
    assert ly[2:7] == (20000, 30000, 0.5, "Changed", "Pay rise")


def test_year_end_and_deadlines():
    assert pack.year_end_words("2024-25") == "5th April 2025"
    assert [d for _, d in pack.deadlines("2025-26")] == [date(2026, 10, 31), date(2026, 12, 30), date(2027, 1, 31), date(2027, 7, 31)]


def test_split_trade_compared_once():
    d = _data()
    part = {"source_label": "Self-employment", "status_label": "Changed", "answer": None, "ended": None, "note": None,
            "this_amount": 30000.0, "group": "Part of Trade A: compared as one trade", "group_last": 20000.0}
    d["last_year"]["lines"] = [dict(part, name="Contract 1", last_amount=15000.0, group_first=True),
                               dict(part, name="Contract 2", last_amount=5000.0, group_first=False)]
    rows = [r for r in _open(d)["Last year vs this year"].iter_rows(values_only=True) if r[1] in ("Contract 1", "Contract 2")]
    assert rows[0][2:7] == (15000, 30000, 0.5, "Changed", "Part of Trade A: compared as one trade")
    assert rows[1][2:7] == (5000, None, None, "Changed", None)


def test_pack_read_back_as_next_years_last_year():
    from backend.app.sa.extract.lastyear import sheets_text
    text = sheets_text(pack.workbook(_data()), "wp.xlsx")
    assert "=== Sheet: PAYE" in text and "Employer 1 : | Employer A | PAYE Ref: | 123/AB456 | 30000 | 3486 | 7" in text
    for skipped in ("Bank 1", "Last year vs this year", "Evidence map"):
        assert f"=== Sheet: {skipped}" not in text


def test_capital_gains_sheet():
    from datetime import date as d_
    from types import SimpleNamespace as N
    from backend.app.sa import cgt
    row = cgt.one(N(id=1, kind="LISTED", name="Shares A", acquired="2015-04-06", contract_date="2025-10-06",
                    completion_date=None, proceeds=30000, cost=10000, costs=0, improvements=0, share=1, uk=1,
                    main_home_months=None, badr=0, negligible=0, rtt_date=None, rtt_gain=None, rtt_tax=None, doc_id=None),
                  "2025-26", d_(2026, 11, 3))
    d = _data()
    d["cgt"] = {"disposals": [row], "summary": cgt.compute([row], 0, "2025-26", 30000, 37700), "notes": []}
    ws = _open(d)["Capital gains"]
    vals = {r[0]: r for r in ws.iter_rows(values_only=True) if r[0]}
    assert vals["Shares A"][3:8] == (30000, 10000, 20000, None, 20000)
    assert vals["Chargeable gains"][3] == 17000 and vals["Capital gains tax"][5] == 3618
