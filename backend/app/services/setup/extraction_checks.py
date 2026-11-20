"""The data extraction checks on the Data check. A blocking check is a WARNING here: the workbook is built as a draft
with the point on its cover until it is cleared or explained. Information checks are OK items with the figures.

C1  last year's filed TB balances                       WARNING when not
C2  only the column dated last year end was read          OK (said when the file had two year columns)
C3  each GL account's lines v its 'Total' line in the file WARNING when not (review/gl_read.py)
C4 GL v TB, per account                                  WARNING
C5  TB type (movement / closing)                          OK; WARNING when too many accounts fit neither
C6  opening v last year's filed TB, per code              WARNING when not explained by a reclass
C7  reclass at opening (same money on another code)       OK, listed
C11 reserves brought forward v last year                  WARNING
C12 the whole P&L the wrong way round (income Dr, costs Cr) WARNING (a TB made as closing less opening)
C13 last year's TB v last year's final working paper's ETB WARNING per balance sheet code
C8 / C9 are the lead sheets' own nil checks (workbook); C10 is the Data check's report items (aged reports, payroll,
VAT returns)."""

from itertools import combinations
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, ClientProfile, GLTransaction, TBRecord
from backend.app.services.setup.data_check import OK, WARNING, CheckItem, first_year, incorporated_in_year

TOLERANCE = 1.0
FIXED_ASSETS = (4000, 4200)   # fixed asset codes: per class x0-x2 cost, x3-x4 depreciation
REVERSED_SHARE = 0.75     # C12: three quarters of income on the debit side and of costs on the credit side
REVERSED_MIN = 1000.0      # ...each at least this much (a dormant or tiny P&L is not judged)
NEITHER_SHARE = 0.10       # TB type test: neither test passes for more than 10% of balance sheet accounts


def _money(v: float) -> str:
    return f"£{abs(v):,.2f}{' Cr' if v < 0 else ''}"


def pl_reversed(tb: List[TBRecord], chart) -> Optional[Tuple[float, float]]:
    """(income on the debit side, costs on the credit side) when most of the P&L is the wrong way round: a TB whose
    P&L lines were made as closing less opening (sales on the debit side) or with Debit and
    Credit swapped. One account the wrong way is the mapping check's (wrong-side balance); this is the whole P&L."""
    from backend.app.services.mapping.mapping_parts.common import INCOME_SECTIONS
    inc_dr = inc_cr = cost_dr = cost_cr = 0.0
    for t in tb:
        if t.std_code is None or not chart.is_pl(t.std_code) or not chart.is_pre_tax_pl(t.std_code):
            continue
        v = float(t.net_amount or 0) - float(t.opening_amount or 0)       # the period's own figure
        if chart.section(t.std_code) in INCOME_SECTIONS:
            inc_dr, inc_cr = inc_dr + max(v, 0), inc_cr + max(-v, 0)
        else:
            cost_dr, cost_cr = cost_dr + max(v, 0), cost_cr + max(-v, 0)
    if inc_dr < REVERSED_MIN or cost_cr < REVERSED_MIN:
        return None
    if inc_dr >= REVERSED_SHARE * (inc_dr + inc_cr) and cost_cr >= REVERSED_SHARE * (cost_dr + cost_cr):
        return round(inc_dr, 2), round(cost_cr, 2)
    return None


def wp_final_balances(profile: Optional[ClientProfile]) -> Dict[str, float]:
    """Last year's final working paper's ETB final balances by firm code, as its upload read them."""
    import json
    try:
        inputs = json.loads(getattr(profile, "tax_inputs", None) or "{}") if profile is not None else {}
    except ValueError:
        return {}
    return (inputs.get("_last_year_wp") or {}).get("etb_final") or {}


