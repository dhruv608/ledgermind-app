"""Building the working papers workbook from the firm's template: load the template, fill the context, run each
part in order (core tabs, fixed assets, balance sheet, payroll, VAT, accruals, reserves, tax, the accountant's
extra tabs), tidy and check it, work out the formulas, save it as a new version.

The rules the build keeps:
1. TTB column totals as =SUM formulas on every amount column
2. The full General Ledger, unfiltered
3. Control account tabs only for codes the TB holds
4. Nothing carried over from the template's own example client (no stray names, no #REF! errors)
5. A pre-release QA gate before the file is saved
"""

import logging
import tempfile
from datetime import timedelta, datetime
from pathlib import Path
from typing import Any, List, Optional

import openpyxl
import pandas as pd
from openpyxl.styles import Border, Font, Side
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.s3 import s3_service
from backend.app.models.database import ClientEngagement, GeneratedWorkpaper, MasterCOA, TBRecord
from backend.app.models.bank_statement import BankStatementLine
from backend.app.models import custom_papers as _custom_papers, stock_lines as _stock_lines  # noqa: F401 (tables made at start)
from backend.app.models import yearend_adjustments as _yearend_adjustments  # noqa: F401
from backend.app.services.ingestion.ageing_reports import read_ageing_reports
from backend.app.services.loans.agreements import agreement_schedules, last_year_loans
from backend.app.services.tax.ct_computation import ct_computation
from backend.app.services.reconciliation.control_accounts import entered_inputs
from backend.app.services.sop.related_party import related_parties
from backend.app.services.workbook.balance_sheet import add_accrual_tabs, add_balance_sheet_tabs, add_reserves_tab
from backend.app.services.workbook.opening_tabs import add_opening_tabs
from backend.app.services.workbook.notes_tab import add_notes
from backend.app.services.workbook.balance_tabs import Context as BalanceTabsContext, add_balance_tabs
from backend.app.services.workbook.context import BuildContext
from backend.app.services.workbook.bs_ledgers import add_bs_ledgers_tab
from backend.app.services.workbook.core_tabs import add_core_tabs
from backend.app.services.workbook.ledger_chain import add_ledger_chain
from backend.app.services.workbook.far_tab import add_far_tab
from backend.app.services.workbook.fixed_assets import add_fixed_asset_tabs
from backend.app.services.workbook.payroll import add_payroll_tabs
from backend.app.services.workbook.subcontractors import add_subcontractor_tab
from backend.app.services.workbook.cis_tabs import add_cis_tabs
from backend.app.services.workbook.qa import run_pre_release_qa_check, zero_references_to_removed_sheets
from backend.app.services.workbook.tab_order import order_tabs
from backend.app.services.workbook.recalc import recalculate_with_excel_com, recalculate_with_libreoffice
from backend.app.services.workbook.scrutiny_tab import add_scrutiny_tab
from backend.app.services.workbook.tax import add_general_checks_tab, add_tax_tab
from backend.app.services.workbook.tidy import tidy_workbook
from backend.app.services.workbook.vat import add_vat_tabs

logger = logging.getLogger(__name__)


def _gl_openings(db: Optional[Session], engagement_id: str) -> dict:
    """The ledger's opening balances the TB could not take (kept at upload): {account: (amount, in the TB)}."""
    if db is None:
        return {}
    from backend.app.models.gl_openings import GLOpeningBalance
    return {o.account_name: (float(o.amount), bool(o.in_tb)) for o in db.execute(
        select(GLOpeningBalance).where(GLOpeningBalance.engagement_id == engagement_id)).scalars()}


def _statement_lines(engagement, db) -> dict:
    """Each bank code whose statement was read on the screen: its lines against the books (Unrecorded / Unmatched /
    Matched under the bank's T)."""
    if db is None:
        return {}
    from backend.app.services.reconciliation.bank_statement import statement_match
    try:
        codes = set(db.execute(select(BankStatementLine.code).where(
            BankStatementLine.engagement_id == str(engagement.id))).scalars())
    except Exception:                     # a database made before the table: no statement read
        db.rollback()
        return {}
    return {int(c): statement_match(engagement, db, int(c)) for c in codes if c is not None}


