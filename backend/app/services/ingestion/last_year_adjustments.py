"""Last year's closing accruals (5360) and prepayments (4900), item by item, from last year's final working paper.

The papers keep them on an accruals tab (G5 / G6 / G7) and a prepayments tab (E2 / E3): a heading row with the two
years, one row per item (name, this year's figure, last year's), then a totals row with no name. The paper's current
year column is what was owed (or paid ahead) at the start of this year: those are the lines to reverse now. Each item
goes to its cost: the code in its name ('3301 Accountancy fees'), else the trial balance account its words match best,
else the cost its words name; an item with no cost found is left for the accountant to enter. The module also reads
the paper's ETB final balances, open queries, losses, tax WDV, loan balances and director's claims."""

import io
import logging
import re
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)
ACCRUAL_TAB = re.compile(r"accru", re.I)
NOT_ACCRUAL_TAB = re.compile(r"accrued income", re.I)
PREPAYMENT_TAB = re.compile(r"prepay", re.I)
NOTES_TAB = re.compile(r"notes\s*&\s*quer", re.I)
ETB_TAB = re.compile(r"(?:^|[\s-])ETB$|extended trial", re.I)
FINAL_BALANCE = re.compile(r"^\s*final balances?\s*$", re.I)
FINAL_GROUP = re.compile(r"^\s*(?:final(?: balances?| trial balance| tb)?|balance)\s*$", re.I)   # not 'Balance sheet'
TB_TAB = re.compile(r"^(?:trial|trail) balance$|^tb$", re.I)
# The code column's heading: 'NC', 'Xero NC', 'Sage NC', 'Nominal code', 'Code'
CODE_HEAD = re.compile(r"^\s*(?:[a-z]+\s+)?nc\s*$|^\s*nominal\s+codes?\s*$|^\s*codes?\s*$", re.I)
POINT_NUMBER = re.compile(r"^\d{1,2}(\.\d{1,2})?$")
NARRATIVE_MIN = 25          # a narrative line, not a table cell ('Bank name', 'Amount')
# A point still waiting on the client: it asks for something
OPEN_POINT = re.compile(r"\bkindly\b|\bplease (confirm|provide|advise|check|send|let us know)|\badvise\b|"
                        r"awaiting|not (yet )?(been )?(received|provided)", re.I)
YEAR_ENDED = re.compile(r"year\s+end(?:ed|ing)?\s+(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s+(\d{4})", re.I)
# Rows that are workings, not items: totals, the roll of the balance, notes, deferred income (it is reversed to sales)
NOT_ITEM = re.compile(r"\b(total|balance|opening|closing|less|reversed?|reversal|paid|moved|details?|b/?fwd|c/?fwd|"
                      r"brought|carried|movement|current year|prior year|deferred|accruals?$|prepayments?$|"
                      r"note|see|per\b)", re.I)
CODE_IN_NAME = re.compile(r"^\s*(\d{4})\b")
# The cost an item's words name (firm chart)
COST_WORDS: Tuple[Tuple[re.Pattern, int], ...] = (
    (re.compile(r"accountan|accounts? prep|bookkeep|year[- ]end fee|accounting fee", re.I), 3301),
    (re.compile(r"\baudit", re.I), 3300),
    (re.compile(r"\blegal|solicitor", re.I), 3302),
    (re.compile(r"\binterest\b", re.I), 3631),
    (re.compile(r"\bwages?|salar|payroll", re.I), 3000),
    (re.compile(r"\bpension", re.I), 3002),
    (re.compile(r"electric|\bgas\b|light|heat|energy|utilit", re.I), 3130),
    (re.compile(r"\bwater", re.I), 3131),
    (re.compile(r"\brates\b|council tax", re.I), 3110),
    (re.compile(r"\brent\b", re.I), 3100),
    (re.compile(r"insurance", re.I), 3260),
    (re.compile(r"telephone|phone|mobile|broadband|internet", re.I), 3290),
    (re.compile(r"software|subscription|licen[cs]", re.I), 3241),
    (re.compile(r"employer'?s? ni|national insurance|p11d|class 1a", re.I), 3001),
    (re.compile(r"sub\W*contract", re.I), 3020),
    (re.compile(r"consultan", re.I), 3304),
    (re.compile(r"advertis|marketing|exhibition|\bfairs?\b", re.I), 3280),
    (re.compile(r"leasing|\bhire\b", re.I), 3200),
    (re.compile(r"\bpurchases\b", re.I), 1100),
    (re.compile(r"\boffice\b", re.I), 3380),
)
# A working paper reference written where the name goes ('E4.1'): the name is in the next cell
WP_REF = re.compile(r"^[A-Z]\d+(?:\.\d+)*$")
MIN_AMOUNT = 1.0
COST_SECTIONS = {"Cost of sales", "Distribution costs", "Employee costs", "General admin", "Premises expenses",
                 "Interest payable and similar charges", "Other operating and exceptional costs"}
