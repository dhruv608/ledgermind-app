"""B2 journal records: each line carries the journal's number, its source (the review point by name) and status."""
from types import SimpleNamespace as NS

from backend.app.services.workbook.journal_lines import journal_source, workbook_journals


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a, **k):
        return self.rows


class _DB:
    def query(self, model):
        return _Q([NS(id=7, procedure_ref="U-PRE-003", finding_title="Prepayment of insurance")])


def _j(**k):
    base = dict(id=1, finding_id=None, source="REVIEW", status="APPROVED", description="Prepayment: insurance",
                debit_code=4900, credit_code=3260, amount=1098.08, lines=[])
    return NS(**{**base, **k})


def test_source_names_the_review_point_or_manual():
    assert journal_source(_j(finding_id=7), {7: "Prepayment of insurance"}) == "Review point: Prepayment of insurance"
    assert journal_source(_j(source="MANUAL"), {}) == "Manual journal"
    assert journal_source(_j(), {}) == "Review"


def test_two_line_journal_records():
    rows = workbook_journals(_DB(), [_j(finding_id=7)])
    assert [(r["no"], r["code"], r["debit"], r["credit"]) for r in rows] == [(1, "4900", 1098.08, None),
                                                                              (1, "3260", None, 1098.08)]
    assert {r["source"] for r in rows} == {"Review point: Prepayment of insurance"} and {r["status"] for r in rows} == {"Approved"}