def _drop_dividers(wb) -> None:
    """The section divider tabs ('C', 'E', 'F' ...: a blank page with the client's name) are not on the screen and
    carry no figures, so they go; every other tab stays. The cover 'A' stays."""
    import re
    for name in [t for t in wb.sheetnames if re.fullmatch(r"[B-Z]", t.strip())]:
        for dn in [n for n, d in list(wb.defined_names.items()) if f"'{name}'!" in (d.attr_text or "")
                   or (d.attr_text or "").startswith(f"{name}!")]:
            del wb.defined_names[dn]
        del wb[name]


def build_master_workpapers(
    engagement: ClientEngagement,
    tb_records: List[TBRecord],
    gl_df: Optional[pd.DataFrame] = None,
    journals: Optional[Any] = None,
    db: Optional[Session] = None,
    draft_note: Optional[str] = None,
) -> GeneratedWorkpaper:
    # A db session passed as the 4th positional argument is taken as db
    if isinstance(journals, Session) or (journals is not None and not isinstance(journals, list)):
        db = journals
        journals = None

    template_path = settings.TEMPLATE_PATH
    if not template_path.exists():
        template_path = settings.FALLBACK_TEMPLATE_PATH
    if not template_path.exists():
        raise FileNotFoundError(f"Master workpaper template not found at {template_path}")

    # Load workbook keeping all formulas intact
    wb = openpyxl.load_workbook(str(template_path), data_only=False)
    from backend.app.services.workbook.context import GL_TAB, TEMPLATE_GL_TAB
    if TEMPLATE_GL_TAB in wb.sheetnames and GL_TAB not in wb.sheetnames:
        wb[TEMPLATE_GL_TAB].title = GL_TAB
    removed_sheets: List[str] = []
    _period_dates(wb, engagement)

    # Aged debtors / creditors reports uploaded with the client's files
    ageing = read_ageing_reports(str(engagement.id), engagement.period_end_date, tb_records)
    report_notes: List[str] = []

    client_name = engagement.client_name or "Client Company"
    from backend.app.services.workbook import memlog
    memlog.step(client_name, "start")
    period_date_str = engagement.period_end_date.strftime("%d %B %Y")
    ye_str = f"Year Ended {period_date_str}"

    # Standard border and font styles for accounting totals
    bold_font = Font(name="Calibri", size=10, bold=True)
    accounting_total_border = Border(
        top=Side(style="thin", color="000000"),
        bottom=Side(style="double", color="000000")
    )

    # What every section shares, and the shared helpers (services/workbook/context.py)
    ctx = BuildContext(wb=wb, engagement=engagement, db=db, tb_records=tb_records, client_name=client_name,
                       ye_str=ye_str, bold_font=bold_font, accounting_total_border=accounting_total_border,
                       ageing=ageing, removed_sheets=removed_sheets, report_notes=report_notes)

    # Cover, TTB, B2 journals, re-analysis, notes, B1 ETB, GL detail, Section K: services/workbook/core_tabs.py
    # An LLP has no corporation tax, share capital or dividends (setup/entity.py): those tabs are left out
    from backend.app.services.setup.entity import is_llp
    from backend.app.models.database import ClientProfile
    _profile = db.query(ClientProfile).filter(ClientProfile.engagement_id == engagement.id).first() if db is not None else None
    if is_llp(engagement, _profile):
        for name in list(wb.sheetnames):
            if name.startswith(("H1", "H2", "J1 ", "J1-", "J3")) or name == "H":
                ctx.remove_sheet(name)
    add_core_tabs(ctx, gl_df, journals, draft_note)
    # The TB account on each GL line and the TTB's movement per GL by client account: workbook/ledger_chain.py
    add_ledger_chain(ctx)
    add_bs_ledgers_tab(ctx)
    # Last year's TB and the opening balances tie-out (PY-TB, OBD): services/workbook/opening_tabs.py
    add_opening_tabs(ctx)


    # Fixed assets (C1, C1-1, C1.2, C1.3): services/workbook/fixed_assets.py
    add_fixed_asset_tabs(ctx)
    add_far_tab(ctx)


    # Stock, debtors, prepayments, bank, creditors, DLA and their review tabs: services/workbook/balance_sheet.py
    add_balance_sheet_tabs(ctx)

    # -------------------------------------------------------------
    # Payroll (G6, G6.2, G6.3, G7, G8): services/workbook/payroll/
    # -------------------------------------------------------------
    add_payroll_tabs(ctx)
    add_subcontractor_tab(ctx)
    add_cis_tabs(ctx)

    # VAT (G9, G9.1, G9.3, G9.5): services/workbook/vat.py
    add_vat_tabs(ctx)

    # Accruals (G10, G10.2): services/workbook/balance_sheet.py
    add_accrual_tabs(ctx)

    # GL scrutiny (K0.2): the ledger lines read, moved and asked about on the Accounts tab
    add_scrutiny_tab(ctx)

    # Notes & Queries the app writes from its own figures: the bank table, P&L this year v last year (notes_tab.py)
    add_notes(ctx)

    zero_references_to_removed_sheets(wb, removed_sheets)

    # Reserves (J2): services/workbook/balance_sheet.py
    add_reserves_tab(ctx)

    # H1 tax computation, H2 CT600 boxes and A1 general checks: services/workbook/tax.py
    add_tax_tab(ctx)
    add_general_checks_tab(ctx)

    # The accountant's balance sheet tabs: one per bank account, loans and HP per lender, deposits, s455 and
    # dividends (made only when the client has the account)
    s455_tax, s455_note = 0.0, ""
    if db is not None:
        comp = ct_computation(engagement, tb_records, db)
        s455_tax, s455_note = float(comp.s455_tax or 0.0), comp.s455_explanation or ""
    balance_ctx = BalanceTabsContext(
        wb=wb, client_name=client_name, period_end=engagement.period_end_date, tb_records=tb_records,
        tx_rows=ctx.tx_rows, opening_by_code=ctx.opening_by_code, account_name=ctx.account_name, tb_kind=ctx.tb_kind,
        s455_tax=s455_tax, s455_note=s455_note,
        statements=entered_inputs(db, engagement.id) if db is not None else {},
        gl_openings=_gl_openings(db, engagement.id),
        agreements=agreement_schedules(engagement, db) if db is not None else [],
        last_year_loans=last_year_loans(engagement),
        journals=ctx.journals,
        statement_lines=_statement_lines(engagement, db),
        period_start=(engagement.prior_period_end_date + timedelta(days=1)) if engagement.prior_period_end_date else None)
    add_balance_tabs(balance_ctx)
    # P1: a letting client's rent and costs by property and month
    from backend.app.services.workbook.property_tab import add_property_tab
    p1 = add_property_tab(ctx)
    # P2: the letting agents' statements against the rent the bank received (gross-up)
    from backend.app.services.workbook.property_agents import add_agent_tab
    add_agent_tab(ctx, p1)
    # F-P: an e-commerce client's platforms (Amazon, Shopify ...) as clearing accounts against their reports
    from backend.app.services.workbook.platform_tab import add_platform_tab, add_takings_tab
    add_platform_tab(ctx)
    # K1-T: a restaurant's card and delivery settlements and its cash, against Z-reports and providers' reports
    add_takings_tab(ctx)
    # D1-P: a property developer's site costs by type and its property schedule (stock v net realisable value)
    from backend.app.services.workbook.development_tab import add_development_tab
    add_development_tab(ctx)
    report_notes.extend(balance_ctx.notes)
    # B1-ETB: final less each single-code schedule's c/fwd
    from backend.app.services.workbook.etb_schedule_check import add_schedule_check
    add_schedule_check(wb, {**ctx.schedule_cf, **balance_ctx.schedule_cf})
    # Leads from the ETB codes: every code of the debtors and creditors leads, the lead checked to all
    from backend.app.services.workbook.lead_codes import add_lead_codes
    add_lead_codes(wb)
    # The other stop rules as labelled checks: C1, J2, H1, balances on the wrong side
    from backend.app.services.workbook.stop_checks import add_stop_checks
    add_stop_checks(wb)

    # Planning and completion tabs: size test (FRS), associated companies, accountancy fee accrual, checklists
    if db is not None and getattr(engagement, "profile", None) is not None:
        from backend.app.services.setup.engagement_setup import build_record
        from backend.app.services.review.last_year import prior_balances_by_code
        from backend.app.services.workbook.setup_tabs import add_setup_tabs
        record = build_record(engagement, engagement.profile, db)
        coa = {c.std_code: c for c in db.execute(select(MasterCOA)).scalars().all()}
        prior = prior_balances_by_code(engagement, db)
        sales_ly = -sum(v for k, v in prior.items() if k in coa and coa[k].category == "Sales")
        assets_ly = sum(v for k, v in prior.items() if k in coa and coa[k].financial_class == "Balance Sheet"
                        and k < 5000 and v > 0)
        last_year_size = {"turnover": round(sales_ly, 2) if abs(sales_ly) >= 0.005 else None,
                          "assets": round(assets_ly, 2) if prior else None, "employees": None}
        connected = [p.name for p in related_parties(engagement) if p.kind == "company"]
        add_setup_tabs(balance_ctx, record, last_year_size, connected)

    # -------------------------------------------------------------
    # STEP 13: links, checks, tab order, look and the pre-release QA gate
    # -------------------------------------------------------------
    memlog.step(client_name, "all tabs written")
    # Every tab's ledger lines as formulas to the GL tab, once all are written
    from backend.app.services.workbook.gl_links import link_to_gl
    link_to_gl(ctx)
    # A0 - Checks: every labelled check with its status, and the cover's draft line by formula
    from backend.app.services.workbook.checks_tab import add_checks_tab, failed as failed_checks
    _schedule_column(wb)
    _journal_links(wb)
    _etb_checks_tab(wb)
    _etb_pl_bs(wb)
    # Tab order: the core pack in the reviewers' order, extra review tabs in an appendix; before A0
    # so its list of checks follows the same order
    # The screen's extra papers under their areas' tabs (same services as the screen)
    from backend.app.services.workbook.screen_papers import add_screen_papers
    add_screen_papers(ctx)
    _drop_dividers(wb)
    order_tabs(wb)
    add_checks_tab(wb, draft_note)
    tidy_workbook(wb, client_name, ye_str)
    # Frozen headings, print set-up, tab colours by section (the house style)
    from backend.app.services.workbook.look import finish_look
    finish_look(wb)
    _light_etb(wb)
    qa_issues = run_pre_release_qa_check(wb, tb_records) + report_notes
    if draft_note:
        qa_issues.append(f"DRAFT: {draft_note}")
    diagnostics_score = "PASS" if not qa_issues else f"{len(qa_issues)} issue(s) found"

    # -------------------------------------------------------------
    # STEP 14: Save and Calculate
    # -------------------------------------------------------------
    clean_name = "".join(c for c in client_name if c.isalnum() or c in (" ", "_", "-")).strip()
    filename = f"WP_{clean_name}_YE_{engagement.period_end_date.strftime('%d.%m.%Y')}{'_DRAFT' if draft_note else ''}.xlsx"
    with tempfile.TemporaryDirectory() as tmp:
        local_output_path = Path(tmp) / filename
        wb.save(str(local_output_path))
        memlog.step(client_name, "file saved")

        # Work out every formula so the figures show wherever the file is opened (Excel's Protected View, phone
        # and in-app previews do not calculate): Excel on a Windows computer, else LibreOffice on the server
        if not recalculate_with_excel_com(local_output_path):
            recalculate_with_libreoffice(local_output_path)
        memlog.step(client_name, "formulas worked out")
        # The stop rule: a red check not nil keeps the workbook a draft; red and amber are listed (A0 - Checks)
        try:
            not_nil = failed_checks(local_output_path)
        except Exception:
            logger.exception("A0 checks could not be read")
            not_nil = None
        if not_nil:
            red = [c for c in not_nil if c[0] == "RED"]
            qa_issues.extend(f"{st}: {tab} - {label} {value:,.2f}" for st, tab, label, value in not_nil[:40])
            diagnostics_score = f"{len(qa_issues)} issue(s) found"
            if red and "_DRAFT" not in filename:
                filename = filename.replace(".xlsx", "_DRAFT.xlsx")

        with open(local_output_path, "rb") as f:
            file_bytes = f.read()

    # Every build is kept as its own version (the Workbook tab lists earlier ones), so the stored name is unique
    s3_key = f"engagements/{engagement.id}/{datetime.utcnow():%Y%m%d-%H%M%S}_{filename}"

    # Upload / save to storage
    storage_path = s3_service.upload_file_bytes(
        file_bytes=file_bytes,
        s3_key=s3_key,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # A new version every build; the newest is the client's current workbook
    workpaper = GeneratedWorkpaper(
        engagement_id=engagement.id,
        filename=filename,
        storage_path=storage_path,
        file_size_bytes=len(file_bytes),
        diagnostics_score=diagnostics_score,
        generated_at=datetime.utcnow(),
    )
    if db:
        db.add(workpaper)

    if db:
        db.commit()
        db.refresh(workpaper)

    memlog.step(client_name, "stored")
    return workpaper


TEMPLATE_PERIOD_START = "=EDATE(YEAREND,-12)+1"     # the template's dates: twelve months before the year end
TEMPLATE_PRIOR_END = "=EDATE(YEAREND,-12)"


def _period_dates(wb, engagement) -> None:
    """The template's period dates (C1 lead, E2, G2 b/fwd) as the real ones when last year's TB date is known: a short
    or long period after a change of year end does not start twelve months before the year end."""
    prior = getattr(engagement, "prior_period_end_date", None)
    if prior is None:
        return
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=60, max_col=8):
            for cell in row:
                text = cell.value.replace(" ", "").upper() if isinstance(cell.value, str) else ""
                if text == TEMPLATE_PERIOD_START:
                    cell.value = prior + timedelta(days=1)
                elif text == TEMPLATE_PRIOR_END:
                    cell.value = prior
                else:
                    continue
                cell.number_format = "dd/mm/yyyy"


