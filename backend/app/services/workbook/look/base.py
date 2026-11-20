"""The house style's colours, sizes and cell helpers, and finding the tables on a tab."""

import re
from typing import List, Optional, Tuple

from openpyxl.styles import Font, PatternFill, Side

TEAL, TEAL_LIGHT, WHITE, SLATE, INK = "0F766E", "CCFBF1", "FFFFFF", "64748B", "0F172A"
ROW_LINE = Side(style="thin", color="E2E8F0")      # a table row's line below
DARK = Side(style="thin", color="334155")          # a line above a total
DOUBLE = Side(style="double", color="334155")      # a total's line below
TEAL_LINE = Side(style="medium", color=TEAL)       # under a section heading
DASHED = Side(style="dashed", color="F59E0B")      # round a cell to type in
NO_SIDE = Side(style=None)
BAND_FILL = PatternFill("solid", fgColor=TEAL)
HEAD_FILL = PatternFill("solid", fgColor=TEAL)
ZEBRA_FILL = PatternFill("solid", fgColor="F8FAFC")
CHECK_STRIP = PatternFill("solid", fgColor="F1F5F9")
SECTION_FILL = PatternFill("solid", fgColor="F0FDFA")     # behind a section heading: the lightest teal
LEAD_HEAD_FILL = PatternFill("solid", fgColor="F1F5F9")   # a lead schedule's heading row: light grey
LEAD_ROW_HEIGHT = 17                                       # lead rows a little taller than Excel's 15
LEAD_BAND_COLS = 5                                         # the lead heading band: columns A-E
GOOD_FILL, GOOD_FONT = PatternFill("solid", fgColor="DCFCE7"), Font(color="166534", bold=True)
BAD_FILL, BAD_FONT = PatternFill("solid", fgColor="FEE2E2"), Font(color="991B1B", bold=True)
AMBER_FILL, AMBER_FONT = PatternFill("solid", fgColor="FEF3C7"), Font(color="92400E", bold=True)
INPUT_COLOUR = "FFF2CC"

LONG_TAB = 30                # rows before a tab gets frozen headings
WIDE_TAB = 7                 # used columns before a tab prints landscape
BAND_MIN, BAND_MAX = 6, 14   # the title band's width in columns
REF_LIKE = re.compile(r"^[A-K]{1,2}\d{0,2}(?:[.-][\dD]{1,2}){0,2}[a-z]?$")   # a tab reference: E2, F3.1, G3.D1, C1-1
COVER = "A"                  # the cover tab the back link points to
HEADING_WORDS = re.compile(r"^(date|code|nc|account|account code|account name|description|debit|credit|amount|"
                           r"month|contact|name|type|reference|ref|no\.?|details|balance|net|vat|vat code|supplier|"
                           r"customer|payee|receipt|payment|running balance|status|tab|check|cell|value|director|"
                           r"employee|period|due by|paid|owed|item|cost|depreciation|nbv|flag|days old|number|"
                           r"opening|closing|movement|journal|narrative|source|particulars|additions|disposals|"
                           r"b/fwd|c/fwd|carried forward|brought forward|rate|charge)\b", re.I)
TOTAL_LABEL = re.compile(r"^\s*(total\b|balance c/fwd|grand total|unexplained difference)", re.I)
SUBTOTAL_LABEL = re.compile(r"^\s*closing per books", re.I)
# The true final balances: the only rows with a double line (on their amounts); every other total is a grey band
FINAL_LABEL = re.compile(r"^\s*balance c/fwd|profits chargeable to corporation tax|^\s*corporation tax chargeable|"
                         r"total tax chargeable|^\s*carried forward|^\s*net book value|^\s*nbv\b", re.I)
TOTAL_FILL = PatternFill("solid", fgColor="F1F5F9")       # a table total's band: light grey
CHECK_LABEL = re.compile(r"must be (nil|0|zero)|^\s*check\b", re.I)
LEAD_START = re.compile(r"^\s*(balance b/fwd|opening balance b/f\b)", re.I)
T_START = re.compile(r"^\s*opening balance b/f\b", re.I)     # a T account (balance_tabs/t_shape)
LEAD_END = re.compile(r"check: b1-etb final balance|check: balance c/d v b1-etb", re.I)
SECTION_COLOURS = (           # by the tab's first letters: (pattern, dark colour, light tint); muted, print-safe
    (re.compile(r"^A$|^A |^A\d|^Notes", re.I), "475569", "F8FAFC"),                 # cover, checks, notes: slate
    (re.compile(r"^B\d|^TTB|^CY-TB|^PY-TB|^OBD|^COA|^General Ledger", re.I), TEAL, "F0FDFA"),  # TB, ETB, GL: teal
    (re.compile(r"^C\d|^C$", re.I), "1E40AF", "EFF6FF"),       # fixed assets: blue
    (re.compile(r"^D\d|^D$", re.I), "78350F", "FFFBEB"),       # stock: brown
    (re.compile(r"^E\d|^E$", re.I), "166534", "F0FDF4"),       # debtors and prepayments: green
    (re.compile(r"^F\d|^F$|^F-P", re.I), "075985", "F0F9FF"),  # bank and cards, platforms: sky
    (re.compile(r"^G\d|^G$", re.I), "92400E", "FFFBEB"),       # creditors, loans, DLA, payroll, VAT: amber
    (re.compile(r"^H\d|^H$", re.I), "991B1B", "FEF2F2"),       # tax: red
    (re.compile(r"^J\d|^J$", re.I), "334155", "F8FAFC"),       # reserves and share capital: dark slate
    (re.compile(r"^K\d|^K$|^K |^Re-analysis", re.I), "155E75", "ECFEFF"),  # P&L, GL scrutiny, takings: cyan
    (re.compile(r"^P\d|^D1-P", re.I), "3F6212", "F7FEE7"),     # industry schedules (property, development): olive
)
# The tab being styled: its section's colours (finish_look sets them before each tab)
CURRENT = {"dark": TEAL, "tint": "F0FDFA"}