# Words too general to place an item ('Advance payment for leasing': 'leasing' places it, 'payment' does not)
COMMON_WORDS = {"costs", "cost", "expenses", "expense", "charges", "charge", "other", "general", "admin", "payment",
                "payments", "advance", "with", "from", "year", "fees", "accrual", "accruals", "prepayment", "prepaid"}
SOURCE = " (last year's final WP)"      # the description ending that marks a line read from the paper


def _year_end(rows: List[List]) -> Optional[date]:
    def as_date(v) -> Optional[date]:
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        # The last date in the text: a period 'from .. to ..' ends on it ('20.06.2024 to 30.11.2025', '02 Oct 2024 to
        # 31 Oct 2025'); digits or the month in words ('31 March 2026')
        found = []
        iso = re.match(r"^\s*((?:19|20)\d\d)-(\d\d)-(\d\d)(?:[ T]00:00:00)?\s*$", str(v or ""))
        if iso:
            try:
                return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            except ValueError:
                return None
        for m in re.finditer(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})|(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", str(v or "")):
            try:
                found.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m.group(1)
                             else datetime.strptime(f"{m.group(4)} {m.group(5)[:3]} {m.group(6)}", "%d %b %Y").date())
            except ValueError:
                continue
        return found[-1] if found else None

    for r in rows[:8]:
        # Older papers: 'Year end: | 31.12.2023', 'Y.E. : 30.06.2026', 'Year End- 31.03.2026', 'Period end:'
        # with the date in the same cell or the next filled one
        for j, c in enumerate(r):
            if isinstance(c, str) and re.match(r"^\s*(?:year\s*end(?:ed)?|period(?:\s*end)?|[yp]\.\s*e\.?(?=\s*[:\-]|\s*\d|\s*$))\s*[:\-]?", c, re.I):
                d = as_date(c) or as_date(next((x for x in r[j + 1:] if x not in (None, "")), None))
                if d:
                    return d
        for c in r:
            m = YEAR_ENDED.search(str(c or ""))
            if m:
                try:
                    return datetime.strptime(f"{m.group(1)} {m.group(2)[:3]} {m.group(3)}", "%d %b %Y").date()
                except ValueError:
                    return None
    # A title block whose second or third row starts with the year end ('31.03.2025', a date cell, sometimes followed
    # by a link to the trial balance)
    for r in rows[1:3]:
        filled = [c for c in r if c not in (None, "")]
        if filled and as_date(filled[0]):
            return as_date(filled[0])
    return None


def _is_year(c) -> bool:
    return isinstance(c, (int, float)) and float(c).is_integer() and 2000 <= c <= 2100


def items_of_tab(rows: List[List]) -> List[Tuple[str, float]]:
    """(name, this year's figure) for each item on an accruals or prepayments tab, from its heading row on."""
    head = next((i for i, r in enumerate(rows[:15]) if sum(1 for c in r if _is_year(c)) >= 2), None)
    if head is None:
        return []
    years = [(j, c) for j, c in enumerate(rows[head]) if _is_year(c)]
    col = max(years, key=lambda x: x[1])[0]            # this year's column: the later year
    out: List[Tuple[str, float]] = []
    for r in rows[head + 1:head + 40]:
        texts = [str(c).strip() for c in r[:col] if isinstance(c, str) and c.strip()]
        name = next((t for t in texts if not WP_REF.match(t)), texts[0] if texts else None)
        if name is None:
            if any(isinstance(c, (int, float)) for c in r):
                break                                    # the totals row: the items end here
            continue
        if NOT_ITEM.search(name):
            if re.match(r"\s*(opening|closing|details?|total)", name, re.I):
                break
            continue
        value = r[col] if col < len(r) else None
        if isinstance(value, (int, float)) and abs(value) >= MIN_AMOUNT:
            out.append((name[:200], round(abs(float(value)), 2)))
    return out


