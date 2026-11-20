"""The control accounts screen's rows: each bank, the CIS accounts, last year's balances, every balance sheet account
to agree by hand, the notes on journals still waiting, and the rows of a bank-only client."""

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, TBRecord
from backend.app.services.workbook.balance_tabs import BANK_CODES
from backend.app.services.mapping.chart_lookup import ChartLookup
from backend.app.services.reconciliation.common import CAPITAL, CATEGORY_SECTION, CURRENT, DIFFERENCE, FIXED, LastYear, NIL, ROW_CODES, ROW_SECTION, Reconciliation, SUPPORT, SUSPENSE_CODE, TRANSFERS_CODE, _in_order, _row, _same_sign, bank_currency, entered_inputs, statement_balance



def _banks(tb_records: List[TBRecord], bal: Dict[int, float], inputs: Dict[str, Dict[str, Any]]) -> List[Reconciliation]:
    rows = []
    codes = [c for c in BANK_CODES if any(t.std_code == c and (abs(float(t.net_amount or 0)) >= 0.005
                                                               or abs(float(t.opening_amount or 0)) >= 0.005) for t in tb_records)
             or abs(bal.get(c, 0.0)) >= 0.005]
    for code in codes:
        names = list(dict.fromkeys(t.raw_account_name for t in tb_records if t.std_code == code)) or [f"Bank {code}"]
        label = " / ".join(names)
        currency, entered = bank_currency(label), inputs.get(f"bank:{code}")
        row = _row(f"bank:{code}", f"{label} ({code})", "Bank", bal.get(code, 0.0), "Bank statement at the year end",
                   statement_balance(entered), "F3",
                   missing=f"Enter the {currency} statement balance and the year-end rate" if currency
                   else "Enter the statement balance at the year end")
        row.currency, row.entered = currency, entered
        if currency and row.status == DIFFERENCE:
            row.note = "A foreign currency account: a difference after the year-end rate is an exchange gain or loss (3562)."
        rows.append(row)
    return rows


def _cis_rows(engagement: ClientEngagement, db: Session) -> List[Reconciliation]:
    """CIS: the books on a cash basis against the CIS300s (deducted) and the EPS claims (suffered), over the
    tax months with an HMRC figure entered; the month-by-month detail is on the CIS checks."""
    from backend.app.services.cis.checks import cis_checks
    profile = getattr(engagement, "profile", None)
    setup_cis = (json.loads(profile.setup or "{}").get("cis") or {}) if profile is not None and profile.setup else {}
    result = cis_checks(engagement, db, setup_cis)
    if not result.get("on"):
        return []
    rows = []
    by_ref = {c["ref"]: c for c in result["checks"]}
    for ref, key, account, compared_with in (("T1", "cis_deducted", "CIS deducted (5321)", "CIS300 returns"),
                                             ("T5", "cis_suffered", "CIS suffered (4421)", "Claimed on the EPS")):
        check = by_ref.get(ref)
        if check is None:
            continue
        entered = [r for r in check["rows"] if r.get("hmrc") is not None]
        books = sum(r["books"] for r in entered) if entered else sum(r["books"] for r in check["rows"])
        row = _row(key, account, "Tax", books, compared_with, sum(r["hmrc"] for r in entered) if entered else None, "CIS",
                   missing="Enter the HMRC CIS figures on the VAT & payroll tab")
        timing = [r for r in entered if r.get("note")]
        if row.status == DIFFERENCE:
            row.note = (f"{check['summary']}." + (f" {len(timing)} month(s) run past the year end (timing)." if timing else "")
                        + " Month by month: CIS checks on the VAT & payroll tab.")
        rows.append(row)
    return rows


