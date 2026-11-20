"""
Data check: is everything the working papers need in the client's files, and was it read? Rules only (the same files
always give the same answer); the app fills in what the files hold (openings from the ledger or last year's TB) and
never makes up a figure.

STOP     the workbook is not built: a figure cannot be right (TB out of balance, a balance sheet with no opening
         balances, a file uploaded and read as nothing)
WARNING  the workbook is built as a draft, the point listed on its cover (a report missing or not agreeing)
OK       nothing to do

hard_stops() is light (the build gate asks it on every status call); data_check() adds the warnings, which read the
control accounts.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.database import (
    ClientEngagement, ClientProfile, GLTransaction, PayrollP32Record, SupplementaryDocument, TBRecord, VAT100Record,
)

from backend.app.services.mapping.chart_lookup import NET_WAGES, PAYE_NIC

logger = logging.getLogger(__name__)

OK, WARNING, STOP = "OK", "WARNING", "STOP"
SHARE_CAPITAL_CODES = (7000, 7999)  # share capital and premium: they do not move in a normal year
RESERVES_CODE = 8000               # profit and loss brought forward
RESERVES_NAME = re.compile(r"retained (earnings|profits?)|profit and loss (account|reserve|b/?f)|p ?& ?l (reserve|b/?f)|"
                           r"reserves? b/?f|retained profit balance", re.I)
FIXED_ASSET_CODES = (4000, 4199)
PAYROLL_FAR_OFF = (0.55, 1.8)      # payroll report v gross wages in the books: outside this, the report is questioned


@dataclass
class CheckItem:
    key: str
    label: str
    status: str            # OK / WARNING / STOP
    detail: str            # what is right or wrong, in plain words, with the figures
    action: str = ""       # what to do: upload_last_year_tb, first_year, reupload_tb, upload_gl, upload_far,
                           # upload_payroll, enter_vat, upload_aged, enter_bank, confirm_vat, loan_statement, add_properties (the Data check tab's buttons)


def _setup(profile: Optional[ClientProfile]) -> Dict[str, Any]:
    try:
        return json.loads(profile.setup or "{}") if profile is not None and profile.setup else {}
    except ValueError:
        return {}


def first_year(profile: Optional[ClientProfile]) -> bool:
    """The accountant ticked 'first year of trading': there are no opening balances to bring in."""
    return bool((_setup(profile).get("data") or {}).get("first_year"))


def incorporated_in_year(eng: ClientEngagement, profile: Optional[ClientProfile]) -> Optional[str]:
    """The incorporation date from Companies House when the company was formed during this year (its first year:
    nothing to bring forward), else None."""
    try:
        register = json.loads(profile.companies_house or "{}") if profile is not None and profile.companies_house else {}
        formed = date.fromisoformat(register["incorporated"]) if register.get("incorporated") else None
    except (ValueError, TypeError):
        return None
    ped = eng.period_end_date
    if formed is None or ped is None:
        return None
    start = (eng.prior_period_end_date + timedelta(days=1)) if eng.prior_period_end_date else ped - timedelta(days=365)
    return formed.isoformat() if formed >= start - timedelta(days=31) else None


def _roles(engagement_id: str) -> Dict[str, str]:
    """What each uploaded file was taken as (saved beside the files at upload)."""
    from backend.app.core.s3 import s3_service
    try:
        data = s3_service.download_file_bytes(f"raw_uploads/{engagement_id}/_roles.json")
        return json.loads(data.decode()) if data else {}
    except Exception:
        return {}


def _opening_balances(eng: ClientEngagement, tb: List[TBRecord], profile: Optional[ClientProfile]) -> CheckItem:
    """A balance sheet needs last year's closing balances. Found (from the ledger's opening lines or last year's TB),
    or not needed (the TB holds closing balances: it still shows the share capital, which does not move in a year),
    or missing. With no share capital in the TB (a company limited by guarantee, or books that never recorded it) the
    reserves stand in, unless last year's TB shows share capital: then the TB is of this year's movements, and its
    reserves are only last year's dividends closed into them."""
    from backend.app.services.review.last_year import SHARE_CAPITAL_NAME, prior_shows_share_capital, prior_uploaded
    label = "Opening balances"
    opened = [t for t in tb if t.opening_amount is not None and abs(float(t.opening_amount or 0)) >= 0.005]
    if opened:
        return CheckItem("openings", label, OK, f"Brought in for {len(opened)} account(s) (from the ledger's opening "
                                                f"lines or last year's TB).")
    shown = lambda t: abs(float(t.net_amount or 0)) >= 1
    share_capital = [t for t in tb if shown(t) and (
        (t.std_code is not None and SHARE_CAPITAL_CODES[0] <= t.std_code <= SHARE_CAPITAL_CODES[1])
        or SHARE_CAPITAL_NAME.search(t.raw_account_name or ""))]
    if share_capital:
        return CheckItem("openings", label, OK, "The trial balance holds closing balances (it shows the share "
                                                "capital), so last year's balances are already in it.")
    reserves = [t for t in tb if shown(t) and (t.std_code == RESERVES_CODE or RESERVES_NAME.search(t.raw_account_name or ""))]
    if reserves and not prior_shows_share_capital(eng):
        return CheckItem("openings", label, OK, "The trial balance holds closing balances (it shows the reserves "
                                                "brought forward), so last year's balances are already in it.")
    if first_year(profile):
        return CheckItem("openings", label, OK, "First year of trading: no opening balances.", "first_year")
    formed = incorporated_in_year(eng, profile)
    if formed:
        return CheckItem("openings", label, OK, f"Incorporated on {formed} (Companies House): the first year, so there "
                                                f"are no opening balances.")
    if prior_uploaded(eng):
        return CheckItem("openings", label, STOP,
                         "The trial balance holds only this year's movements, and last year's TB was uploaded but its "
                         "balances could not be used. Check that it is last year's closing TB, that its debits equal "
                         "its credits, and that it has a heading row: Code, Account, Debit, Credit. Then upload it "
                         "again.", "upload_last_year_tb")
    return CheckItem("openings", label, STOP,
                     "The trial balance holds only this year's movements (it shows no share capital, or last year's "
                     "TB shows share capital this one leaves out) and no opening balances were found in the ledger or "
                     "last year's TB, so debtors, creditors, bank, loans and fixed assets would show only this year's "
                     "change. Upload last year's closing TB, or tick 'first year of trading'.", "upload_last_year_tb")