def _dark() -> str:
    return CURRENT["dark"]


def _tint() -> str:
    return CURRENT["tint"]


def _palette(title: str):
    """(dark, tint) of the tab's section; teal when it has none."""
    return next(((d, t) for pattern, d, t in SECTION_COLOURS if pattern.search(title.strip())), (TEAL, "F0FDFA"))


def _merged(c) -> bool:
    return type(c).__name__ == "MergedCell"


def _text(c) -> Optional[str]:
    return c.value.strip() if isinstance(c.value, str) and c.value.strip() and not c.value.startswith("=") else None


def _is_formula(c) -> bool:
    return isinstance(c.value, str) and c.value.startswith("=")


def _amount(c) -> bool:
    return _is_formula(c) or (isinstance(c.value, (int, float)) and not isinstance(c.value, bool))


def _font(c, **kw) -> Font:
    size = c.font.sz if c.font is not None and c.font.sz else 10
    return Font(name="Calibri", size=kw.pop("size", size), **kw)


def _has_border(b) -> bool:
    return b is not None and any(getattr(getattr(b, s, None), "style", None) for s in ("left", "right", "top", "bottom"))


def _is_input(c) -> bool:
    """A cell for the accountant to type in: shaded yellow and not a formula (a check's formula shares the colour)."""
    return bool(c.fill is not None and c.fill.fill_type == "solid" and not _is_formula(c)
                and str(getattr(c.fill.fgColor, "rgb", "") or "").endswith(INPUT_COLOUR))


# ---------------------------------------------------------------------------------------------------------------------
# Finding the tables
# ---------------------------------------------------------------------------------------------------------------------
def _is_heading(row) -> Optional[Tuple[int, int]]:
    """(first, last column) of a heading row: three or more short text cells, most of them heading words, bold."""
    texts = [c for c in row if _text(c)]
    filled = [c for c in row if c.value not in (None, "")]
    if len(texts) < 3 or len(texts) < len(filled) - 1:
        return None
    words = sum(1 for c in texts if len(c.value) <= 40 and HEADING_WORDS.match(c.value.strip()))
    bold = sum(1 for c in texts if c.font is not None and c.font.b)
    if words < 2 or bold < 2:
        return None
    return filled[0].column, filled[-1].column


def _heading_row(ws) -> Optional[int]:
    """The first heading row in the tab's first 15 rows (frozen and printed on every page)."""
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 15)):
        if _is_heading(row):
            return row[0].row
    return None


def _tables(ws) -> List[Tuple[int, int, int, int]]:
    """(heading row, first column, last column, last body row) of every table: a heading row, then its rows down to the
    first empty row."""
    out = []
    rows = list(ws.iter_rows())
    i = 0
    while i < len(rows):
        span = _is_heading(rows[i])
        if not span:
            i += 1
            continue
        first, last = span
        j = i + 1
        while j < len(rows) and any(c.value not in (None, "") for c in rows[j][first - 1:last]):
            j += 1
            # The ETB's one blank row between the P&L and the balance sheet codes: the same table goes on below it
            if (ws.title == "B1-ETB" and j + 1 < len(rows) and all(c.value in (None, "") for c in rows[j])
                    and isinstance(rows[j + 1][0].value, int)):
                j += 1
        out.append((rows[i][0].row, first, last, rows[j - 1][0].row))
        i = j
    return out


__all__ = ["TEAL", "TEAL_LIGHT", "WHITE", "SLATE", "INK", "ROW_LINE", "DARK", "DOUBLE", "TEAL_LINE", "DASHED", "NO_SIDE", "BAND_FILL", "HEAD_FILL", "ZEBRA_FILL", "CHECK_STRIP", "SECTION_FILL", "LEAD_HEAD_FILL", "LEAD_ROW_HEIGHT", "LEAD_BAND_COLS", "GOOD_FILL", "GOOD_FONT", "BAD_FILL", "BAD_FONT", "AMBER_FILL", "AMBER_FONT", "INPUT_COLOUR", "LONG_TAB", "WIDE_TAB", "BAND_MIN", "BAND_MAX", "REF_LIKE", "COVER", "HEADING_WORDS", "TOTAL_LABEL", "SUBTOTAL_LABEL", "FINAL_LABEL", "TOTAL_FILL", "CHECK_LABEL", "LEAD_START", "T_START", "LEAD_END", "SECTION_COLOURS", "CURRENT", "_dark", "_tint", "_palette", "_merged", "_text", "_is_formula", "_amount", "_font", "_has_border", "_is_input", "_is_heading", "_heading_row", "_tables"]