def tb_v_final_wp(lines, wp: Dict[str, float], chart) -> List[Tuple[str, float, float]]:
    """[(code, last year's TB, final working paper)] for the balance sheet codes that differ by £1 or more. Reserves
    are left to C11 (the paper's reserves b/f plus its year's profit is the TB's closing reserve) and the P&L closes
    into them."""
    def key(code: str) -> str:
        # A fixed asset class compares as cost and depreciation: the paper keeps the year's additions (x1) and charge
        # (x4) apart, the TB has them in cost and depreciation brought forward
        c = int(code)
        return f"{c // 10 * 10}" if FIXED_ASSETS[0] <= c < FIXED_ASSETS[1] and c % 10 < 3 else \
            f"{c // 10 * 10 + 3}" if FIXED_ASSETS[0] <= c < FIXED_ASSETS[1] else code

    tb: Dict[str, float] = {}
    for l in lines:
        if l.code is not None:
            k = key(str(l.code))
            tb[k] = round(tb.get(k, 0.0) + float(l.amount), 2)
    paper: Dict[str, float] = {}
    for code, v in wp.items():
        if code.isdigit():
            paper[key(code)] = round(paper.get(key(code), 0.0) + float(v), 2)
    diffs = {}
    for code in set(tb) | set(paper):
        if not code.isdigit() or chart.is_pl(int(code)) or 8000 <= int(code) <= 8099:
            continue
        if abs(tb.get(code, 0.0) - paper.get(code, 0.0)) >= TOLERANCE:
            diffs[code] = round(tb.get(code, 0.0) - paper.get(code, 0.0), 2)
    # The same money on another code (a reclass, as C7): not a difference
    moved = {k for g in _reclass_groups(diffs) for k in g}
    out = [(c, tb.get(c, 0.0), paper.get(c, 0.0)) for c in diffs if c not in moved]
    return sorted(out, key=lambda x: -abs(x[1] - x[2]))


def _reclass_groups(diffs: Dict[str, float]) -> List[List[str]]:
    """Codes whose differences net to nil, two or three at a time (the same money on another code)."""
    left = dict(diffs)
    groups: List[List[str]] = []
    for size in (2, 3):
        for combo in combinations(sorted(left, key=lambda k: (-abs(left[k]), k))[:16], size):
            if all(k in left for k in combo) and abs(sum(left[k] for k in combo)) < TOLERANCE:
                groups.append(list(combo))
                for k in combo:
                    left.pop(k)
    return groups


def wp_read_item(db: Session, eng: ClientEngagement, profile: Optional[ClientProfile]) -> Optional[CheckItem]:
    """C14: what LM read from last year's final working paper, so the accountant can see it took the right tab and
    figures (an older firm template shows the mapping found, for the reviewer to confirm once).
    None when no paper was uploaded."""
    import json
    try:
        inputs = json.loads(getattr(profile, "tax_inputs", None) or "{}") if profile is not None else {}
    except ValueError:
        return None
    read = inputs.get("_last_year_wp_read")
    if not read:
        return None
    from backend.app.models.database import FixedAssetRecord
    assets = db.query(FixedAssetRecord).filter(FixedAssetRecord.engagement_id == eng.id).count() if db is not None else 0
    when = read.get("year_end")
    parts = [f"year end {when[8:10]}/{when[5:7]}/{when[:4]}" if when else "no year end found"]
    parts.append(f"final balances from the '{read['etb_tab']}' tab ({read['etb_codes']} codes)" if read.get("etb_tab")
                 else "no ETB final balances found (or they do not add up to nil)")
    many = lambda n, one, more: f"{n} {one if n == 1 else more}"
    parts.append(f"{many(read.get('accruals', 0), 'accrual', 'accruals')} and "
                 f"{many(read.get('prepayments', 0), 'prepayment', 'prepayments')} to reverse")
    if assets:
        parts.append(f"{many(assets, 'asset', 'assets')} in the register")
    if read.get("losses_cf"):
        parts.append(f"tax losses carried forward £{float(read['losses_cf']):,.2f}")
    if read.get("loans"):
        parts.append(many(read["loans"], "lender's balance", "lenders' balances") + " (loans tab)")
    if read.get("claims"):
        parts.append(many(read["claims"], "director claim", "director claims"))
    if read.get("open_queries"):
        parts.append(many(read["open_queries"], "open query", "open queries") + " carried forward")
    if not read.get("used"):
        return CheckItem("c14_wp_read", "Last year's working paper read (C14)", WARNING,
                         "Last year's working paper was uploaded but not used: "
                         + ("its year end is not about a year before this one. " if when else
                            "its year end could not be found. ")
                         + "Found: " + "; ".join(parts) + ". Upload last year's final paper, or check its year end.")
    status = OK if read.get("etb_tab") and when else WARNING
    return CheckItem("c14_wp_read", "Last year's working paper read (C14)", status,
                     "Read from last year's working paper: " + "; ".join(parts) + ". Check these are the right figures; "
                     "the opening balances still come from last year's filed TB.")