def _books_openings(db: Session, eng: ClientEngagement, tb: List[TBRecord], profile: Optional[ClientProfile]) -> CheckItem:
    """A Bank + Dext / bank-only client's books open with last year's closing TB (uploaded with the statements) or
    last year's job in the app. A company that traded last year with neither would start at nil: bank, loans, the
    director's loan, share capital and reserves all wrong, so it stops the work."""
    from backend.app.services.review.last_year import last_year_job
    label = "Opening balances"
    opened = [t for t in tb if t.opening_amount is not None and abs(float(t.opening_amount or 0)) >= 0.005]
    if opened:
        return CheckItem("openings", label, OK, f"Brought in for {len(opened)} account(s) from last year's closing TB.")
    if last_year_job(eng, db) is not None:
        return CheckItem("openings", label, OK, "Last year's job in the app gives the opening balances.")
    if first_year(profile):
        return CheckItem("openings", label, OK, "First year of trading: no opening balances.", "first_year")
    formed = incorporated_in_year(eng, profile)
    if formed:
        return CheckItem("openings", label, OK, f"Incorporated on {formed} (Companies House): the first year, so there "
                                                f"are no opening balances.")
    if "OPENING_TB" in _roles(str(eng.id)).values():
        return CheckItem("openings", label, STOP, "Last year's closing TB was uploaded but no balance could be read from "
                                                  "it. Check it has a heading row (Code or Account, Debit, Credit) and "
                                                  "upload it again.", "upload_last_year_tb")
    return CheckItem("openings", label, STOP, "No closing trial balance for last year, so the bank, loans, the "
                                              "director's loan, share capital and reserves would all start at nil. "
                                              "Upload last year's closing TB (codes or account names, with debit and "
                                              "credit), or tick 'first year of trading'.", "upload_last_year_tb")


