"""One list of a job's queries: everything the app asks about the job, from the
Data check (round 1: files missing or unreadable), the Books tab's client questions and the review points (round 2),
each put to the person who answers it:

- CLIENT: only the client can answer (a missing report, an unknown bank line, a confirmation)
- ACCOUNTANT: a judgement or an approval (a dividend, corporation tax not final, capitalise or not)
- INTERNAL: the preparer fixes it in the app; never sent to the client

Who answers and whether a query blocks the job follow the firm's query rules (rule IDs below). The checks stay
where they are; this only gathers what they found. Rules that no other check raises are in r1_rules (their queries
are only here).
What the person did (sent, answered, cleared) is kept in job_queries by the query's key, so it survives every re-run;
a review point cleared here is cleared on the Review tab too, and a bank question answered here is answered on the
Books tab, so both screens always agree."""

import copy
import logging
import re
import threading
from collections import OrderedDict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement
from backend.app.models.queries import JobQuery

logger = logging.getLogger(__name__)

CLIENT, ACCOUNTANT, INTERNAL = "CLIENT", "ACCOUNTANT", "INTERNAL"
AUDIENCES = (CLIENT, ACCOUNTANT, INTERNAL)
# Open or done (answered, cleared). No "sent": the email goes from the firm's own mail, so the app cannot know it
# went, and a status nobody sets is worse than none
OPEN, ANSWERED, CLEARED = "OPEN", "ANSWERED", "CLEARED"
STATUSES = (OPEN, ANSWERED, CLEARED)

# Data check: who answers, by the item's action (rules C-01..C-10: the client sends bank statements, payroll and
# VAT returns; the accountant decides whether the GL, last year's TB, the asset register or aged lists are needed)
DATA_AUDIENCE = {
    "upload_payroll": CLIENT, "enter_vat": CLIENT, "confirm_vat": CLIENT, "enter_bank": CLIENT,
    "reupload_bank": CLIENT, "loan_statement": CLIENT, "add_properties": CLIENT,
    "upload_gl": ACCOUNTANT, "upload_last_year_tb": ACCOUNTANT, "first_year": ACCOUNTANT, "upload_far": ACCOUNTANT,
    "upload_aged": ACCOUNTANT,
    "reupload_tb": INTERNAL,
}
# Data check items that stop the job even as a warning (blocking rules: C-02 GL, C-03 opening balances, C-04
# bank statements, C-07 payroll, C-08 VAT returns, TB-02 loan statements); a Data check "must fix" always does
DATA_BLOCKING = ("tb", "gl", "openings", "payroll", "vat", "bank:", "statement:", "loan:")
# What the client is asked for, item by item (the same words as the Data check's client email)
DATA_ASK = {
    "upload_last_year_tb": "Last year's closing trial balance (or last year's accounts), for the opening balances.",
    "reupload_tb": "The trial balance again: the one we have does not balance.",
    "upload_gl": "The general ledger (nominal ledger detail) for the year, as an Excel export.",
    "upload_far": "The fixed asset register: each asset with its cost, date bought and depreciation.",
    "upload_payroll": "The payroll summary for the year (gross pay, tax, NI and pension per month), the P32 (amounts "
                      "paid to HMRC), the pension contribution schedule and the year-end P60s.",
    "enter_vat": "The VAT returns filed for the year (and any return still unpaid at the start of the year), and a "
                 "screenshot of the VAT account in your HMRC online account.",
    "confirm_vat": "Whether the company is VAT registered: if it is, the VAT number and the VAT returns filed for "
                   "the year.",
    "loan_statement": "The year-end statement for each loan or mortgage (the balance owed at the year end and the "
                      "interest charged in the year).",
    "add_properties": "A list of the company's properties: for each, the address, whether it is held to rent out or "
                      "to sell (or being developed to sell), and the completion statement for any bought or sold in "
                      "the year.",
    "upload_aged": "The aged debtors and aged creditors reports at the year end.",
    "enter_bank": "The bank statements showing the balance at the year end, for each account.",
    "reupload_bank": "The full bank statements for the year (every month, with the running balance), as issued by "
                     "the bank.",
}