ETB_MAIN_LAST_COL = 14           # B1-ETB N, the final balance: the main columns are A to N
ETB_SHOWN = {"schedule"}        # a heading after N that stays open (the link to each code's tab)


def _etb_heading(ws, c: int) -> str:
    return " ".join(str(ws.cell(row=r, column=c).value or "").strip() for r in (6, 7)).strip()


def _etb_check_columns(ws) -> List[int]:
    """B1-ETB's check columns: after the final balance (N), all but the schedule link."""
    view = getattr(ws, "_etb_view_cols", set())     # the P&L / balance sheet columns and the schedule beside them
    return [c for c in range(ETB_MAIN_LAST_COL + 1, ws.max_column + 1)
            if c not in view and _etb_heading(ws, c).lower().split(" ")[0] not in ETB_SHOWN]


ETB_CHECKS_TAB = "B1.1 - ETB checks"


def _etb_checks_tab(wb) -> None:
    """B1.1: the ETB's check columns on a tab of their own, each code on the same row as on B1-ETB and every figure a
    link to B1-ETB (only links, no large calculations). The columns stay
    on B1-ETB too (collapsed, _light_etb): the final balance and other tabs read them there. Headings say what each
    column is without 'must be nil', so A0 does not count the same checks twice."""
    if "B1-ETB" not in wb.sheetnames:
        return
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from backend.app.services.workbook.etb_rows import data_rows
    etb = wb["B1-ETB"]
    cols = [c for c in _etb_check_columns(etb) if _etb_heading(etb, c)]       # every check column, empty or not
    if not cols:
        return
    if ETB_CHECKS_TAB in wb.sheetnames:
        del wb[ETB_CHECKS_TAB]
    ws = wb.create_sheet(ETB_CHECKS_TAB, wb.sheetnames.index("B1-ETB") + 1)
    ws["A1"], ws["A2"], ws["E1"] = "=A!B2", "='Notes & Queries'!A2", "B1.1"
    ws["A4"] = "ETB checks: the columns kept off the ETB, linked to B1-ETB"
    ws["A4"].font = Font(bold=True, size=12)
    ws["A5"] = ("Each figure is the B1-ETB cell on the same row; the checks themselves are counted on A0 from B1-ETB, "
                "so a difference here is the same one as there.")
    bold = Font(bold=True)
    ws.cell(row=6, column=1, value="Code").font = bold
    ws.cell(row=6, column=2, value="Account").font = bold
    for j, c in enumerate(cols, 3):
        text = _etb_heading(etb, c).replace("(must be nil)", "(should be nil)")
        ws.cell(row=6, column=j, value=text).font = bold
    rows = data_rows(etb)
    total = next((r for r in range(rows[-1] + 1, rows[-1] + 4) if str(etb.cell(row=r, column=2).value or "") == "TOTAL"),
                 None) if rows else None
    for r in rows + ([total] if total else []):
        ws.cell(row=r, column=1, value=f"='B1-ETB'!A{r}" if r != total else None)
        ws.cell(row=r, column=2, value=f"='B1-ETB'!B{r}")
        for j, c in enumerate(cols, 3):
            src = etb.cell(row=r, column=c).value
            if src in (None, "") and r == total:
                continue
            ref = f"'B1-ETB'!{get_column_letter(c)}{r}"
            cell = ws.cell(row=r, column=j, value=f'=IF({ref}="","",{ref})')       # an empty ETB cell shows empty
            cell.number_format = "#,##0.00;(#,##0.00)"
            if r == total:
                cell.font = bold
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 10, 34
    for j in range(3, 3 + len(cols)):
        ws.column_dimensions[get_column_letter(j)].width = 18
    ws.freeze_panes = "C7"


