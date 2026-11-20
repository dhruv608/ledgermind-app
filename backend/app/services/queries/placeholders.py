"""
Blanks in the rule libraries' question templates ('A balance of £[x] remains in [suspense/clearing account]'): filled
from what the check found, and any sentence still holding a blank is left out, so no client or accountant sees '[x]'.
Plain brackets of other kinds ('[1]', '[a-z]') are
not blanks.
"""

import re
from typing import Dict, Optional

BLANK = re.compile(r"\[(?!\d)[A-Za-z][A-Za-z0-9 /_\-]{0,40}\]")
SENTENCE = re.compile(r"(?<=[.?!])\s+")


def fill(text: Optional[str], values: Optional[Dict[str, str]] = None) -> str:
    """The template with its known blanks filled (keys are the blank's words, any case: {'x': '1,250.00'}) and every
    sentence that still has a blank left out."""
    text = text or ""
    for name, value in (values or {}).items():
        if value not in (None, ""):
            text = re.sub(r"\[" + re.escape(name) + r"\]", lambda _: str(value), text, flags=re.IGNORECASE)
    if not BLANK.search(text):
        return text
    lines = []
    for line in text.split("\n"):
        kept = [s for s in SENTENCE.split(line) if not BLANK.search(s)]
        if kept or not line.strip():
            lines.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