def _last_year_balances(engagement: ClientEngagement, db: Session,
                        tb_records: List[TBRecord]) -> Optional[Dict[int, float]]:
    """Each code's balance at last year end: last year's job in the app (its final balances), else the opening
    balances this year's TB carries; None when neither is known."""
    from backend.app.services.review.last_year import last_year_job
    from backend.app.services.tax.ct_computation import final_balances
    try:
        last = last_year_job(engagement, db)
    except Exception:
        last = None
    if last is not None:
        ly_tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == last.id)).scalars())
        if ly_tb:
            return LastYear(final_balances(str(last.id), ly_tb, db), from_job=True)
    if any(t.opening_amount is not None for t in tb_records):
        out: Dict[int, float] = {}
        for t in tb_records:
            if t.std_code is not None:
                out[t.std_code] = out.get(t.std_code, 0.0) + float(t.opening_amount or 0.0)
        return out
    return None


def _account_label(code: int, tb_records: List[TBRecord], chart: ChartLookup) -> str:
    names = list(dict.fromkeys(t.raw_account_name for t in tb_records if t.std_code == code and t.raw_account_name))
    return f"{' / '.join(names[:2]) or chart.name(code, f'Account {code}')} ({code})"


def _lower_first(text: str) -> str:
    """'Accruals schedule' -> 'accruals schedule'; an initialism stays ('HMRC PAYE account statement')."""
    return text if len(text) > 1 and text[1].isupper() else text[:1].lower() + text[1:]


def _by_hand(key: str, account: str, section: str, books: float, compared_with: str, codes: List[int],
             entered: Optional[Dict[str, Any]], tab: str = "", note: str = "") -> Reconciliation:
    """An account agreed to a document the app does not hold: the figure the accountant typed from it, or their tick
    that it agrees; until then it is still to agree."""
    if entered and entered.get("agreed"):
        row = _row(key, account, section, books, compared_with, books, tab)
        row.ticked = True
        row.note = f"Agreed to the {_lower_first(compared_with)} by the accountant" + \
                   (f": {entered['note']}" if entered.get("note") else ".")
    else:
        row = _row(key, account, section, books, compared_with, statement_balance(entered), tab,
                   missing=f"Agree it to the {_lower_first(compared_with)}: type its figure, or tick "
                           f"that it agrees")
        if note:
            row.note = f"{note} {row.note}".strip()
    row.section, row.codes, row.entered = section, codes, entered
    return row


