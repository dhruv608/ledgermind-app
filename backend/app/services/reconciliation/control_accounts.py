"""
The control accounts screen: each control account's balance in the books next to the figure it is agreed to (bank
statement, VAT returns, aged lists, payroll report, tax computation) and the difference, before the workbook is built.
The figures are the ones the workbook's tabs show, worked out here so the screen does not need the Excel; the VAT
position is shared with the workbook (G9 / G9.1) so the two cannot disagree.

Books figures are the final balances: the trial balance plus the journals approved in the app, as on the ETB.

Parts: recon_common (statuses, sections, the row, typed figures, the summary), recon_vat (the VAT position),
recon_rows (bank, CIS, last year, balance sheet rows). This module builds the screen's list and re-exports every name."""

from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.database import ClientEngagement, PayrollP32Record, TBRecord
from backend.app.services.workbook.balance_tabs import S455_CODES
from backend.app.services.mapping.chart_lookup import ChartLookup, VAT_CONTROL
from backend.app.services.reconciliation.common import (CAPITAL, CATEGORY_SECTION, CT_CHARGE, CURRENT, CURRENT_LIAB,
                                               DIFFERENCE, EMPLOYER_NI_CODES, EMPLOYER_PENSION_CODES, FIXED,
                                               LONG_LIAB, LastYear, MATCHED, NEEDS_INPUT, NIL, PL_CHECKS, ROW_CODES,
                                               ROW_SECTION, Reconciliation, SECTIONS, SUPPORT, SUSPENSE_CODE,
                                               TOLERANCE, TRADE_CREDITORS, TRADE_DEBTORS, TRANSFERS_CODE,
                                               VAT_PROOF_KEYS, _in_order, _row, _same_sign, bank_currency,
                                               by_hand_key, entered_inputs, save_input, statement_balance, summary)  # re-exported
from backend.app.services.reconciliation.rows import (_account_label, _balance_sheet_rows, _banks, _books_client_rows,
                                             _by_hand, _cis_rows, _journal_notes, _last_year_balances, _lower_first)  # re-exported
from backend.app.services.reconciliation.vat import (CHARGE_TEXT, CT_TEXT, HMRC_TEXT, JOURNAL_SOURCE, OTHER_TAX_TEXT,
                                            PAID_WITHIN_DAYS, QB_VAT_MEMO, VAT_PAID_TEXT, VAT_WORDS, VatPosition,
                                            other_tax_kind, vat_paid_per_return, vat_position)  # re-exported