def extraction_items(db: Session, eng: ClientEngagement, tb: List[TBRecord],
                     profile: Optional[ClientProfile]) -> List[CheckItem]:
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.review import last_year as ly
    from backend.app.services.review.extraction import ledger_tie
    from backend.app.services.review.gl_read import gl_read_check
    items: List[CheckItem] = []
    chart = ChartLookup(db)

    def label(code: str) -> str:
        return f"{code} {chart.name(int(code), '') if code.isdigit() else ''}".strip()

    # C1 / C2: last year's filed TB as read
    lines = ly.prior_lines(eng, db) if ly.last_year_job(eng, db) is None else []
    if lines:
        out_by = round(sum(l.amount for l in lines), 2)
        if abs(out_by) >= TOLERANCE:
            items.append(CheckItem("c1_filed_tb", "Last year's TB balances (C1)", WARNING,
                                   f"Last year's TB does not balance: debits and credits differ by {_money(out_by)}. "
                                   f"Check the right column was read (only last year's closing balance).",
                                   "upload_last_year_tb"))
        try:
            frame = ly._prior_frame(eng)
            year = ly._year_column(frame[1].values.tolist()) if frame else None
        except Exception:
            year = None
        if year is not None:
            h, col = year
            when = ly._date_of(frame[1].values.tolist()[h][col])
            items.append(CheckItem("c2_filed_column", "Last year's TB: one year column (C2)", OK,
                                   f"Two year columns found in last year's TB: only {when:%d/%m/%Y} used (the other is "
                                   f"the year before)."))

    # C14: what LM read from last year's working paper (an older firm template shows the mapping found)
    item = wp_read_item(db, eng, profile)
    if item is not None:
        items.append(item)

    # C13: last year's TB as uploaded against last year's final working paper (its ETB final balances)
    if lines:
        wp = wp_final_balances(profile)
        gaps = tb_v_final_wp(lines, wp, chart) if wp else []
        if gaps:
            items.append(CheckItem("c13_wp_final", "Last year's TB v last year's final working paper (C13)", WARNING,
                                   f"Last year's TB differs from last year's final working paper on {len(gaps)} "
                                   f"balance sheet account(s): "
                                   + "; ".join(f"{label(k)} TB {_money(t)} v working paper {_money(w)}"
                                               for k, t, w in gaps[:6])
                                   + (f" and {len(gaps) - 6} more" if len(gaps) > 6 else "")
                                   + ". The TB decides the opening balances: explain each difference "
                                     "(a change after the paper was finished), or upload the TB the accounts were filed "
                                     "on if this one is from before last year's adjustments.", "upload_last_year_tb"))
        elif wp:
            items.append(CheckItem("c13_wp_final", "Last year's TB v last year's final working paper (C13)", OK,
                                   "Last year's TB agrees to last year's final working paper on every balance sheet "
                                   "account."))

    # C3: each GL account's lines against its total line in the file (also when no line was read at all)
    try:
        read = gl_read_check(eng, db)
    except Exception:
        read = None
    if read is not None:
        checked, missed = read
        if missed:
            items.append(CheckItem("c3_gl_read", "General ledger read in full (C3)", WARNING,
                                   "; ".join(f"GL for {a} did not read fully: lines read {_money(r)}, its Total line "
                                             f"{_money(t)}" for a, r, t in missed[:6])
                                   + (f" and {len(missed) - 6} more" if len(missed) > 6 else "")
                                   + ". Check the GL file (a line in an unusual layout) and upload it again.",
                                   "upload_gl"))
        else:
            items.append(CheckItem("c3_gl_read", "General ledger read in full (C3)", OK,
                                   f"All {checked} GL accounts read in full: each agrees to its Total line."))

    # C12: the whole P&L the wrong way round (income on the debit side, costs on the credit side)
    reversed_pl = pl_reversed(tb, chart)
    if reversed_pl:
        items.append(CheckItem("c12_tb_signs", "Trial balance signs (C12)", WARNING,
                               f"The P&L reads the wrong way round: {_money(reversed_pl[0])} of income is on the debit "
                               f"side and {_money(reversed_pl[1])} of costs on the credit side. Was the P&L worked out "
                               f"as this year's closing less last year's? The P&L starts from nil each year, so its "
                               f"movement is the period's own figures. Upload the closing TB for the period (or the "
                               f"TB with Debit and Credit as the accounting software gives them).", "reupload_tb"))

    gl_lines = db.execute(select(func.count(GLTransaction.id)).where(GLTransaction.engagement_id == eng.id)).scalar() or 0
    if not gl_lines:
        return items
    tie = ledger_tie(eng, tb, db)

    # C5: the TB type
    told = sum(tie.votes.values())
    neither = tie.votes.get("neither", 0)
    kind = "a closing (as of) TB" if tie.kind == "closing" else "a TB of the year's movements"
    if told and neither / told > NEITHER_SHARE and neither >= 2:
        items.append(CheckItem("c5_tb_type", "Trial balance type (C5)", WARNING,
                               f"Read as {kind}, but {neither} of {told} balance sheet accounts fit neither a movement "
                               f"nor a closing TB against the ledger: a wrong TB date or part of the ledger missing. "
                               f"Upload a TB 'for the period' or the full general ledger.", "reupload_tb"))
    else:
        items.append(CheckItem("c5_tb_type", "Trial balance type (C5)", OK,
                               f"The TB is {kind}" + (f" ({max(tie.votes['movement'], tie.votes['closing'])} of {told} "
                                                      f"balance sheet accounts agree)" if told else "")
                               + ": opening from last year's accounts, movement from the general ledger, the TB as the "
                                 "check."))

    # C4: the ledger against the TB, account by account
    gaps = sorted(((k, v) for k, v in tie.not_in_gl.items() if abs(v) >= TOLERANCE), key=lambda kv: (-abs(kv[1]), kv[0]))
    if gaps:
        items.append(CheckItem("c4_gl_tb", "General ledger v trial balance (C4)", WARNING,
                               f"The GL and the TB differ on {len(gaps)} account(s): "
                               + "; ".join(f"{label(k)} {_money(v)}" for k, v in gaps[:6])
                               + (f" and {len(gaps) - 6} more" if len(gaps) > 6 else "")
                               + ". Missing GL transactions or a wrong TB date (B1-ETB column S); the workbook stays a "
                                 "draft until each is explained.", "upload_gl"))
    else:
        items.append(CheckItem("c4_gl_tb", "General ledger v trial balance (C4)", OK,
                               "Every account's TB balance is its opening plus the ledger's movement."))

    # C6 / C7 / C11: the opening against last year's filed TB
    if not tie.filed:
        if not (first_year(profile) or incorporated_in_year(eng, profile)):
            items.append(CheckItem("c6_opening", "Opening v last year's accounts (C6)", WARNING,
                                   "No last year's filed TB (or last year's job): the opening is worked out as the TB "
                                   "less the ledger's movement and cannot be checked. Upload last year's filed TB.",
                                   "upload_last_year_tb"))
        return items
    diffs = {k: v for k, v in tie.adjust.items() if abs(v) >= TOLERANCE and k != "8000"}
    groups = _reclass_groups(diffs)
    grouped = {k for g in groups for k in g}
    if groups:
        said = []
        for g in groups:
            down = [k for k in g if diffs[k] < 0]
            up = [k for k in g if diffs[k] > 0]
            # Books higher than last year's figure on one code, lower on another: the money moved from the second
            said.append(f"{_money(sum(abs(diffs[k]) for k in up))} was on {', '.join(label(k) for k in down)} last "
                        f"year and is on {', '.join(label(k) for k in up)} now")
        items.append(CheckItem("c7_reclass", "Reclass at opening (C7)", OK,
                               "; ".join(said) + ". A reclass, not a difference: confirm this year's codes (last "
                                                 "year's comparatives follow them)."))
    rest = sorted(((k, v) for k, v in diffs.items() if k not in grouped), key=lambda kv: (-abs(kv[1]), kv[0]))
    if rest:
        items.append(CheckItem("c6_opening", "Opening v last year's accounts (C6)", WARNING,
                               f"The opening differs from last year's filed accounts on {len(rest)} account(s): "
                               + "; ".join(f"{label(k)} books {_money(tie.opening.get(k, 0.0))} v filed "
                                           f"{_money(tie.filed.get(k, 0.0))}" for k, v in rest[:6])
                               + ". Last year's journals not posted in the books, or a balance to explain (B1-ETB "
                                 "opening adjustment; journal on the Opening balances point)."))
    else:
        items.append(CheckItem("c6_opening", "Opening v last year's accounts (C6)", OK,
                               f"Every balance opens at last year's filed figure ({tie.source})."))
    books_bf, filed_bf = tie.opening.get("8000", 0.0), tie.filed.get("8000", 0.0)
    if abs(books_bf - filed_bf) >= TOLERANCE:
        items.append(CheckItem("c11_reserves", "Reserves brought forward (C11)", WARNING,
                               f"Reserves brought forward are {_money(books_bf)} in the books but {_money(filed_bf)} in "
                               f"last year's accounts (with last year's profit and dividends): {_money(books_bf - filed_bf)} "
                               f"to explain."))
    else:
        items.append(CheckItem("c11_reserves", "Reserves brought forward (C11)", OK,
                               f"Reserves brought forward agree to last year's accounts ({_money(filed_bf)})."))
    return items