def _balance_sheet_rows(engagement: ClientEngagement, db: Session, bal: Dict[int, float],
                        last: Optional[Dict[int, float]], done: List[Reconciliation], chart: ChartLookup,
                        tb_records: List[TBRecord]) -> List[Reconciliation]:
    """Every balance sheet account the rows above do not cover: fixed assets against the asset register, retained
    earnings against last year's closing reserves, suspense and transfers against nil, and the rest against the
    document they are agreed to (typed or ticked by the accountant)."""
    from backend.app.models.database import FixedAssetRecord
    from backend.app.services.review.setup_checks import ASSET_CLASS_CODES, INTANGIBLE_CLASS_CODES
    from backend.app.services.review.yearend_journals import _far_class
    from backend.app.services.workbook.balance_tabs import DIVIDEND_CODES
    inputs = entered_inputs(db, engagement.id)
    # Last year's job in the app gives its closing reserves; opening balances alone do not hold its profit
    last_from_job = bool(last) and getattr(last, "from_job", False)
    last = last or {}
    covered = {c for r in done for c in r.codes}
    has = lambda c: abs(bal.get(c, 0.0)) >= 0.005 or abs(last.get(c, 0.0)) >= 0.005
    rows: List[Reconciliation] = []

    # Fixed assets: cost and depreciation of each class against the asset register (as U-FAR-002 checks it)
    classes = {**ASSET_CLASS_CODES, **INTANGIBLE_CLASS_CODES}
    far = list(db.execute(select(FixedAssetRecord).where(FixedAssetRecord.engagement_id == engagement.id)).scalars())
    held = {cls: sum(abs(bal.get(c, 0.0)) for c in codes["cost"]) for cls, codes in classes.items()}
    register: Dict[str, Dict[str, float]] = {}
    from backend.app.services.review.yearend_journals import merged_classes
    merged = merged_classes(far, tb_records, bal)
    for a in far:
        cls = _far_class(a.category, held, merged)
        if cls is None:
            continue
        r = register.setdefault(cls, {"cost": 0.0, "dep": 0.0})
        r["cost"] += float(a.cost_fwd or 0) or (float(a.cost_bwd or 0) + float(a.additions or 0) - float(a.disposals or 0))
        r["dep"] += float(a.depr_fwd or 0) or (float(a.depr_bwd or 0) + float(a.depr_charge or 0) - float(a.depr_disposals or 0))
    for cls, codes in classes.items():
        for part, part_codes, sign, what in (("cost", codes["cost"], 1, "cost"), ("dep", codes["acc"], -1, "depreciation")):
            if not any(has(c) for c in part_codes) and cls not in register:
                continue
            covered.update(part_codes)
            books = sum(bal.get(c, 0.0) for c in part_codes)
            key, account = f"far:{cls}:{part}", f"{cls}: {what} ({part_codes[0]}-{max(part_codes)})"
            if far:
                reg = register.get(cls, {}).get(part, 0.0) * sign
                row = _row(key, account, FIXED, books, "Fixed asset register", reg, "B")
                if row.status == DIFFERENCE and part == "dep":
                    row.note = "Until this year's depreciation journal is approved the books hold depreciation brought forward only."
                row.section, row.codes = FIXED, list(part_codes)
            else:
                row = _by_hand(key, account, FIXED, books, "Fixed asset register", list(part_codes), inputs.get(key),
                               "B", note="No fixed asset register uploaded.")
            rows.append(row)

    # Retained earnings brought forward: last year's closing reserves (its reserves plus its profit for the year)
    reserve_codes = sorted(c for c in set(bal) | set(last)
                           if chart.section(c) == "Profit and loss account" and c not in DIVIDEND_CODES)
    if reserve_codes and any(has(c) for c in reserve_codes):
        covered.update(reserve_codes)
        books = sum(bal.get(c, 0.0) for c in reserve_codes)
        if last_from_job:
            closing = sum(v for c, v in last.items() if chart.section(c) == "Profit and loss account" or chart.is_pl(c))
            row = _row("reserves", f"Retained earnings brought forward ({reserve_codes[0]})", CAPITAL, books,
                       "Last year's closing reserves (its reserves plus its profit, less its dividends)", closing, "K")
            row.section, row.codes = CAPITAL, reserve_codes
        else:
            row = _by_hand("reserves", f"Retained earnings brought forward ({reserve_codes[0]})", CAPITAL, books,
                           "Last year's signed accounts: closing reserves", reserve_codes, inputs.get("reserves"), "K")
        rows.append(row)

    # Suspense and the transfers account: nil at the year end
    for code, what in ((SUSPENSE_CODE, "Suspense"), (TRANSFERS_CODE, "Transfers between own accounts")):
        if code in bal or any(t.std_code == code for t in tb_records):
            covered.add(code)
            row = _row(f"code:{code}", f"{what} ({code})", NIL, bal.get(code, 0.0), "Nil at the year end", 0.0, "")
            if row.status == DIFFERENCE:
                row.note = ("Lines the books could not place: find what each is for and post it to its account."
                            if code == SUSPENSE_CODE else
                            "Money moved between the client's accounts with only one side seen: the other account's "
                            "statement is missing, or the amounts or dates do not agree.")
            row.section, row.codes = NIL, [code]
            rows.append(row)

    # The rest, one row per code
    for code in sorted(set(bal) | set(last)):
        if code in covered or code in DIVIDEND_CODES or not has(code) or chart.is_pl(code):
            continue
        section = CATEGORY_SECTION.get(chart.section(code) or "")
        if section is None:
            continue
        account = _account_label(code, tb_records, chart)
        what = next((w for p, w in SUPPORT if p.search(account) or p.search(chart.name(code))), "Supporting document")
        rows.append(_by_hand(f"code:{code}", account, section, bal.get(code, 0.0), what, [code],
                             inputs.get(f"code:{code}"), chart.accounts[code].lead_schedule_ref or ""
                             if code in chart.accounts else ""))
    for r in rows:
        if last and r.codes:
            r.last_year = round(sum(last.get(c, 0.0) for c in r.codes), 2)
    # PAYE and the pension: what the payroll report says, beside the statement's figure
    from backend.app.services.mapping.chart_lookup import PAYE_NIC
    from backend.app.services.review.paye_check import PENSION_PAYABLE, help_note, payroll_figures
    for r in rows:
        for code, kind in ((PAYE_NIC, "paye"), (PENSION_PAYABLE, "pension")):
            if r.codes == [code]:
                try:
                    extra = help_note(payroll_figures(engagement, tb_records, db, kind), kind)
                except Exception:
                    extra = ""
                if extra:
                    r.note = f"{r.note} {extra}".strip()
    return rows


