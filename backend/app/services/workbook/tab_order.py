"""The workbook's tab order: the core pack in the reviewers' order, the app's extra review tabs
(checklists, CT600 boxes, pattern review, GL scrutiny, duplicates, related parties) in an appendix at the back.

1 A, A0, Notes & Queries  2 PY-TB, CY-TB, COA, opening balances  3 General Ledger  4 TTB
5 B1-ETB, B2-Journals, Re-analysis, B3  6-14 C, D, E, F, G, H, I, J, K, inside each by reference (E, E1, E2, E2.1,
E2.2, E3: each control before its ledger; numbers as numbers, G3 before G10)
15 Appendix. Formulas and links name their tab, so the order changes no figure."""

import re
from typing import List

APPENDIX = re.compile(r"^(A[1-9]\b|H2\b|K0\b)|duplicates review|related parties", re.I)
COVER = re.compile(r"^(A|A0\b.*|notes & queries)$", re.I)
INPUTS = [re.compile(r"^PY-TB\b", re.I), re.compile(r"^CY-TB\b", re.I), re.compile(r"^COA$", re.I),
          re.compile(r"^OBD\b", re.I)]
GENERAL_LEDGER = re.compile(r"^general ledger", re.I)
TTB = re.compile(r"^TTB$", re.I)
JOURNALS = re.compile(r"^(B\d|re-analysis)", re.I)
SECTION = re.compile(r"^([C-K])(?=\d|$|[\s(.\-])")
# The reference's numbers: 'E2.1-Debtors NL' (2, 1), 'C1-1-FA detail' (1, 1), 'F3.1 - 4800 - Bank' (3, 1)
REFERENCE = re.compile(r"^[C-K](\d+(?:[.\-]\d+)*)")
APPENDIX_GROUP = 15


def tab_group(title: str):
    """(group, place within the group) for a tab name; None when the name says nothing (it stays with the tab
    before it)."""
    if APPENDIX.search(title):
        return APPENDIX_GROUP, ()
    if COVER.match(title):
        return 1, ()
    for i, pattern in enumerate(INPUTS):
        if pattern.match(title):
            return 2, (i,)
    if GENERAL_LEDGER.match(title):
        return 3, ()
    if TTB.match(title):
        return 4, ()
    if JOURNALS.match(title):
        return 5, ()
    m = SECTION.match(title)
    if m:
        ref = REFERENCE.match(title)
        numbers = tuple(int(n) for n in re.split(r"[.\-]", ref.group(1))) if ref else ()
        return 6 + ord(m.group(1)) - ord("C"), numbers
    return None


def spec_order(titles: List[str]) -> List[str]:
    """The tab names in the workbook's set order; inside a section by reference number, otherwise the workbook's own order."""
    keyed = []
    last = (1, ())
    for i, title in enumerate(titles):
        group = tab_group(title)
        if group is None:
            group = last                  # an unnamed tab stays after the tab it followed
        else:
            last = group
        keyed.append((group[0], group[1], i, title))
    return [t for *_k, t in sorted(keyed)]


def order_tabs(wb) -> None:
    """Put the tabs in the set order and open the file on the cover (A)."""
    for index, title in enumerate(spec_order(wb.sheetnames)):
        ws = wb[title]
        wb.move_sheet(ws, offset=index - wb.index(ws))
    cover = "A" if "A" in wb.sheetnames else wb.sheetnames[0]
    for ws in wb.worksheets:
        ws.sheet_view.tabSelected = ws.title == cover
    wb.active = wb.sheetnames.index(cover)