def _light_etb(wb) -> None:
    """A minimal B1-ETB: code, name, opening, movement, journals and final balance open, and the check columns after
    them (opening adjustment, the TB per software, TB not in the ledger, last year and the variance, the spec final)
    grouped and collapsed, a + above them to open. The columns are not moved: the final balance and 30-odd formulas
    on other tabs read them, so only the view changes."""
    if "B1-ETB" not in wb.sheetnames:
        return
    from openpyxl.utils import get_column_letter
    ws = wb["B1-ETB"]
    last = ws.max_column
    hide = _etb_check_columns(ws)
    runs, start = [], None
    for c in range(ETB_MAIN_LAST_COL + 1, last + 2):
        if c in hide and start is None:
            start = c
        elif c not in hide and start is not None:
            runs.append((start, c - 1))
            start = None
    for a, b in runs:
        ws.column_dimensions.group(get_column_letter(a), get_column_letter(b), outline_level=1, hidden=True)
    ws.sheet_properties.outlinePr.summaryRight = True
    # With the P&L / balance sheet columns (_etb_pl_bs): the empty C-E and the schedule link V (repeated beside them)
    # fold away, leaving the 16 open columns
    if getattr(ws, "_etb_view_cols", None):
        ws.column_dimensions.group("C", "E", outline_level=1, hidden=True)
        ws.column_dimensions.group("V", "V", outline_level=1, hidden=True)