def read(content: bytes) -> Dict:
    """{'year_end': last year's year end or None, 'items': [(kind, name, amount)], 'claims': [(kind, why, amount)]}
    from a whole final working paper."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        return {"year_end": None, "items": [], "claims": []}
    items: List[Tuple[str, str, float]] = []
    year_end = None
    claims: List[Tuple[str, str, float]] = []
    try:
        if len(wb.sheetnames) < 5:                       # a whole working paper, not a one-tab file
            return {"year_end": None, "items": [], "claims": []}
        claims = director_claims(journals_of(wb))
        for name in wb.sheetnames:
            if ACCRUAL_TAB.search(name) and not NOT_ACCRUAL_TAB.search(name):
                kind = "ACCRUAL"
            elif PREPAYMENT_TAB.search(name):
                kind = "PREPAYMENT"
            else:
                continue
            rows = [list(r) for r in wb[name].iter_rows(max_row=60, values_only=True)]
            year_end = year_end or _year_end(rows)
            if any(k == kind for k, _n, _a in items):
                continue                                 # one tab of each kind (the first)
            items += [(kind, n, a) for n, a in items_of_tab(rows)]
        tax = tax_carried_forward(wb)
        etb = etb_final_with_tab(wb)
        if etb:
            tax["etb_final"] = etb[1]
            year_end = year_end or etb[0]
            tax["etb_tab"] = etb[2]
        notes = next((n for n in wb.sheetnames if NOTES_TAB.search(n)), None)
        if notes is not None:
            rows = [list(r) for r in wb[notes].iter_rows(max_row=400, max_col=10, values_only=True)]
            # The paper's year end from its heading when it has no accruals or prepayments tab
            year_end = year_end or _year_end(rows)
            queries = open_queries(rows)
            if queries:
                tax["open_queries"] = queries
    finally:
        wb.close()
    return {"year_end": year_end, "items": items, "claims": claims, "tax": tax}


def etb_final(wb) -> Optional[Tuple[Optional[date], Dict[str, float]]]:
    """(the paper's year end, {firm code: final balance, debit positive}) from its ETB tab ('B1-ETB': a heading row
    with 'NC' and 'Final balance'): the figures last year's accounts were filed on, which the brought forward balances
    are checked against. None when the paper has no such tab.
    The ETB tab first ('B1-ETB', 'ETB '), then the older paper's 'Trial Balance' / 'Trail Balance' / 'TB' tabs: the
    first whose final balances read and add up to nil (a plain TB read the wrong way is never used)."""
    found = etb_final_with_tab(wb)
    return found[:2] if found else None


def etb_final_with_tab(wb) -> Optional[Tuple[Optional[date], Dict[str, float], str]]:
    """etb_final, and the tab it was read from (shown on the Data check)."""
    names = ([n for n in wb.sheetnames if ETB_TAB.search(n.strip())]
             + [n for n in wb.sheetnames if TB_TAB.search(n.strip())])
    for name in names:
        found = _etb_tab(wb, name)
        if found:
            return found[0], found[1], name.strip()
    return None


def _etb_tab(wb, name: str) -> Optional[Tuple[Optional[date], Dict[str, float]]]:
    rows = [list(r) for r in wb[name].iter_rows(max_row=400, max_col=24, values_only=True)]
    cell = lambda r, j: str(r[j] or "").strip().lower() if j < len(r) else ""
    head = next((i for i, r in enumerate(rows[:15]) if any(CODE_HEAD.search(str(v or "")) for v in r)), None)
    if head is None:
        return None
    code_col = next(j for j, v in enumerate(rows[head]) if CODE_HEAD.search(str(v or "")))
    final_col = next((j for j, v in enumerate(rows[head]) if FINAL_BALANCE.search(str(v or ""))), None)
    if final_col is not None:
        # 'NC | ... | Final balances' over a Debit £ | Credit £ pair on the row below (newer papers), else one signed
        # column
        sub, first = (rows[head + 1] if head + 1 < len(rows) else []), head + 1
    else:
        # Older papers: a group row above the headings ('Opening Balance | TTB | Journals | Final | P&L'), the
        # 'Final' group over 'Balance' or 'Dr | Cr' on the 'Code' row
        above = rows[head - 1] if head > 0 else []
        final_col = next((j for j, v in enumerate(above) if FINAL_GROUP.search(str(v or ""))), None)
        if final_col is None:
            return None
        sub, first = rows[head], head
    pair = cell(sub, final_col).startswith(("debit", "dr")) and cell(sub, final_col + 1).startswith(("credit", "cr"))
    first += 1 if pair and first == head + 1 else 0
    out: Dict[str, float] = {}
    for r in rows[first:]:
        code = r[code_col] if code_col < len(r) else None
        if pair:
            dr = r[final_col] if final_col < len(r) else None
            cr = r[final_col + 1] if final_col + 1 < len(r) else None
            num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
            # A credit is shown positive (the newer paper) or negative (the older one): taken off either way
            amount = (num(dr) - abs(num(cr))) if isinstance(dr, (int, float)) or isinstance(cr, (int, float)) else None
        else:
            amount = r[final_col] if final_col < len(r) else None
        if isinstance(code, str):
            # '4800', or a sub-code per director / account ('5400/1', '5400/2'): counted under its main code
            m = re.match(r"^\s*(\d{1,4})(?:\s*[/.\-]\s*\d{1,3})?\s*$", code)
            code = int(m.group(1)) if m else code
        if not isinstance(code, (int, float)) or isinstance(code, bool) or not isinstance(amount, (int, float)):
            continue
        key = str(int(code))
        out[key] = round(out.get(key, 0.0) + float(amount), 2)
    if out and abs(sum(out.values())) >= 1.0:
        # Final balances that do not add up to nil were read from the wrong column, or the paper is an unfinished
        # draft: not used (wrong opening figures are worse than none)
        logger.warning("Last year's WP ETB (%s) does not balance (%.2f): not read", name, sum(out.values()))
        return None
    return (_year_end(rows[:6]), out) if out else None


def open_queries(rows: List[List]) -> List[Dict[str, str]]:
    """Last year's Notes & Queries points still waiting on the client, carried forward as open queries: each numbered
    point ('1 | Stock | Please note ... Kindly provide the confirmation'), its text
    being the narrative lines down to the next number; kept when the text asks for something (kindly, please confirm /
    provide / advise ...). [{'no', 'area', 'text'}]."""
    points: List[Dict[str, str]] = []
    for r in rows:
        cells = [c for c in r if c not in (None, "")]
        if not cells:
            continue
        first = cells[0]
        # A point's number (1, 2, 10.1), not an amount in one of its tables (19649.99)
        number = ((isinstance(first, (int, float)) and not isinstance(first, bool) and 0 < first < 100
                   and POINT_NUMBER.match(f"{first:g}"))
                  or (isinstance(first, str) and POINT_NUMBER.match(first.strip())))
        texts = [c.strip() for c in cells[1 if number else 0:] if isinstance(c, str) and c.strip()]
        if number and texts:
            points.append({"no": str(first).strip(), "area": texts[0][:60],
                           "lines": [t for t in texts[1:] if len(t) >= NARRATIVE_MIN]})
        elif points and texts:
            points[-1]["lines"] += [t for t in texts if len(t) >= NARRATIVE_MIN]
    out = []
    for p in points:
        text = " ".join(p["lines"])
        if text and OPEN_POINT.search(text):
            out.append({"no": p["no"], "area": p["area"], "text": text[:500]})
    return out


# Last year's tax computation (H1): the trading losses it carried forward ('Losses C/fwd', 'Total losses c/f',
# 'Taxable loss c/fwd'), this year's losses brought forward (CTA 2010 s45)
LOSSES_CF = re.compile(r"\b(total\s+)?(taxable\s+|trading\s+)?loss(es)?\s+(c\s*/\s*f(wd)?|carried\s+forward)\b", re.I)


def tax_carried_forward(wb) -> Dict[str, float]:
    """{'losses_cf': amount} from last year's H1 tab, when it states one, and {'wdv_cf': amount}: last year's tax
    written-down value of the assets (the capital allowance pools carried forward, CAA 2001 s59), when its deferred
    tax working states it as one figure."""
    out: Dict[str, float] = {}
    tab = next((n for n in wb.sheetnames if n.strip().upper().startswith("H1")), None)
    if tab is not None:
        for r in wb[tab].iter_rows(max_row=200, values_only=True):
            cells = list(r)
            at = next((i for i, v in enumerate(cells) if isinstance(v, str) and LOSSES_CF.search(v)), None)
            if at is None:
                continue
            amount = next((float(v) for v in cells[at + 1:] if isinstance(v, (int, float)) and not isinstance(v, bool)), None)
            if amount is not None and abs(amount) >= 1:
                out["losses_cf"] = round(abs(amount), 2)
                break
    wdv = tax_wdv_carried_forward(wb)
    if wdv is not None:
        out["wdv_cf"] = wdv
    loans = loans_carried_forward(wb)
    if loans:
        out["loans_cf"] = loans
    return out


# Each lender's closing balance on last year's loan tabs, to pre-fill this year's G4.n loan tabs: the lender's own tab
# ('G4.2-LLOYDS-BBL-8582', or LedgerMind's own 'G4.1 - 23111 - HP 1 - BL24 GME'), or one column
# block per agreement on a summary ('Hire Purchase': each agreement's name over its 'Closing balance'). A lead's
# 'Balance C/Fwd' total is not one lender's: a tab whose name has no lender in it and whose closing row holds one
# figure is left out
LOAN_TAB = re.compile(r"\bloans?\b|\bhp\b|hire purchase|\bpcp\b|\bbbls?\b|bounce|mortgage|finance|funding|^G4\.", re.I)
# LedgerMind's own lender tab (G4.n): its heading names the loan code
OUR_LOAN_TAB = re.compile(r"^\s*(50[01]\d|5[15][0-2]\d|535\d)\b")
NOT_LOAN_TAB = re.compile(r"\bNL\b|transaction|interest|director|\bDLA\b|\bDCA\b|staff|<|>|less than|more than|"
                          r"\byrs?\b|years?\b", re.I)
CLOSING_LABEL = re.compile(r"^\s*(closing balance|balance\s*c\s*/\s*f(wd)?|c\s*/\s*fwd)\b", re.I)
BLOCK_LABEL = re.compile(r"^\s*(details?|debit|credit|balance|loan|repayments?|interest|insur|adjust|move|dispos|"
                         r"closing|opening|total|date|difference|less than|more than|check|ttb|movement|£|owed|"
                         r"per |split|due|adjusting|suggested|dispo|period|client|year ended|insurance)", re.I)


LOAN_WORD = re.compile(r"loan|\bhp\b|hire|\bpcp\b|finance|agreement|mortgage|\bbbls?\b|bounce|lease|funding", re.I)
KIND_WORDS = {"pcp", "bbl", "bbls", "mortgage", "mortgages", "funding"}


def _tab_lender(name: str) -> str:
    """The tab's name without its reference ('G4.2-LLOYDS-BBL-8582' -> 'LLOYDS-BBL-8582')."""
    return re.sub(r"^\s*[A-Z]{1,2}\d+(?:[.\-]\d+)*\s*[-:]?\s*", "", name).strip()