def _journal_notes(rows: List[Reconciliation], engagement: ClientEngagement, db: Session) -> None:
    """A difference that a journal still waiting on the Journals tab would change says so (the books here include
    approved journals only): the tax charge differs from the computation until its journal is approved."""
    from backend.app.models.database import ProposedJournal
    waiting: Dict[int, List[str]] = {}
    for j in db.query(ProposedJournal).filter_by(engagement_id=engagement.id, status="PROPOSED").all():
        codes = {int(l.account_code) for l in j.lines} if j.lines else {int(j.debit_code), int(j.credit_code)}
        for c in codes:
            waiting.setdefault(c, []).append(j.journal_ref)
    for r in rows:
        if r.status != DIFFERENCE:
            continue
        codes = set(r.codes) or ROW_CODES.get(r.key) or ({int(r.key[5:])} if r.key.startswith("bank:") else set())
        refs = sorted({ref for c in codes for ref in waiting.get(c, [])})
        if refs:
            r.note = (f"Journal {', '.join(refs)} on the Journals tab is not approved yet and changes this account: "
                      f"approve it (or reject it) and the difference is worked out again." + (f" {r.note}" if r.note else ""))
        elif r.key == "ct":
            r.note = "Run the review: it proposes the corporation tax journal that brings the charge in the accounts to the computation."


def _books_client_rows(engagement: ClientEngagement, db: Session) -> List[Reconciliation]:
    """A client with no accounting software: the Books tab's checks (bank statements, invoices, bills)."""
    from backend.app.services.bank_only import books as raw_books
    checks = raw_books.books(engagement, db)["checks"]
    rows = [_row(f"bank:{b['code']}", f"{b['account']} ({b['code']})", "Bank", b["books"] or 0.0,
                 "Bank statement at the year end", b["statement"], "F3",
                 missing="No closing balance read from the statement")
            for b in checks.get("banks", [])]
    for key, what, code, books, other, compared_with in (
            ("ar", "Trade debtors", 4400, checks.get("debtors_books"), checks.get("debtors"), "Unpaid sales invoices"),
            ("ap", "Trade creditors", 5200, checks.get("creditors_books"), checks.get("creditors"), "Unpaid bills")):
        if abs(books or 0.0) >= 0.005 or abs(other or 0.0) >= 0.005:
            rows.append(_row(key, f"{what} ({code})", "Balance sheet", books or 0.0, compared_with, other or 0.0,
                             "E2" if key == "ar" else "G2"))
    # Every other balance sheet account of the books the app keeps, as for any client
    raw, _bank, _sales, _bills, ledger, _choices = raw_books.work_out(engagement, db)
    bal = ledger.trial_balance()
    last = {int(c): float(v) for c, v in (raw.opening_tb or {}).items()} or None
    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    for r in rows:
        r.section = ROW_SECTION.get(r.key) or CURRENT
        r.codes = sorted(ROW_CODES.get(r.key) or ({int(r.key[5:])} if r.key.startswith("bank:") else set()))
    rows.extend(_balance_sheet_rows(engagement, db, bal, last, rows, ChartLookup(db), tb_records))
    for r in rows:
        if r.last_year is None and last is not None and r.codes:
            r.last_year = _same_sign(r, bal, sum(last.get(c, 0.0) for c in r.codes))
    return _in_order(rows)
