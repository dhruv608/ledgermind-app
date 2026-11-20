"""A ledger in several files (one per quarter): copies read once, last year's quarter left out, openings from the first."""
from datetime import date

import pandas as pd

from backend.app.services.ingestion.ledger_files.gl_parts import distinct_parts, join_parts


def _part(start, end, opening):
    df = pd.DataFrame({"Date": pd.to_datetime([start, end]), "Debit": [1.0, 2.0], "Credit": [0.0, 0.0],
                       "Parent_Account": ["Sales", "Sales"]})
    df.attrs = {"opening_balances": {"Bank": opening}, "explicit_sides": True}
    return df


def test_copies_read_once():
    files = [("Q5.xlsx", b"same", None), ("Q5(1).xlsx", b"same", None), ("Q4.xlsx", b"other", None)]
    assert [f[0] for f in distinct_parts(files)] == ["Q5.xlsx", "Q4.xlsx"]


def test_parts_joined_in_date_order_every_part_kept():
    q1 = _part("2024-10-01", "2024-12-31", 10.0)          # a 15-month period's first quarter is kept (the TB has it)
    q3 = _part("2025-07-01", "2025-09-30", 30.0)
    q2 = _part("2025-01-01", "2025-03-31", 20.0)
    out = join_parts([q1, q3, q2], date(2025, 12, 31))
    assert len(out) == 6 and out["Date"].min() == pd.Timestamp("2024-10-01")
    assert out.attrs["opening_balances"] == {"Bank": 10.0} and out.attrs["parts"] == 3