def reconciliations(engagement: ClientEngagement, db: Session) -> List[Reconciliation]:
    """Every control account the client has."""
    from backend.app.services.bank_only import books as raw_books
    if raw_books.is_books_client(engagement):
        return _books_client_rows(engagement, db)

    from backend.app.services.ingestion.ageing_reports import read_ageing_reports
    from backend.app.services.tax.ct_computation import ct_computation, final_balances
    from backend.app.services.sop.common import gl_lines

    tb_records = list(db.execute(select(TBRecord).where(TBRecord.engagement_id == engagement.id)).scalars())
    bal = final_balances(str(engagement.id), tb_records, db)
    lines = gl_lines(str(engagement.id), tb_records, db)
    rows = _banks(tb_records, bal, entered_inputs(db, engagement.id))

    # VAT: owed to HMRC (credit) as a positive figure, as on G9
    pos = vat_position(db, engagement, ((l.when, str(l.code), l.description, l.debit - l.credit, l.source) for l in lines))
    vat_books = -bal.get(VAT_CONTROL, 0.0)
    if pos.returns or abs(vat_books) >= 0.005:
        in_year = len(pos.returns) - pos.brought_forward
        # Without the ledger's lines on the VAT account the HMRC payments cannot be seen: no figure, not a difference
        ledger = any(l.code == VAT_CONTROL for l in lines) or (pos.returns and abs(pos.owed_per_returns - vat_books) < TOLERANCE)
        # The books are agreed to the VAT proof: the returns less payments, then the lines that explain the rest
        # (yet to file, opening variance, filed but not in the accounts, cash-basis debtors and creditors, typed
        # exception report and adjustments)
        from backend.app.services.tax.vat_proof import vat_proof
        proof = vat_proof(engagement, tb_records, db, pos=pos, books=vat_books, gl=lines) if pos.returns else None
        row = _row("vat", f"VAT ({VAT_CONTROL})", "Tax", vat_books,
                   f"VAT proof: returns less {'payments per the VAT summary' if pos.source == 'summary' else 'HMRC payments'}"
                   f" and the reconciling lines ({in_year} return(s) this year)",
                   proof["total"] if proof and ledger else None, "G9",
                   missing=("Enter the VAT returns on the VAT returns screen" if not pos.returns else
                            "No ledger lines on the VAT account, so the HMRC payments cannot be seen: "
                            "upload the general ledger"))
        row.proof = proof
        rows.append(row)

    # Trade debtors and creditors against the aged lists (as the review's ledger_vs_aged_list)
    try:
        ageing = read_ageing_reports(str(engagement.id), engagement.period_end_date, tb_records)
    except Exception:
        ageing = {}
    for kind, code, what, tab in (("AR", TRADE_DEBTORS, "Trade debtors", "E2"), ("AP", TRADE_CREDITORS, "Trade creditors", "G2")):
        books = abs(bal.get(code, 0.0))
        report = ageing.get(kind)
        if books < 0.005 and report is None:
            continue
        rows.append(_row(kind.lower(), f"{what} ({code})", "Balance sheet", books, f"Aged {what.lower()} report",
                         abs(report.total) if report is not None and report.total is not None else None, tab,
                         missing=f"No aged {what.lower()} report in the client's files: it is read from the upload "
                                 f"(an optional file with the trial balance and ledger)"))

    # Payroll: gross pay in the books against the payroll report (as U-PAY-001), only its pay periods inside the year
    # (as the review: a file can hold other months, e.g. a calendar-year report against an April-March year); a row
    # with no date (a year's summary) is kept
    from backend.app.services.review.paye_check import _year as payroll_year
    year_start, year_end = payroll_year(engagement)
    uploaded = db.execute(select(PayrollP32Record).where(PayrollP32Record.engagement_id == engagement.id)).scalars().all()
    from backend.app.services.review.payroll_period import off_period
    off = off_period(engagement, uploaded)
    payroll = [] if off else [r for r in uploaded if r.period_end is None or year_start <= r.period_end <= year_end]
    outside = sorted({r.period_end for r in uploaded if r not in payroll})
    outside_text = (f"{outside[0]:%b %Y}" if len(outside) == 1 else f"{outside[0]:%b %Y} to {outside[-1]:%b %Y}") if outside else ""
    chart = ChartLookup(db)
    # Employer NI the firm codes with the wages (an account named employer NI on 3000 / 1500) is NI, not gross pay
    from backend.app.services.review.payroll_journals.common import EMPLOYER_NI_NAME
    ni_on_pay = round(sum(float(t.net_amount or 0) for t in tb_records if chart.is_gross_wages(t.std_code)
                          and EMPLOYER_NI_NAME.search(t.raw_account_name or "")), 2)
    gross_books = sum(v for k, v in bal.items() if chart.is_gross_wages(k)) - ni_on_pay
    if uploaded or abs(gross_books) >= 0.005:
        rows.append(_row("payroll", "Gross pay (wages and directors' salaries)", "Payroll", gross_books, "Payroll report",
                         sum(float(r.gross_pay or 0) for r in payroll) if payroll else None, "G6.2",
                         note=f"Pay periods outside the year left out: {outside_text}" if outside_text else "",
                         missing=(f"{off}: upload this year's payroll report" if off else
                                  f"The payroll report is for {outside_text}, not this year ({year_start:%b %Y} to "
                                  f"{year_end:%b %Y}): upload this year's payroll report" if uploaded else
                                  "Upload the payroll report")))
        # Employer NI: the payroll's, less the employment allowance claimed through the payroll (its allowance
        # column), is the cost in the accounts; employer pension per the payroll is the pension cost
        from backend.app.services.review.payroll_journals import allowance_in_books_total, payroll_file_allowance
        er_ni_books = sum(bal.get(c, 0.0) for c in EMPLOYER_NI_CODES) + ni_on_pay
        er_ni = sum(float(r.employer_nic or 0) for r in payroll)
        # The allowance per the payroll file; else the one the books already hold ('EA' journals)
        allowance, source = (payroll_file_allowance(engagement, db), "per payroll") if payroll else (0.0, "")
        if payroll and allowance < 0.005:
            allowance, source = allowance_in_books_total(engagement, tb_records, chart, db), "in the books"
        if payroll and (er_ni >= 0.005 or abs(er_ni_books) >= 0.005):
            rows.append(_row("payroll_er_ni", "Employer NI (after employment allowance)", "Payroll", er_ni_books,
                             "Payroll report: employer NI"
                             + (f" £{er_ni:,.2f} less allowance {source} £{allowance:,.2f}" if allowance >= 0.005 else ""),
                             er_ni - allowance, "G7",
                             note=("" if allowance >= 0.005 else "No employment allowance in the payroll report or "
                                   "the books: see the review's employment allowance point")))
        er_pension_books = sum(bal.get(c, 0.0) for c in EMPLOYER_PENSION_CODES)
        er_pension = sum(float(r.pension_employer or 0) for r in payroll)
        if payroll and (er_pension >= 0.005 or abs(er_pension_books) >= 0.005):
            rows.append(_row("payroll_er_pension", "Employer pension", "Payroll", er_pension_books,
                             "Payroll report: employer pension", er_pension, "G8"))

    # Corporation tax: the charge in the accounts against the computation (H1); s455 against the books (E5)
    comp = ct_computation(engagement, tb_records, db)
    if abs(comp.tax_in_accounts) >= 0.005 or abs(comp.corporation_tax) >= 0.005:
        rows.append(_row("ct", f"Corporation tax charge ({CT_CHARGE})", "Tax", comp.tax_in_accounts,
                         "Corporation tax computation", comp.corporation_tax, "H1"))
    s455_books = sum(bal.get(c, 0.0) for c in S455_CODES)
    if comp.s455_tax >= 0.005 or abs(s455_books) >= 0.005:
        rows.append(_row("s455", "s455 tax recoverable (4450 / 4550)", "Tax", s455_books,
                         "s455 per the tax computation", comp.s455_tax, "E5"))
    rows.extend(_cis_rows(engagement, db))
    for r in rows:
        r.section = ROW_SECTION.get(r.key) or (CURRENT if r.key.startswith("bank:") else PL_CHECKS)
        r.codes = sorted(ROW_CODES.get(r.key) or ({int(r.key[5:])} if r.key.startswith("bank:") else set()))
    last = _last_year_balances(engagement, db, tb_records)
    rows.extend(_balance_sheet_rows(engagement, db, bal, last, rows, chart, tb_records))
    for r in rows:
        if r.last_year is None and last is not None and r.section != PL_CHECKS and r.codes:
            r.last_year = _same_sign(r, bal, sum(last.get(c, 0.0) for c in r.codes))
    _journal_notes(rows, engagement, db)
    # Each row's plain balance (debit +), so a screen can list rows that show their books differently alike (the
    # Creditors summary: every creditor as an amount owed)
    for r in rows:
        if r.codes:
            r.balance = round(sum(bal.get(c, 0.0) for c in r.codes), 2)
    return _in_order(rows)