def hard_stops(db: Session, eng: ClientEngagement, tb_records: Optional[List[TBRecord]] = None) -> List[CheckItem]:
    """The STOP items only, from the database and the saved upload roles (cheap enough for the build gate)."""
    from backend.app.services.bank_only.books import is_books_client
    from backend.app.services.setup.profile_service import ProfileService
    if tb_records is None:
        tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == eng.id)).scalars())
    if not tb_records:
        return []
    out = [item for item in _core_items(db, eng, tb_records, ProfileService.get_or_create_profile(db, eng.id),
                                        is_books_client(eng)) if item.status == STOP]
    return out


def _core_items(db: Session, eng: ClientEngagement, tb: List[TBRecord], profile: Optional[ClientProfile],
                books_client: bool) -> List[CheckItem]:
    items: List[CheckItem] = []
    net = round(sum(float(t.net_amount or 0) for t in tb), 2)
    if abs(net) >= 1:
        items.append(CheckItem("tb", "Trial balance", STOP,
                               f"Debits and credits differ by £{net:,.2f}. Check the TB file (a missing or duplicated "
                               f"line, or a total read as an account) and upload it again.", "reupload_tb"))
    else:
        items.append(CheckItem("tb", "Trial balance", OK, f"{len(tb)} accounts; debits equal credits."))

    if books_client:
        items.append(_books_openings(db, eng, tb, profile))
    if not books_client:            # a Bank + Dext / bank-only client's TB is built from last year's closing TB
        items.append(_opening_balances(eng, tb, profile))

        gl_lines = db.execute(select(func.count(GLTransaction.id)).where(GLTransaction.engagement_id == eng.id)).scalar() or 0
        gl_uploaded = not gl_lines and "GL" in _roles(str(eng.id)).values()
        if gl_lines:
            items.append(CheckItem("gl", "General ledger", OK, f"{gl_lines:,} ledger lines read."))
        elif gl_uploaded:
            items.append(CheckItem("gl", "General ledger", STOP,
                                   "A general ledger was uploaded but no lines could be read from it, so the review "
                                   "checks, VAT payments and opening balances from it are missing. Upload it again and "
                                   "confirm which column is the date, account, debit and credit.", "upload_gl"))
        else:
            items.append(CheckItem("gl", "General ledger", WARNING,
                                   "No general ledger uploaded: the review cannot look at the transactions and the "
                                   "HMRC payments on the VAT account cannot be seen.", "upload_gl"))

    fars = list(db.execute(select(SupplementaryDocument).where(
        SupplementaryDocument.engagement_id == eng.id,
        SupplementaryDocument.doc_type.in_(("FIXED_ASSET_REGISTER", "FIXED_ASSET_REGISTER_EMPTY")))).scalars())
    fa_balance = sum(abs(float(t.net_amount or 0)) for t in tb
                     if t.std_code is not None and FIXED_ASSET_CODES[0] <= t.std_code <= FIXED_ASSET_CODES[1])
    blank = [d for d in fars if d.doc_type == "FIXED_ASSET_REGISTER_EMPTY"]
    if blank and not any(d.parsed_records_count for d in fars):
        # A blank template: not a reading problem
        if fa_balance >= 1:
            items.append(CheckItem("far", "Fixed asset register", STOP,
                                   f"The asset register uploaded ({blank[-1].filename}) is an empty template: its headings "
                                   f"are there but every figure is nil, while the books hold fixed assets of "
                                   f"£{fa_balance:,.2f}. Upload the filled-in register.", "upload_far"))
        else:
            items.append(CheckItem("far", "Fixed asset register", OK,
                                   "The asset register uploaded is an empty template, and the books hold no fixed "
                                   "assets either."))
    elif fars and not any(d.parsed_records_count for d in fars):
        items.append(CheckItem("far", "Fixed asset register", STOP,
                               "A fixed asset register was uploaded but no assets could be read from it, so "
                               "depreciation and capital allowances would be wrong. Upload it again in the firm's "
                               "register layout (one row per asset: cost, depreciation, rate).", "upload_far"))
    elif fars:
        items.append(CheckItem("far", "Fixed asset register", OK,
                               f"{max(d.parsed_records_count or 0 for d in fars)} assets read."))
    elif fa_balance >= 1:
        items.append(CheckItem("far", "Fixed asset register", WARNING,
                               f"Fixed asset accounts hold £{fa_balance:,.2f} but no asset register was uploaded: "
                               f"depreciation is worked from the TB only.", "upload_far"))
    return items


