"""The gate every review point passes before it is saved: code detects, AI narrates, every figure is verified. A query
with an unfilled placeholder such as [x], [Account] or [months] is never sent; it is downgraded to an internal note.

- Tidied: a nil figure written '£-0.00' is £0.00; an empty '()' left by a missing explanation is dropped.
- Downgraded: a point whose wording still holds a blank ([x], {field}) or a missing value (None, nan) becomes an
  internal note for the preparer (LOW, 'Internal note:' in the title), so it never reaches the client as a query.
"""

import re
from typing import Iterable

from backend.app.services.queries.placeholders import BLANK

MINUS_ZERO = re.compile(r"£-0\.00\b|-£0\.00\b")
EMPTY_BRACKETS = re.compile(r"\s*\(\s*\)")
MISSING = re.compile(r"\b(None|nan|NaN|null|undefined)\b|\{[a-z_]+\}")
INTERNAL = "Internal note: "


def _tidy(text: str) -> str:
    return EMPTY_BRACKETS.sub("", MINUS_ZERO.sub("£0.00", text or ""))


def unfilled(text: str) -> bool:
    return bool(BLANK.search(text or "") or MISSING.search(text or ""))


def gate_points(findings: Iterable) -> None:
    for f in findings:
        f.finding_title = _tidy(f.finding_title)
        f.finding_details = _tidy(f.finding_details)
        if (unfilled(f.finding_title) or unfilled(f.finding_details)) and not f.finding_title.startswith(INTERNAL):
            f.finding_title = (INTERNAL + f.finding_title)[:255]
            f.severity = "LOW"
            f.finding_details = (f.finding_details or "") + (
                "\n\nThe app could not fill every figure in this point: check it before anything goes to the client.")