def loans_carried_forward(wb) -> Dict[str, float]:
    """{lender as last year's paper names it: amount owed at last year's end} (settled ones, nil, left out)."""
    from backend.app.services.loans.agreements import name_words
    out: Dict[str, float] = {}
    for tab in wb.sheetnames:
        if not LOAN_TAB.search(tab) or NOT_LOAN_TAB.search(tab):
            continue
        rows = [list(r) for r in wb[tab].iter_rows(max_row=80, max_col=80, values_only=True)]
        own = _tab_lender(tab)
        loan_tab = bool(LOAN_WORD.search(own))
        if tab.strip().upper().startswith("G4.") and not loan_tab and not (
                len(rows) > 3 and rows[3] and OUR_LOAN_TAB.search(str(rows[3][0] or ""))):
            continue                     # a G4.n tab of another paper's numbering (VAT, PAYE ...)
        lender_like = lambda text: re.search(r"[a-z]{3}", " ".join(name_words(text) - KIND_WORDS))
        single: List[float] = []
        blocks: List[Tuple[str, float]] = []
        for i, r in enumerate(rows):
            spots = []
            for c, v in enumerate(r):
                if isinstance(v, str) and CLOSING_LABEL.search(v):
                    amount = next((float(x) for x in r[c + 1:c + 4]
                                   if isinstance(x, (int, float)) and not isinstance(x, bool)), None)
                    if amount is not None:
                        spots.append((c, amount))
            if len(spots) == 1:
                single.append(spots[0][1])
                continue
            for c, amount in spots:      # several side by side: one column block per agreement
                # The agreement's name: the nearest heading above in the label's column
                head = next((str(rows[k][c]) for k in range(i - 1, -1, -1) if c < len(rows[k])
                             and isinstance(rows[k][c], str) and name_words(rows[k][c]) - KIND_WORDS
                             and not BLOCK_LABEL.search(rows[k][c])), None)
                # A lender's name (not a code's: '5100 Bank loans'), and on a tab named only by its reference ('G4 -
                # Other creditors') one that says it is a loan (not 'VAT', 'PAYE')
                if head and re.search(r"[a-z]{3}", " ".join(name_words(head) - KIND_WORDS)) \
                        and (loan_tab or LOAN_WORD.search(head)):
                    blocks.append((head, amount))
        if blocks:                       # one column block per agreement (the summary's own total left out)
            for head, amount in blocks:
                if abs(amount) >= 1:
                    out[head.strip()[:120]] = round(abs(amount), 2)
        elif single and lender_like(own) and abs(single[0]) >= 1:
            out[own[:120]] = round(abs(single[0]), 2)      # the lender's own tab; a lead's total is no lender's
    return out


