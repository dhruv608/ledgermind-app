"""Last year's working paper read into sources (made-up figures; the AI's answer is given, not asked)."""

import io

import pandas as pd

from backend.app.sa.extract.lastyear import clean, merge, previous_year, sheets_text


def test_answer_kept_to_known_sources():
    out = clean({"total_income": 30000, "answers": {"child_benefit": False, "pets": True},
                 "lines": [{"source": "EMPLOYMENT", "kind": "P60", "name": "Employer A", "ref": "123/AB456", "amount": "20,000", "tax": 2000},
                           {"source": "SAVINGS", "kind": "ISA", "name": "Bank B", "amount": 500},          # kind put right
                           {"source": "CARRY_FORWARD", "kind": "DEFERRED", "name": "Invoice left to next year", "amount": 4000},
                           {"source": "LOTTERY", "kind": "WIN", "name": "x", "amount": 1}]})
    assert [(l["source"], l["kind"]) for l in out["lines"]] == [("EMPLOYMENT", "P60"), ("SAVINGS", "INTEREST"), ("CARRY_FORWARD", "DEFERRED")]
    assert out["lines"][0]["amount"] == 20000.0 and out["answers"] == {"child_benefit": False} and out["total_income"] == 30000


def test_two_reads_compared():
    first = clean({"lines": [{"source": "EMPLOYMENT", "kind": "P60", "name": "Employer A", "amount": 20000},
                             {"source": "PROPERTY", "kind": "PROFIT", "name": "1 Any Street", "amount": 8000, "note": "whole"}]})
    second = clean({"lines": [{"source": "EMPLOYMENT", "kind": "P60", "name": "EMPLOYER A LTD", "amount": 20000.4},
                              {"source": "PROPERTY", "kind": "PROFIT", "name": "1 Any Street", "amount": 4000, "note": "50% share"}]})
    out = merge(first, second)
    assert [(l["amount"], l["agreed"]) for l in out["lines"]] == [(20000.0, True), (8000.0, False), (4000.0, False)]
    assert out["checks"] == ["2 lines read differently by the two readers: check against the working paper."]


def test_sheets_as_rows_bank_sheets_left_out():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame([["Employer 1 :", "Employer A", 20000.0], [None, None, None], ["Total income", None, 20000.0]]).to_excel(w, sheet_name="PAYE", header=False, index=False)
        pd.DataFrame([["Balance Bfwd", 100.0]]).to_excel(w, sheet_name="Bank 1", header=False, index=False)
    text = sheets_text(buf.getvalue(), "wp.xlsx")
    assert "=== Sheet: PAYE" in text and "r1: Employer 1 : | Employer A | 20000" in text and "Bank 1" not in text


def test_previous_year():
    assert previous_year("2025-26") == "2024-25" and previous_year("2000-01") == "1999-00"


def test_same_payer_and_questions():
    from types import SimpleNamespace as N
    from backend.app.sa.lastyear import _same_payer, question
    assert _same_payer("Employer A Holdings Ltd", None, "EMPLOYER A HOLDINGS LIMITED")
    assert _same_payer("Old name", "123/AB456", "New name plc", "PAYE 123/AB456")         # the PAYE reference
    assert not _same_payer("First Bank Savings", None, "Second Bank Savings")             # 'bank', 'savings' say nothing
    line = N(source="EMPLOYMENT", kind="P60", name="Employer A", last_amount=20000)
    assert question(line, 2026) == "Did you still work for Employer A on 5 April 2026? If so, please send your P60."
    left = N(source="CARRY_FORWARD", kind="DEFERRED", name="Invoice 12", last_amount=4000)
    assert question(left, 2026).startswith("Last year's working paper left £4,000.00 for Invoice 12 to this year")


def test_client_message_lists_open_queries_once():
    from backend.app.sa.queries import client_text
    item = lambda text, status, kind="CLIENT": {"kind": kind, "status": status, "text": text}
    data = {"items": [item("Please send the P60.", "OPEN"), item("Please send the P60.", "OPEN"),
                      item("Answered already.", "ANSWERED"), item("Decide this.", "OPEN", "DECISION"),
                      item("Please send the interest statement.", "OPEN")]}
    text = client_text(data, "Pat Trader", "2025-26")
    assert text.startswith("Hello Pat,") and "1. Please send the P60.\n2. Please send the interest statement." in text
    assert "Answered already" not in text and "Decide this" not in text


def test_use_of_home_is_never_income_and_a_nil_pool_carries_nothing():
    from backend.app.sa.extract.lastyear import clean
    f = clean({"lines": [{"source": "OTHER", "kind": "INCOME", "name": "Use of home", "amount": 288},
                         {"source": "CARRY_FORWARD", "kind": "CA_POOL", "name": "Special rate pool", "amount": 0},
                         {"source": "CARRY_FORWARD", "kind": "CA_POOL", "name": "Main pool", "amount": 1200}]})
    assert [(l["source"], l["kind"], l["amount"]) for l in f["lines"]] == [("CARRY_FORWARD", "USE_OF_HOME", 288.0),
                                                                          ("CARRY_FORWARD", "CA_POOL", 1200.0)]


def test_last_years_p11d_and_expenses_are_asked_about():
    from types import SimpleNamespace as N
    from backend.app.sa.extract.lastyear import clean
    from backend.app.sa.lastyear import question
    f = clean({"lines": [{"source": "EMPLOYMENT", "kind": "BENEFIT", "name": "A Co Ltd", "amount": 4200},
                         {"source": "EMPLOYMENT", "kind": "EXPENSES", "name": "Professional fees", "amount": 300}]})
    assert [l["kind"] for l in f["lines"]] == ["BENEFIT", "EXPENSES"]
    assert "P11D" in question(N(source="EMPLOYMENT", kind="BENEFIT", name="A Co Ltd", ref=None, last_amount=4200), 2026)
    assert "R-SA102-05" in question(N(source="EMPLOYMENT", kind="EXPENSES", name="Fees", ref=None, last_amount=300), 2026)


def test_a_company_working_paper_is_not_last_years_return():
    from backend.app.sa.lastyear import COMPANY_FILE
    assert COMPANY_FILE.search("Test Consulting Ltd Working Papers 2025.xls")
    assert not COMPANY_FILE.search("Working papers Pat Test 2024-25.xls")