def _etb_pl_bs(wb) -> None:
    """B1-ETB in 16 columns (code, name, opening, movement, journals, final, P&L Dr/Cr, BS Dr/Cr): the final balance split into profit and loss or balance sheet, debit and credit, after the last
    column, with their totals and a check that they add back to the final balance; then the schedule link (V) beside
    them. No column moves (thousands of formulas read B1-ETB by letter): the empty C-E and V fold away instead."""
    if "B1-ETB" not in wb.sheetnames:
        return
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from backend.app.services.workbook.balance_tabs.common import MONEY
    from backend.app.services.workbook.etb_rows import data_rows, is_pl
    ws = wb["B1-ETB"]
    rows = data_rows(ws)
    if not rows:
        return
    s = ws.max_column + 1
    L = [get_column_letter(s + i) for i in range(5)]
    ws._etb_view_cols = set(range(s, s + 5))
    bold = Font(name="Calibri", size=11, bold=True)
    for i, (head, side) in enumerate((("Profit and loss", "Debit £"), (None, "Credit £"),
                                      ("Balance sheet", "Debit £"), (None, "Credit £"), ("Schedule", None))):
        if head:
            ws.cell(row=6, column=s + i, value=head).font = bold
        if side:
            ws.cell(row=7, column=s + i, value=side).font = bold
        ws.column_dimensions[L[i]].width = 26 if i == 4 else 15
    for r in rows:
        dr, cr = (0, 1) if is_pl(ws.cell(row=r, column=1).value) else (2, 3)
        ws.cell(row=r, column=s + dr, value=f"=MAX(N{r},0)").number_format = MONEY
        ws.cell(row=r, column=s + cr, value=f"=MAX(-N{r},0)").number_format = MONEY
        link = ws.cell(row=r, column=22).value
        if isinstance(link, str) and link.startswith("=HYPERLINK"):
            ws.cell(row=r, column=s + 4, value=link)
    total = next((r for r in range(rows[-1] + 1, rows[-1] + 6)
                  if str(ws.cell(row=r, column=2).value or "").strip().upper() == "TOTAL"), None)
    if total:
        for i in range(4):
            cell = ws.cell(row=total, column=s + i, value=f"=SUM({L[i]}{rows[0]}:{L[i]}{rows[-1]})")
            cell.number_format, cell.font = MONEY, bold
        check = total + 1
        if "check" in str(ws.cell(row=check, column=2).value or "").lower():
            ws.cell(row=check, column=s, value=(f"=ROUND(({L[0]}{total}-{L[1]}{total}+{L[2]}{total}-{L[3]}{total})"
                                                f"-N{total},2)")).number_format = MONEY