def data_check(db: Session, eng: ClientEngagement) -> Dict[str, Any]:
    """Every item, for the Data check tab and the data-check API: {ready, stops, warnings, items}."""
    from backend.app.services.bank_only.books import is_books_client
    from backend.app.services.setup.profile_service import ProfileService
    tb = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == eng.id)).scalars())
    profile = ProfileService.get_or_create_profile(db, eng.id)
    books_client = is_books_client(eng)
    items = _core_items(db, eng, tb, profile, books_client) if tb else [
        CheckItem("tb", "Trial balance", STOP, "No trial balance has been uploaded.", "reupload_tb")]
    if tb:
        items += _report_items(db, eng, tb, profile, books_client)
    if tb and not books_client:
        # The extraction checks (C1-C11): opening from last year's filed TB, movement from the GL, the TB as check
        try:
            from backend.app.services.setup.extraction_checks import extraction_items
            items += extraction_items(db, eng, tb, profile)
        except Exception:
            logger.exception("Extraction checks not run")
    if books_client:
        raw = _read_client_files(eng)
        if raw is not None:
            items += _statement_items(raw) + _vat_signs(db, eng, profile, raw)
        items += _properties(profile)
    stops = [i for i in items if i.status == STOP]
    warnings = [i for i in items if i.status == WARNING]
    return {"ready": not stops, "stops": len(stops), "warnings": len(warnings),
            "first_year": first_year(profile), "items": [asdict(i) for i in items]}


def _properties(profile: Optional[ClientProfile]) -> List[CheckItem]:
    """A property company on the bank route: each property must be set up as rental (a fixed asset) or trading (stock)
    before a sale or purchase in the bank can be put anywhere (else money from buyers is read as sales)."""
    from backend.app.services.setup.profile_service import confirmed_industry
    if confirmed_industry(profile) != "PRP":
        return []
    try:
        props = json.loads(profile.properties or "[]")
    except (TypeError, ValueError):
        props = []
    if props:
        return [CheckItem("properties", "Properties", OK, f"{len(props)} propert{'y' if len(props) == 1 else 'ies'} set up.")]
    return [CheckItem("properties", "Properties", WARNING,
                      "A property company with no properties set up: a large amount in or out of the bank cannot be "
                      "put to turnover, stock or fixed assets until each property is held to rent out or to sell. "
                      "Add them on the client setup.", "add_properties")]


def _read_client_files(eng: ClientEngagement):
    """A Bank + Dext client's files as read for the books (None when they cannot be read)."""
    from backend.app.services.bank_only.books import client_files
    from backend.app.services.bank_only.input_files import read_input_files
    try:
        files, roles = client_files(str(eng.id))
        return read_input_files(files, roles, year_end=eng.period_end_date)
    except Exception:
        logger.exception("Bank statements not read for the data check")
        return None