# Review points the client answers: payroll reports and differences (PY-02..07), payments to people the
# payroll does not name (PY-08), closing stock (YE-03), asset invoices and disposals (TB-04, TB-06), missing VAT
# returns (VT-03), old debts (AR-02), large or round-sum payments (GL-01, GL-02), use of home (SQ-02), suspense
# balances (TB-07), a cost that may be an asset (TB-04: its invoice)
REVIEW_CLIENT = ("U-PAY-001", "U-PAY-006", "U-PAY-008", "U-PAY-009", "U-SUB-", "U-STK-003", "CT-CA-001", "G1",
                 "CT-CA-002", "V-F01", "U-DEB-002", "G9", "U-ADJ-004", "U-LOAN-004", "U-LOAN-005", "U-TB-003")
# Review points the preparer fixes in the app (rules TB-10, TB-16, GL-05, GL-06: the TB, the client's setup,
# duplicates found in the books)
REVIEW_INTERNAL = ("U-TB-001", "U-TB-005", "U-TB-006", "G5", "RP-00", "UNMAPPED")
# Review points that stop the job until answered (blocking rules: DL-01 overdrawn loan, DL-02 dividends,
# PY-08 people paid outside the payroll, YE-03 closing stock, TB-07 suspense)
REVIEW_BLOCKING = ("U-DIV-001", "U-DLA-001", "U-SUB-003", "U-STK-003", "U-TB-003")
CT_HELD = "Corporation tax not proposed yet"     # U-CT-003 while the bank job's suspense is over the firm's limit


def _starts(ref: str, prefixes) -> bool:
    return any(ref == p or (p.endswith("-") and ref.startswith(p)) or ref.startswith(p + "-") for p in prefixes)


def _starts_key(key: str, keys) -> bool:
    return any(key.startswith(k) if k.endswith(":") else key == k for k in keys)


def _review_audience(ref: str) -> str:
    if _starts(ref, REVIEW_INTERNAL):
        return INTERNAL
    if _starts(ref, REVIEW_CLIENT):
        return CLIENT
    return ACCOUNTANT


def _norm(text: str) -> str:
    """A review point's words without its figures, so the same point keeps its key when an amount changes."""
    return re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()[:80]


def _query(key: str, source: str, round_: int, audience: str, title: str, detail: str = "", amount: float = 0.0,
           blocking: bool = False, go_to: str = "", items: Optional[List[Dict[str, Any]]] = None,
           done: bool = False) -> Dict[str, Any]:
    return {"key": key, "source": source, "round": round_, "audience": audience, "title": title, "detail": detail,
            "amount": round(float(amount or 0), 2), "blocking": blocking, "go_to": go_to, "items": items or [],
            "done": done}