__all__ = ['CAPITAL', 'CATEGORY_SECTION', 'CHARGE_TEXT', 'CT_CHARGE', 'CT_TEXT', 'CURRENT', 'CURRENT_LIAB',
           'DIFFERENCE', 'EMPLOYER_NI_CODES', 'EMPLOYER_PENSION_CODES', 'FIXED', 'HMRC_TEXT', 'JOURNAL_SOURCE',
           'LONG_LIAB', 'LastYear', 'MATCHED', 'NEEDS_INPUT', 'NIL', 'OTHER_TAX_TEXT', 'PAID_WITHIN_DAYS',
           'PL_CHECKS', 'QB_VAT_MEMO', 'ROW_CODES', 'ROW_SECTION', 'Reconciliation', 'SECTIONS', 'SUPPORT',
           'SUSPENSE_CODE', 'TOLERANCE', 'TRADE_CREDITORS', 'TRADE_DEBTORS', 'TRANSFERS_CODE', 'VAT_PAID_TEXT',
           'VAT_PROOF_KEYS', 'VAT_WORDS', 'VatPosition', '_account_label', '_balance_sheet_rows', '_banks',
           '_books_client_rows', '_by_hand', '_cis_rows', '_in_order', '_journal_notes', '_last_year_balances',
           '_lower_first', '_row', '_same_sign', 'bank_currency', 'by_hand_key', 'entered_inputs', 'other_tax_kind',
           'save_input', 'statement_balance', 'summary', 'vat_paid_per_return', 'vat_position', 'reconciliations']