def _journal_links(wb) -> None:
    """B2-Journals: each journal line's code linked to the tab that holds its schedule, as the ETB's column V does
    A cell link, so the code stays a number the ETB adds up."""
    refs = getattr(wb, "_schedule_refs", None) or {}
    if "B2-Journals" not in wb.sheetnames or not refs:
        return
    from openpyxl.styles import Font
    ws = wb["B2-Journals"]
    for row in ws.iter_rows(min_row=5, min_col=5, max_col=5):
        cell = row[0]
        tab = refs.get(str(cell.value)) if cell.value not in (None, "") else None
        if tab and tab in wb.sheetnames:
            cell.hyperlink = "#'" + tab.replace("'", "''") + "'!A1"
            cell.font = Font(name="Calibri", size=11, color="0563C1", underline="single")


def _schedule_column(wb) -> None:
    """B1-ETB column V: the tab that holds each code's schedule, linked (the 'Schedule ref')."""
    refs = getattr(wb, "_schedule_refs", None) or {}
    if "B1-ETB" not in wb.sheetnames or not refs:
        return
    from openpyxl.styles import Font
    ws = wb["B1-ETB"]
    ws.cell(row=6, column=22, value="Schedule").font = Font(name="Calibri", size=11, bold=True)
    ws.column_dimensions["V"].width = 26
    from backend.app.services.workbook.etb_rows import data_rows
    for r in data_rows(ws):
        tab = refs.get(str(ws.cell(row=r, column=1).value))
        if tab and tab in wb.sheetnames:
            safe = tab.replace("'", "''")
            link = "#'" + safe + "'!A1"
            ws.cell(row=r, column=22, value=f'=HYPERLINK("{link}","{tab[:30]}")')