# The tax written-down value as one figure in a firm's deferred tax working: 'WDV as per Tax Comp' (deferred tax tab)
# or 'WDV of qualifying assets' (I1-1 Deferred Tax calc, this year's column first). The pool split (main / special) is
# kept in TaxCalc, often only as a screenshot, so only the total is read
WDV_LABEL = re.compile(r"^\s*(wdv as per tax comp(utation)?|wdv of qualifying assets|tax written[\s-]*down value)\b", re.I)
WDV_TAB = re.compile(r"deferred|\bI1\b|^I1|tax", re.I)


def tax_wdv_carried_forward(wb) -> Optional[float]:
    for name in wb.sheetnames:
        if not WDV_TAB.search(name):
            continue
        for r in wb[name].iter_rows(max_row=150, values_only=True):
            cells = list(r)
            at = next((i for i, v in enumerate(cells) if isinstance(v, str) and WDV_LABEL.search(v)), None)
            if at is None:
                continue
            amount = next((float(v) for v in cells[at + 1:] if isinstance(v, (int, float)) and not isinstance(v, bool)),
                          None)
            if amount is not None and amount >= 1:
                return round(amount, 2)
    return None


def cost_code(name: str, tb_names: Iterable[Tuple[int, str]], is_pl) -> Optional[int]:
    """The P&L account an item belongs to: the code in its name, else the client's own trial balance account sharing
    the most words with it (only when one account is best), else the cost its words name."""
    m = CODE_IN_NAME.match(name)
    if m and is_pl(int(m.group(1))):
        return int(m.group(1))
    words = {w for w in re.findall(r"[a-z]{4,}", name.lower())} - COMMON_WORDS
    scores: Dict[int, int] = {}
    for code, tb_name in tb_names:
        if is_pl(code):
            s = len(words & set(re.findall(r"[a-z]{4,}", (tb_name or "").lower())))
            if s:
                scores[code] = max(scores.get(code, 0), s)
    if scores:
        top = max(scores.values())
        best = [c for c, s in scores.items() if s == top]
        if len(best) == 1:
            return best[0]                               # the client's own account (two as good: not guessed)
    for rx, code in COST_WORDS:
        if rx.search(name):
            return code
    return None