def _from_data_check(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    from backend.app.services.setup.data_check import data_check, STOP, OK
    out = []
    for item in data_check(db, eng)["items"]:
        if item["status"] == OK:
            continue
        action = item["action"] or ""
        audience = DATA_AUDIENCE.get(action, INTERNAL)
        detail = item["detail"]
        if audience == CLIENT and action in DATA_ASK:
            detail = f"{DATA_ASK[action]}\n\n{detail}"
        out.append(_query(f"data:{item['key']}", "data", 1, audience, item["label"], detail,
                          blocking=item["status"] == STOP or _starts_key(item["key"], DATA_BLOCKING),
                          go_to="data"))
    return out


def _from_books(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    """The Books tab's client questions. The unknown bank lines are put as two queries, each with its schedule of
    lines (rules BK-01, BK-02: one query for the money in we cannot identify, one for the money out); every other
    question is a query of its own. A file question (invoice numbers used twice) is round 1, the rest round 2."""
    from backend.app.services.bank_only import books as raw_books
    if not raw_books.is_books_client(eng):
        return []
    try:
        worked = raw_books.books(eng, db)
    except Exception:
        return []
    questions = worked["questions"]
    money_in, money_out, bills, out = [], [], [], []
    for q in questions:
        key, text = q["key"], q["text"]
        item = {"key": key, "text": text, "answer": q.get("answer", ""), "answered": bool(q.get("answered"))}
        lone = key.startswith(("bank:", "payee:")) and q["group"] == "explain" and "completion statement" not in text
        if lone:
            (money_in if " paid in " in text or "receipts from" in text else money_out).append(item)
            continue
        if key.startswith("bill:"):
            bills.append(item)
            continue
        blocking = key.startswith("transfer:") or "completion statement" in text     # BK-08, BK-11
        round_ = 1 if key.startswith("file:") else 2
        out.append(_query(f"books:{key}", "books", round_, CLIENT, _headline(text), text, blocking=blocking,
                          go_to="books", items=[item], done=item["answered"]))
    for name, lines, word, ask in (
            ("money_in", money_in, "Money in we cannot identify", "Please tell us what each of these was for."),
            ("money_out", money_out, "Money out we cannot identify", "Please tell us what each of these was for."),
            ("bills", bills, "Bills we cannot match to a payment",
             "Please tell us what each of these bills was for and how it was paid.")):
        if lines:
            out.insert(0, _query(f"books:{name}", "books", 2, CLIENT,
                                 f"{word}: {len(lines)} line{'s' if len(lines) != 1 else ''}", ask, go_to="books",
                                 items=lines, done=all(i["answered"] for i in lines)))
    return out + worked.get("rule_queries", [])


def _headline(text: str) -> str:
    """A bank question's title: its first sentence, short."""
    first = re.split(r"(?<=[.?])\s", text, maxsplit=1)[0]
    return first if len(first) <= 110 else first[:107].rsplit(" ", 1)[0] + "…"


# The words a review point keeps for the client: after the marker its check writes ('Client question: ...'), and what
# to send ('Evidence: ...'); the rest of the point (our working and steps) stays on its card, not in the query
_CLIENT_MARK = re.compile(r"(?:Query to the client|Client question|Question to the client|Client query|Question)\s*:\s*", re.I)
_EVIDENCE_MARK = re.compile(r"(?:Evidence needed|Evidence required|Evidence)\s*:\s*", re.I)
_REF = re.compile(r"\s*Ref:.*$")


def client_words(details: str) -> str:
    """A review point's question to the client and the documents to send, without the accountant's working; empty
    when the point has no question for the client (its title says what it is)."""
    ask, send = [], []
    for line in (details or "").splitlines():
        line = line.strip()
        q = _CLIENT_MARK.search(line)
        e = _EVIDENCE_MARK.match(line)
        if q:
            ask.append(_REF.sub("", line[q.end():]).strip())
        elif e:
            what = _REF.sub("", line[e.end():]).strip().rstrip(".")
            if what and what not in ("-",):
                send.append(f"Please send: {what}.")
    return " ".join(a for a in ask + send if a)


def _from_review(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    findings = list(db.execute(select(AuditFinding).where(AuditFinding.engagement_id == eng.id)
                               .order_by(AuditFinding.id)).scalars())
    out, seen = [], {}
    for f in findings:
        ref = f.procedure_ref or ""
        base = f"review:{ref}:{_norm(f.source_row_ref or '') or _norm(f.finding_title or '')}"
        seen[base] = seen.get(base, 0) + 1
        key = base if seen[base] == 1 else f"{base}:{seen[base]}"
        blocking = _starts(ref, REVIEW_BLOCKING) or (ref == "U-CT-003" and f.finding_title.startswith(CT_HELD))
        # A point the gate downgraded (a figure it could not fill) is the preparer's note, never a client query
        audience = INTERNAL if (f.finding_title or "").startswith("Internal note: ") else _review_audience(ref)
        # The client's words only (the email is made from these); the whole point is on its card (Open the point)
        q = _query(key, "review", 2, audience, f.finding_title or "", client_words(f.finding_details or ""),
                   float(f.quantified_amount or 0), blocking=blocking, go_to="review",
                   done=f.status != "OPEN")
        q["finding_id"], q["severity"], q["ref"] = f.id, f.severity, ref
        out.append(q)
    return out


def _from_scrutiny(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    """Questions asked about single ledger lines on the GL scrutiny screen (Accounts tab), one query per line."""
    from backend.app.models.gl_line_reviews import GLLineReview
    rows = db.execute(select(GLLineReview).where(GLLineReview.engagement_id == str(eng.id),
                                                 GLLineReview.question.isnot(None))
                      .order_by(GLLineReview.asked_at, GLLineReview.id)).scalars()
    out = []
    for r in rows:
        out.append(_query(f"gl:{r.line_key}", "gl", 2, CLIENT, r.line_label or "Ledger line", r.question,
                          abs(float(r.amount or 0)), go_to="accounts"))
    return out


def _from_raised(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    """Queries raised by hand on an area page; read on every call (not kept with the worked-out ones), so a new one
    shows at once."""
    from backend.app.models.point_signoffs import point_key
    from backend.app.models.queries import RaisedQuery
    rows = list(db.execute(select(RaisedQuery).where(RaisedQuery.engagement_id == str(eng.id))
                           .order_by(RaisedQuery.id)).scalars())
    if not rows:
        return []
    points = {point_key(f.procedure_ref, f.finding_title, f.source_row_ref): f.id
              for f in db.execute(select(AuditFinding).where(AuditFinding.engagement_id == eng.id)).scalars()}
    out = []
    for r in rows:
        q = _query(f"raised:{r.id}", "raised", 2, r.audience or CLIENT, r.title, r.detail or "",
                   float(r.amount or 0))
        q["ref"], q["area"], q["raised_id"] = r.ref or "", r.area or "", r.id
        if r.point_key and r.point_key in points:
            q["finding_id"] = points[r.point_key]
        out.append(q)
    return out


def raise_query(db: Session, eng: ClientEngagement, user_id: Optional[int], title: str, detail: str = "",
                audience: str = CLIENT, area: str = "", amount: float = 0.0,
                finding_id: Optional[int] = None) -> None:
    """A query raised by hand on an area page, on the account or on one of its points."""
    from backend.app.models.point_signoffs import point_key
    from backend.app.models.queries import RaisedQuery
    title = (title or "").strip()
    if not title:
        raise ValueError("Write the question")
    if audience not in AUDIENCES:
        raise ValueError("Unknown audience")
    ref, key = None, None
    if finding_id:
        f = db.get(AuditFinding, int(finding_id))
        if f is None or str(f.engagement_id) != str(eng.id):
            raise ValueError("Point not found")
        ref, key = f.procedure_ref, point_key(f.procedure_ref, f.finding_title, f.source_row_ref)
    db.add(RaisedQuery(engagement_id=str(eng.id), area=(area or None), audience=audience, title=title[:300],
                       detail=(detail or "").strip() or None, amount=round(float(amount or 0), 2) or None,
                       ref=ref, point_key=key, user_id=user_id))
    db.commit()


def remove_raised(db: Session, eng: ClientEngagement, raised_id: int) -> None:
    from backend.app.models.queries import RaisedQuery
    row = db.get(RaisedQuery, raised_id)
    if row is None or row.engagement_id != str(eng.id):
        raise ValueError("Query not found")
    saved = _saved(db, str(eng.id)).get(f"raised:{raised_id}")
    if saved is not None:
        db.delete(saved)
    db.delete(row)
    db.commit()


def _saved(db: Session, engagement_id: str) -> Dict[str, JobQuery]:
    return {r.key: r for r in db.execute(select(JobQuery).where(JobQuery.engagement_id == engagement_id)).scalars()}


# The queries worked out for a job, kept while nothing they are worked out from has changed (working them out reads
# the client's files and runs the Data check, the books, the tax computation and every rule: seconds per job). What
# the person did to each query (job_queries) is not part of it: it is added on every call.
_KEPT_JOBS = 100
_kept: "OrderedDict[str, Tuple[str, List[Dict[str, Any]]]]" = OrderedDict()
_kept_lock = threading.Lock()


def _job_tables():
    """(model, columns) of every table a job's queries are worked out from: all columns of the small ones; the
    count and the last id of the large ones (their rows are replaced, not edited, apart from the TB's codes)."""
    from backend.app.models.database import (
        ClientProfile, FixedAssetRecord, GLTransaction, PayrollP32Record, ProposedJournal, SupplementaryDocument,
        TBRecord, VAT100Record,
    )
    from backend.app.models.director_pay import PayrollDirectorPay
    from backend.app.models.gl_openings import GLOpeningBalance
    from backend.app.models.loan_agreements import LoanAgreement
    from backend.app.models.payroll_allowance import PayrollAllowance
    from backend.app.models.payroll_headcount import PayrollHeadcount
    from backend.app.models.raw_books import RawBooksChoice
    from backend.app.models.reconciliation_inputs import ReconciliationInput
    from backend.app.models.vat_payments import VatReturnPayment
    from backend.app.models.yearend_adjustments import YearEndAdjustment
    from backend.app.models.gl_line_reviews import GLLineReview
    small = [ClientProfile, AuditFinding, ProposedJournal, PayrollDirectorPay, GLOpeningBalance, LoanAgreement,
             PayrollAllowance, PayrollHeadcount, RawBooksChoice, ReconciliationInput, VatReturnPayment,
             YearEndAdjustment, VAT100Record, FixedAssetRecord, SupplementaryDocument, GLLineReview]
    large = [GLTransaction, PayrollP32Record]
    return small, large, TBRecord


def _fingerprint(db: Session, eng: ClientEngagement) -> str:
    """Everything the job's queries are worked out from, in a few quick reads: the job, its rows, its uploaded
    files, last year's job, the firm's settings and rules, and today's date."""
    from sqlalchemy import func
    from backend.app.core.s3 import s3_service
    from backend.app.models.database import FirmMappingRule, MasterCOA
    from backend.app.models.firm_settings import FirmSetting
    from backend.app.services.shared.file_cache import digest
    from backend.app.services.review.last_year import last_year_job

    small, large, tb = _job_tables()
    job = str(eng.id)
    parts: List[Any] = [date.today(), [getattr(eng, c.name) for c in ClientEngagement.__table__.columns]]
    for model in small:
        parts.append(db.execute(select(model.__table__).where(model.engagement_id == job)
                                .order_by(*model.__table__.primary_key.columns)).all())
    for model in large:
        parts.append(db.execute(select(func.count(), func.max(model.id)).where(model.engagement_id == job)).all())
    parts.append(db.execute(select(tb.id, tb.std_code, tb.mapping_status, tb.net_amount)
                            .where(tb.engagement_id == job).order_by(tb.id)).all())
    parts.append(db.execute(select(FirmSetting.key, FirmSetting.value).order_by(FirmSetting.key)).all())
    parts.append(db.execute(select(FirmMappingRule.__table__).order_by(FirmMappingRule.id)).all())
    parts.append(db.execute(select(func.count(), func.max(MasterCOA.std_code))).all())
    last = last_year_job(eng, db)
    if last is not None:
        parts.append((last.id, last.data_changed_at, last.review_run_at,
                      db.execute(select(func.count(), func.max(tb.id)).where(tb.engagement_id == last.id)).all()))
    parts.append(s3_service.signature(f"raw_uploads/{job}/"))
    return digest(*parts)


def _safe(failed: List[str], name: str, fn, *args) -> List[Dict[str, Any]]:
    """One source of queries: a check that fails is logged with its stack trace and left out, so the other checks'
    queries still show (one failing check never breaks the whole queries page)."""
    db = args[0]
    try:
        return fn(*args)
    except Exception:
        logger.exception("Queries: %s failed for engagement %s", name, getattr(args[1], "id", "?"))
        db.rollback()
        failed.append(name)
        return []


def _work_out(db: Session, eng: ClientEngagement) -> List[Dict[str, Any]]:
    """The job's queries from every check, before what the person did to them."""
    failed: List[str] = []
    data = _safe(failed, "the Data check", _from_data_check, db, eng)
    review = _safe(failed, "the review points", _from_review, db, eng)
    if any(q["key"] == "data:vat" for q in data):
        # The VAT review's "no VAT returns entered" is the Data check's VAT returns query again
        review = [q for q in review if not (q["ref"] == "V-F01" and q["title"].startswith("No VAT returns"))]
    books = _safe(failed, "the Books tab questions", _from_books, db, eng)
    asked = {q["key"] for q in books}
    if "books:standard:use_of_home" in asked:
        # The review's "use of home not claimed" is the standard client question about it
        review = [q for q in review if q["ref"] != "U-ADJ-004"]
    if asked & {"books:money_in", "books:money_out", "books:bills"}:
        # On a bank job the suspense balance is the unknown bank lines and bills, already asked line by line
        review = [q for q in review if q["ref"] != "U-TB-003"]
    from backend.app.services.queries.r1_rules import r1_queries
    rules = _safe(failed, "the query rules", r1_queries, db, eng)
    if any(q["ref"] == "U-PAY-006" for q in review):
        # The review already asks about net wages owed at the year end
        rules = [q for q in rules if q["ref"] != "PY-04"]
    if any(q["key"].startswith("data:loan:") for q in data):
        # A bank job's Data check already asks for each loan's statement
        rules = [q for q in rules if q["ref"] != "TB-02"]
    # The Data check already asks for last year's TB and the VAT returns; the review for the stock (U-STK-003)
    if any(q["key"].startswith("data:openings") for q in data):
        rules = [q for q in rules if q["ref"] != "C-03"]
    if any(q["key"].startswith("data:vat") for q in data):
        rules = [q for q in rules if q["ref"] != "C-08"]
    if any(q["ref"] == "U-STK-003" for q in review):
        rules = [q for q in rules if q["ref"] != "YE-03"]
    if any(q["ref"] == "U-EQ-001" for q in review):
        # The review's dividends-over-reserves point already asks for the vouchers and minutes
        rules = [q for q in rules if q["ref"] != "DL-02"]
    from backend.app.services.queries.industry_requests import industry_requests
    industry = _safe(failed, "the industry document requests", industry_requests, db, eng)
    out = data + books + review + rules + industry + _safe(failed, "the GL scrutiny questions", _from_scrutiny, db, eng)
    if failed:
        out.append(_query("internal:checks-failed", "rules", 1, INTERNAL, "Some checks could not make their queries",
                          f"{', '.join(failed).capitalize()} could not run on this job, so their queries are missing "
                          f"here. The error is in the server log; tell the developer."))
    # No question goes out with a template blank in it ('[x]'), whichever check raised it
    from backend.app.services.queries.placeholders import BLANK, fill
    for q in out:
        q["title"] = fill(q.get("title")) or BLANK.sub("…", q.get("title") or "")
        q["detail"] = fill(q.get("detail"))
    return out


def query_list(db: Session, eng: ClientEngagement) -> Dict[str, Any]:
    """Every query of the job, with what was done to it, blocking ones first; and the counts per audience."""
    print_ = _fingerprint(db, eng)
    with _kept_lock:
        kept = _kept.get(str(eng.id))
    if kept and kept[0] == print_:
        queries = copy.deepcopy(kept[1])
    else:
        queries = _work_out(db, eng)
        with _kept_lock:
            _kept[str(eng.id)] = (print_, copy.deepcopy(queries))
            _kept.move_to_end(str(eng.id))
            while len(_kept) > _KEPT_JOBS:
                _kept.popitem(last=False)
    queries += _from_raised(db, eng)
    saved = _saved(db, str(eng.id))
    for q in queries:
        row = saved.get(q["key"])
        status = row.status if row and row.status in STATUSES else OPEN     # a stored "SENT" row counts as open
        # A review point cleared on the Review tab, or every bank line answered on the Books tab, is done here too
        if q["done"] and status == OPEN:
            status = ANSWERED if q["source"] == "books" else CLEARED
        if q["source"] == "review" and not q["done"] and status == CLEARED:
            status = OPEN          # cleared here, then the review ran again and raised it again
        q.update(status=status, answer=(row.answer if row else "") or "",
                 audience=(row.audience if row and row.audience else q["audience"]),
                 answered_at=row.answered_at.isoformat() if row and row.answered_at else None)
        q.pop("done")
    order = {OPEN: 0, ANSWERED: 1, CLEARED: 2}
    queries.sort(key=lambda q: (order[q["status"]], not q["blocking"], q["round"]))
    counts = {a: {"open": sum(1 for q in queries if q["audience"] == a and q["status"] == OPEN),
                  "blocking": sum(1 for q in queries if q["audience"] == a and q["blocking"]
                                  and q["status"] == OPEN),
                  "total": sum(1 for q in queries if q["audience"] == a)} for a in AUDIENCES}
    return {"queries": queries, "counts": counts,
            "open": sum(c["open"] for c in counts.values()), "blocking": sum(c["blocking"] for c in counts.values())}


def update_query(db: Session, eng: ClientEngagement, key: str, user_id: Optional[int], status: Optional[str] = None,
                 answer: Optional[str] = None, audience: Optional[str] = None,
                 item_answers: Optional[Dict[str, str]] = None) -> None:
    """Save what the person did to one query. A bank line's answer is saved on the Books tab as well (the same
    'answer:' choice it has there), and a review point cleared here is cleared on the Review tab."""
    if status is not None and status not in STATUSES:
        raise ValueError("Unknown status")
    if audience is not None and audience not in AUDIENCES:
        raise ValueError("Unknown audience")
    row = _saved(db, str(eng.id)).get(key)
    if row is None:
        row = JobQuery(engagement_id=str(eng.id), key=key, status=OPEN)
        db.add(row)
    now = datetime.utcnow()
    if answer is not None:
        row.answer = answer.strip() or None
        if row.answer and status is None and row.status not in (ANSWERED, CLEARED):
            status = ANSWERED
    if status is not None:
        row.status = status
        if status == ANSWERED:
            row.answered_at = now
    if audience is not None:
        row.audience = audience
    row.user_id = user_id

    if item_answers and key.startswith("books:"):
        from backend.app.services.bank_only import books as raw_books
        for item_key, text in item_answers.items():
            text = (text or "").strip()
            raw_books.save_choice(db, str(eng.id), f"answer:{item_key}", {"text": text} if text else None, user_id)
    if status == CLEARED and key.startswith("review:"):
        _clear_review_point(db, eng, key, row.answer)
    db.commit()


def _clear_review_point(db: Session, eng: ClientEngagement, key: str, note: Optional[str]) -> None:
    for q in _from_review(db, eng):
        if q["key"] == key:
            f = db.get(AuditFinding, q["finding_id"])
            if f is not None and f.status == "OPEN":
                f.status, f.cleared_at = "CLEARED", datetime.utcnow()
                f.cleared_note = note or "Cleared on the Queries tab"
            return
