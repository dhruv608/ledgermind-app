"""A review point's figures as a small table for the screen.

The check that raises a point already has its figures in hand; it writes them here as well as in the point's sentence,
so the screen shows them as rows without reading the sentence. Saved as JSON on AuditFinding.figures:

    {"columns": ["", "Ledger", "Return", "Difference"],
     "rows": [{"label": "Box 1 VAT on sales", "values": [-13302.91, 13809.60, 27112.51]},
              {"label": "Net over-declared", "values": [null, null, 26541.02], "strong": true}],
     "more": 3}

A number is money (the screen shows £1,234.56, a minus in brackets); a string is shown as it is; null is an empty cell.
"strong" marks the row the decision turns on. "more" is how many rows of a long list are left out.
"""
import json
from typing import Any, Dict, List, Optional, Sequence

MAX_ROWS = 8


def row(label: str, *values: Any, strong: bool = False) -> Dict[str, Any]:
    """One row: its label and its cells (money as numbers, rounded to the penny; text as text)."""
    cells = [round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else v for v in values]
    return {"label": label, "values": cells, **({"strong": True} if strong else {})}


def table(columns: Sequence[str], rows: List[Dict[str, Any]]) -> Optional[str]:
    """The table as the JSON saved on the point (a long list keeps its first rows and says how many more); None when
    there are no rows."""
    if not rows:
        return None
    out: Dict[str, Any] = {"columns": list(columns), "rows": rows[:MAX_ROWS]}
    if len(rows) > MAX_ROWS:
        out["more"] = len(rows) - MAX_ROWS
    return json.dumps(out)


def amounts(label_amounts: Sequence[tuple], heading: str = "Amount") -> Optional[str]:
    """A two-column table of labels and amounts: [(label, amount)] or [(label, amount, strong)]."""
    return table(["", heading], [row(t[0], t[1], strong=bool(t[2]) if len(t) > 2 else False) for t in label_amounts])