def _statement_items(raw) -> List[CheckItem]:
    """A Bank + Dext client's bank statements whose own figures do not hold together (a balance that does not follow
    on, a month or the opening balance missing): uploaded anyway, shown here to look at, one item per account."""
    by_account: Dict[str, List[str]] = {}
    for p in raw.problems:
        if p.where == "Bank" and p.severity == "HIGH" and not p.blocks_upload:
            account, _, text = p.text.partition(": ") if len(raw.accounts) > 1 else ("", "", p.text)
            by_account.setdefault(account, []).append((text or p.text).rstrip("."))
    items = []
    for account, texts in by_account.items():
        shown = "; ".join(texts[:4]) + (f"; and {len(texts) - 4} more" if len(texts) > 4 else "")
        items.append(CheckItem(f"statement:{account or 'bank'}", f"Bank statement figures{': ' + account if account else ''}",
                               WARNING, f"{shown[0].upper()}{shown[1:]}. Check against the bank's own statement (a "
                               f"line left out, typed wrong or in the wrong order, a month or the opening balance "
                               f"missing) and upload it again if needed.",
                               "reupload_bank"))
    return items


HMRC_VAT = re.compile(r"\bhmrc\b.*\bvat\b|\bvat\b.*\bhmrc\b", re.I)
VAT_ACCOUNTS = (5300, 5700)          # the firm's VAT creditor accounts (short and long term)


def _vat_signs(db: Session, eng: ClientEngagement, profile: Optional[ClientProfile], raw) -> List[CheckItem]:
    """A Bank + Dext client's books have no VAT lines to tell from, so the setup's 'not VAT registered' is
    checked against what the files show: a VAT balance in last year's TB, payments to or from HMRC for VAT, sales
    invoices charging VAT, or VAT returns uploaded. Any of them while the setup says No is a question; VAT on
    suppliers' bills is not (an unregistered business pays VAT too)."""
    if profile is None or profile.is_vat_registered:
        return []
    signs = []
    owed = round(sum(v for k, v in raw.opening_tb.items() if k in VAT_ACCOUNTS), 2)
    if abs(owed) >= 1:
        signs.append(f"last year's TB has a VAT balance of £{abs(owed):,.2f}")
    hmrc = [b for b in raw.bank if HMRC_VAT.search(b.description or "")]
    if hmrc:
        signs.append(f"{len(hmrc)} bank line(s) to or from HMRC for VAT (£{sum(abs(b.money_in - b.money_out) for b in hmrc):,.2f}, "
                     f"e.g. \"{hmrc[0].description[:60]}\")")
    charged = [i for i in raw.sales if abs(i.vat) >= 0.01]
    if charged:
        signs.append(f"{len(charged)} of {len(raw.sales)} sales invoice(s) charge VAT (£{sum(i.vat for i in charged):,.2f})")
    returns = db.execute(select(func.count(VAT100Record.id)).where(VAT100Record.engagement_id == eng.id)).scalar() or 0
    if returns:
        signs.append(f"{returns} VAT return(s) uploaded")
    if not signs:
        return []
    return [CheckItem("vat_registered", "VAT registration", WARNING,
                      f"The setup says the client is not VAT registered, but {'; '.join(signs)}. A registered client's "
                      f"sales and costs would be taken gross and its VAT account left out. Check the VAT registration "
                      f"(client setup, VAT) and, if registered, enter the VAT returns.", "confirm_vat")]


def _loan_statements(db: Session, eng: ClientEngagement, tb: List[TBRecord]) -> List[CheckItem]:
    """A Bank + Dext client repaying a loan with no loans register: the lender's year-end statement is asked
    for (its balance, typed on the Balance sheet tab, gives the year's interest), one item per loan still to agree."""
    from backend.app.services.reconciliation.control_accounts import entered_inputs
    from backend.app.services.review.loan_statements import loan_codes
    register = db.execute(select(func.count(SupplementaryDocument.id)).where(
        SupplementaryDocument.engagement_id == eng.id, SupplementaryDocument.doc_type == "LOANS_REGISTER")).scalar()
    if register:
        return []
    inputs = entered_inputs(db, eng.id)
    items = []
    for code, name in sorted(loan_codes(tb).items()):
        repaid = round(sum(float(t.net_amount or 0) - float(t.opening_amount or 0) for t in tb if t.std_code == code), 2)
        if repaid < 1:
            continue
        typed = inputs.get(f"code:{code}") or {}
        if typed.get("balance") is not None or typed.get("agreed"):
            items.append(CheckItem(f"loan:{code}", f"Loan statement: {name}", OK,
                                   f"Repayments of £{repaid:,.2f}; the statement balance is entered."))
            continue
        items.append(CheckItem(f"loan:{code}", f"Loan statement: {name}", WARNING,
                               f"Repayments of £{repaid:,.2f} in the year, but no lender's statement: the interest "
                               f"in them cannot be split out, so the loan is overstated as repaid and interest is "
                               f"nil. Ask for the lender's year-end statement and type its balance on the Balance "
                               f"sheet tab against this loan.", "loan_statement"))
    return items


