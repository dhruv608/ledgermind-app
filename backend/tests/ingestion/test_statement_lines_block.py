"""A read bank statement's lines go under the bank's T in the workbook: Unrecorded, Unmatched, Matched with totals;
nothing when no statement was read."""
from types import SimpleNamespace

import openpyxl

from backend.app.services.workbook.balance_tabs.statement_lines import statement_lines_block

MATCH = {
    "read": True, "from": "2024-04-01", "to": "2025-03-31", "statement_lines": 3, "ledger_lines": 3,
    "unrecorded": [{"date": "2024-05-02", "description": "Bank charge", "amount": -12.5}],
    "unmatched": [{"date": "2024-06-01", "description": "Cheque 104", "amount": -300.0},
                  {"date": "2024-06-03", "description": "Deposit", "amount": 50.0}],
    "matched": [{"statement": {"date": "2024-07-01", "description": "Customer A", "amount": 1000.0},
                 "ledger": {"date": "2024-07-02"}, "days": 1}],
}


def _texts(ws):
    return [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]


def test_lists_written_with_totals():
    ws = openpyxl.Workbook().active
    end = statement_lines_block(SimpleNamespace(statement_lines={4800: MATCH}), ws, 4800, 30)
    texts = _texts(ws)
    assert "Unrecorded (1)" in texts and "Unmatched (2)" in texts and "Matched (1)" in texts
    assert any("1 day apart" in t for t in texts)
    totals = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=SUM(")]
    assert len(totals) == 3
    assert end > 30


def test_nothing_without_a_statement():
    ws = openpyxl.Workbook().active
    assert statement_lines_block(SimpleNamespace(statement_lines={}), ws, 4800, 30) == 30
    assert statement_lines_block(SimpleNamespace(statement_lines={4800: {"read": False}}), ws, 4800, 30) == 30
    assert _texts(ws) == []
