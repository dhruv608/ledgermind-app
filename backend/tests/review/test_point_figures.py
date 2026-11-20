"""A review point's figures table (review/point_figures.py): money rounded to the penny, text kept, a long list cut to
its first rows with the count of the rest, and the saved JSON read back by the API schema."""
import json

from backend.app.models.schemas import AuditFindingSchema
from backend.app.services.review.point_figures import MAX_ROWS, amounts, row, table


def test_row_rounds_money_and_keeps_text():
    r = row("Box 1 VAT on sales", 13302.914, "10 of 12", None, strong=True)
    assert r == {"label": "Box 1 VAT on sales", "values": [13302.91, "10 of 12", None], "strong": True}
    assert "strong" not in row("Plain", 1)


def test_long_list_keeps_first_rows_and_counts_the_rest():
    saved = json.loads(table(["Account", "Amount"], [row(f"Account {i}", i) for i in range(MAX_ROWS + 3)]))
    assert len(saved["rows"]) == MAX_ROWS and saved["more"] == 3
    assert table(["", "Amount"], []) is None


def test_amounts_marks_the_strong_row():
    saved = json.loads(amounts([("Owed per the books", 9529.46), ("Difference", 9698.74, True)]))
    assert saved["columns"] == ["", "Amount"]
    assert saved["rows"][1] == {"label": "Difference", "values": [9698.74], "strong": True}


def test_schema_reads_the_saved_json():
    base = dict(procedure_ref="G3", procedure_name="Missing accruals", severity="HIGH", finding_title="t",
                finding_details="d")
    saved = amounts([("Average a month", 518.16)])
    assert AuditFindingSchema(**base, figures=saved).figures["rows"][0]["values"] == [518.16]
    assert AuditFindingSchema(**base, figures=None).figures is None
    assert AuditFindingSchema(**base, figures="not json").figures is None