def _report_items(db: Session, eng: ClientEngagement, tb: List[TBRecord], profile: ClientProfile,
                  books_client: bool) -> List[CheckItem]:
    """The reports the control accounts are checked against: payroll, VAT returns, aged lists, bank statements."""
    from backend.app.services.mapping.chart_lookup import ChartLookup
    from backend.app.services.reconciliation import control_accounts as recs
    items: List[CheckItem] = []
    chart = ChartLookup(db)

    wages = sum(float(t.net_amount or 0) for t in tb if chart.is_gross_wages(t.std_code))
    # Only the report's pay periods inside the year (as the review); a report for another year is said so
    from backend.app.services.review.paye_check import _year as payroll_year
    year_start, year_end = payroll_year(eng)
    from backend.app.services.review.payroll_period import off_period
    uploaded = list(db.execute(select(PayrollP32Record).where(PayrollP32Record.engagement_id == eng.id)).scalars())
    off = off_period(eng, uploaded)
    payroll = [] if off else [r for r in uploaded if r.period_end is None or year_start <= r.period_end <= year_end]
    gross = sum(float(r.gross_pay or 0) for r in payroll)
    payroll_files = list(db.execute(select(SupplementaryDocument).where(
        SupplementaryDocument.engagement_id == eng.id,
        SupplementaryDocument.doc_type.in_(("PAYROLL_P32", "PAYROLL_FROM_GL")))).scalars())
    from_gl = [d for d in payroll_files if d.doc_type == "PAYROLL_FROM_GL"]
    if uploaded and off:
        items.append(CheckItem("payroll", "Payroll report", WARNING,
                               f"{off}: its pay is left out and no payroll journal is proposed from it. Upload the "
                               f"payroll report for this year.", "upload_payroll"))
    elif not payroll and from_gl:
        items.append(CheckItem("payroll", "Payroll report", WARNING,
                               f"{from_gl[-1].filename} was built from the ledger's wage accounts, not a payroll report: "
                               f"it can only agree to the books, and it has no PAYE, NI or net pay, so the payroll "
                               f"cannot be checked. Upload the payroll report (BrightPay, Xero, Sage or the payroll "
                               f"summary).", "upload_payroll"))
    elif not payroll and payroll_files:
        items.append(CheckItem("payroll", "Payroll report", WARNING,
                               f"A payroll file was uploaded ({payroll_files[-1].filename}) but no pay could be read from "
                               f"it, so PAYE, NI and pension cannot be checked. Upload it as a row per month (gross, tax, "
                               f"NI, pension, net pay) or the payroll software's report.", "upload_payroll"))
    elif payroll and wages >= 1:
        ratio = gross / wages
        if PAYROLL_FAR_OFF[0] <= ratio <= PAYROLL_FAR_OFF[1]:
            items.append(CheckItem("payroll", "Payroll report", OK,
                                   f"Gross pay £{gross:,.2f} per the report, £{wages:,.2f} in the books."))
        else:
            items.append(CheckItem("payroll", "Payroll report", WARNING,
                                   f"Gross pay per the report (£{gross:,.2f}) is {ratio:.1f} times the wages in the "
                                   f"books (£{wages:,.2f}): check the report was read right (a total counted twice, a "
                                   f"part of the year) or the wages accounts' codes.", "upload_payroll"))
    elif payroll:
        items.append(CheckItem("payroll", "Payroll report", OK, f"Gross pay £{gross:,.2f} per the report."))
    elif wages >= 1:
        items.append(CheckItem("payroll", "Payroll report", WARNING,
                               f"Wages of £{wages:,.2f} in the books but no payroll report uploaded: PAYE, NI and "
                               f"pension cannot be checked.", "upload_payroll"))
    elif books_client:
        # A Bank + Dext client's books have the pay going out (net wages, PAYE to HMRC) but no wage costs
        # until the payroll report is posted
        paid = {c: sum(float(t.net_amount or 0) - float(t.opening_amount or 0) for t in tb if t.std_code == c)
                for c in (NET_WAGES, PAYE_NIC)}
        shown = [f"£{v:,.2f} {'net pay' if c == NET_WAGES else 'PAYE and NI'}" for c, v in paid.items() if v >= 1]
        if shown:
            items.append(CheckItem("payroll", "Payroll report", WARNING,
                                   f"The bank shows {' and '.join(shown)} paid in the year, but no payroll report was "
                                   f"uploaded, so the wages are only estimated from what was paid. Upload the payroll "
                                   f"summary (P32 / RTI) for the year.", "upload_payroll"))

    if books_client:
        items += _loan_statements(db, eng, tb)

    returns = db.execute(select(func.count(VAT100Record.id)).where(VAT100Record.engagement_id == eng.id)).scalar() or 0
    vat_files = list(db.execute(select(SupplementaryDocument).where(
        SupplementaryDocument.engagement_id == eng.id, SupplementaryDocument.doc_type == "VAT_100")).scalars())
    if vat_files and not returns:
        # A VAT file was uploaded but nothing came out of it: said, not left as a silent nil
        items.append(CheckItem("vat", "VAT returns", WARNING,
                               f"A VAT file was uploaded ({vat_files[-1].filename}) but no returns could be read from "
                               f"it, so the VAT account cannot be agreed. Upload it as a row per return (period, "
                               f"output VAT, input VAT, due, paid) or type the returns on the VAT tab.", "enter_vat"))
    elif profile is not None and profile.is_vat_registered:
        items.append(CheckItem("vat", "VAT returns", OK, f"{returns} return(s) entered.") if returns else
                     CheckItem("vat", "VAT returns", WARNING,
                               "The client is VAT registered but no VAT returns are entered: the VAT account cannot "
                               "be agreed.", "enter_vat"))

    if books_client:
        return items
    try:
        rows = recs.reconciliations(eng, db)
    except Exception:
        logger.exception("Control accounts not worked out for the data check")
        rows = []
    for r in rows:
        if r.key in ("ar", "ap"):
            what = "Aged debtors" if r.key == "ar" else "Aged creditors"
            if r.status == recs.NEEDS_INPUT:
                items.append(CheckItem(r.key, what, WARNING, f"No aged list read: the books show £{r.books:,.2f}.",
                                       "upload_aged"))
            elif r.status == recs.DIFFERENCE:
                items.append(CheckItem(r.key, what, WARNING,
                                       f"The aged list totals £{r.other:,.2f}, the books £{r.books:,.2f} (difference "
                                       f"£{r.difference:,.2f}).", "upload_aged"))
            else:
                items.append(CheckItem(r.key, what, OK, f"Agrees to the books (£{r.books:,.2f})."))
        elif r.key.startswith("bank:") and r.status == recs.NEEDS_INPUT:
            items.append(CheckItem(r.key, f"Bank statement: {r.account}", WARNING,
                                   f"No year-end statement balance entered (books £{r.books:,.2f}).", "enter_bank"))
        elif r.key.startswith("bank:"):
            items.append(CheckItem(r.key, f"Bank statement: {r.account}",
                                   OK if r.status == recs.MATCHED else WARNING,
                                   f"Statement £{r.other:,.2f}, books £{r.books:,.2f}" +
                                   ("." if r.status == recs.MATCHED else f" (difference £{r.difference:,.2f})."),
                                   "" if r.status == recs.MATCHED else "enter_bank"))
    return items