# The director's claims last year's paper credited to the director's loan (its B2 journals): use of home ('Being rent
# (WFH) recorded as per previous year'), the director's salary taken through the loan, mileage
DIRECTORS_LOAN = 5400
HOME_WHY = re.compile(r"\b(home|wfh|work(ing)? from home|use of home)\b", re.I)
MILEAGE_WHY = re.compile(r"\bmileage\b", re.I)
SALARY_WHY = re.compile(r"\bsalar(y|ies)\b|\bremuneration\b", re.I)
SALARY_CODES = {3010, 1510, 2510}           # directors' salaries (overheads, cost of sales, distribution)


def journals_of(wb) -> List[Dict]:
    """Every journal on a working paper's B2 tab: {no, lines [(code, debit, credit)], why}."""
    sheet = next((s for s in wb.sheetnames if s.upper().startswith("B2")), None)
    if not sheet:
        return []
    rows = [list(r) for r in wb[sheet].iter_rows(max_row=400, values_only=True)]
    hdr = next((i for i, r in enumerate(rows) if r and any(str(v).strip().lower() == "code" for v in r if v)), None)
    if hdr is None:
        return []
    cols = [str(v).strip().lower() if v else "" for v in rows[hdr]]
    ci = cols.index("code")
    di = next((i for i, c in enumerate(cols) if c.startswith("debit")), None)
    ki = next((i for i, c in enumerate(cols) if c.startswith("credit")), None)
    if di is None or ki is None:
        return []
    out: List[Dict] = []
    cur = None
    for r in rows[hdr + 1:]:
        if not r:
            continue
        if isinstance(r[0], (int, float)) and r[0]:
            cur = {"no": int(r[0]), "lines": [], "why": ""}
            out.append(cur)
        if cur is None:
            continue
        text = " ".join(str(v) for v in r[1:ci] if v)
        try:
            code = int(str(r[ci]).strip()) if ci < len(r) and r[ci] not in (None, "") else None
        except ValueError:
            code = None
        dr = r[di] if di < len(r) and isinstance(r[di], (int, float)) else 0
        cr = r[ki] if ki < len(r) and isinstance(r[ki], (int, float)) else 0
        if code is not None and (dr or cr):
            cur["lines"].append((code, round(float(dr), 2), round(float(cr), 2)))
        elif text.strip().startswith("(") or "being" in text.lower():
            cur["why"] = (cur["why"] + " " + text.strip())[:200]
    return [j for j in out if j["lines"]]


def director_claims(journals: List[Dict]) -> List[Tuple[str, str, float]]:
    """(kind, narrative, amount) for each journal crediting the director's loan with use of home, mileage or the
    director's salary. A dividend, a reclassification or a clearing journal is not a claim."""
    out: List[Tuple[str, str, float]] = []
    for j in journals:
        credit = round(sum(cr - dr for c, dr, cr in j["lines"] if c == DIRECTORS_LOAN), 2)
        if credit < MIN_AMOUNT:
            continue
        codes = {c for c, dr, _ in j["lines"] if dr}
        why = j.get("why") or ""
        if codes & {8010, 8011}:
            continue
        if SALARY_WHY.search(why) or codes & SALARY_CODES:
            kind = "SALARY"
        elif MILEAGE_WHY.search(why):
            kind = "MILEAGE"
        elif HOME_WHY.search(why) or (codes == {3100} and "rent" in why.lower()):
            kind = "HOME"
        else:
            continue
        out.append((kind, why.strip(" ()")[:200], credit))
    return out
