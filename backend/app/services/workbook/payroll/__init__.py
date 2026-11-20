"""Payroll tabs from the ledger: G6 net wages, G6.2 payroll summary (with the payroll report checked against the
books), G6.3 average employees, G7 PAYE / NI and G8 pension, each with its month-by-month control table.

Split by part: controls (leads, month tables), report (payroll report, directors),
build (the tabs); this module holds the shared state and the order the tabs are made in."""

from types import SimpleNamespace
from functools import partial

from backend.app.models.database import PayrollP32Record
from backend.app.services.mapping.chart_lookup import NET_WAGES
from backend.app.services.papers.payroll_months import LedgerMonths, pension_accounts, pension_line, year_months
from backend.app.services.papers.payroll_months import closing_owed as _closing_owed
from backend.app.services.papers.payroll_months import journal_allowance as _journal_allowance
from backend.app.services.papers.payroll_months import journal_totals as _journal_totals
from backend.app.services.workbook.context import BuildContext
from backend.app.services.workbook.context import rebuild_control_subledger as _rebuild_control_subledger

from backend.app.services.workbook.payroll import build, controls, report


def add_payroll_tabs(ctx: BuildContext) -> None:
    wb, engagement, db, tb_records, journals = ctx.wb, ctx.engagement, ctx.db, ctx.tb_records, ctx.journals
    tx_rows, tb_codes_present, report_notes = ctx.tx_rows, ctx.tb_codes_present, ctx.report_notes
    bold_font, accounting_total_border = ctx.bold_font, ctx.accounting_total_border
    remove_sheet = ctx.remove_sheet
    rebuild_control_subledger = partial(_rebuild_control_subledger, ctx)

    # -------------------------------------------------------------
    # Payroll (G6 net wages, G6.2 summary, G6.3 employees, G7 PAYE, G8 pension) from the ledger, with the payroll
    # report checked against it when one is uploaded.
    # -------------------------------------------------------------
    pension_names, pension_codes = pension_accounts(tb_records)
    payroll_months = year_months(engagement.period_end_date)
    led = LedgerMonths(tx_rows, payroll_months)
    month_of = led.month_of
    is_pension_line = pension_line(pension_names)
    closing_owed = partial(_closing_owed, tb_records)

    p = SimpleNamespace(**{k: v for k, v in locals().items() if k != 'p'})
    p.write_control_lead = partial(controls.write_control_lead, p)
    p.lead_to_g1 = partial(controls.lead_to_g1, p)
    p.write_control_table = partial(controls.write_control_table, p)
    p.clear_from = partial(controls.clear_from, p)
    p.tab_opening = partial(controls.tab_opening, p)
    p.other_entries = partial(controls.other_entries, p)
    p.payroll_report_lines = partial(report.payroll_report_lines, p)
    p.write_payroll_report = partial(report.write_payroll_report, p)
    p.directors_per_file = partial(report.directors_per_file, p)
    p.write_directors = partial(report.write_directors, p)
    p.write_net_pay_paid = partial(report.write_net_pay_paid, p)
    p.build_payroll = partial(build.build_payroll, p)
    journal_totals = partial(_journal_totals, journals)
    p.journal_totals = journal_totals
    journal_allowance = partial(_journal_allowance, journals)
    p.journal_allowance = journal_allowance
    PAYROLL_FIELDS = ["gross_pay", "tax_deducted", "employee_nic", "employer_nic", "student_loan",
                      "pension_employee", "pension_employer", "net_pay"]
    p.PAYROLL_FIELDS = PAYROLL_FIELDS
    WAGE_PAYMENT_CODES = {str(NET_WAGES), "3000", "3004", "3010", "3014", "3015"}
    p.WAGE_PAYMENT_CODES = WAGE_PAYMENT_CODES
    build_payroll = p.build_payroll

    # 8. Net Wages / Payroll (Section G6)
    has_wages = any(c in tb_codes_present for c in {"5330", "2220", "3000", "3010"})
    if not has_wages:
        for s in ["G6 - Net Wages", "G6.1 - NL Analysis", "G6.2 - Payroll summary", "G6.3 - Avg. No. of Employee"]:
            remove_sheet(s)
        if "G1 (LEAD)" in wb.sheetnames:
            wb["G1 (LEAD)"]["D17"] = 0.0
    else:
        rebuild_control_subledger("G6.1 - NL Analysis", {"5330", "5730"}, "wage", "Net Wages")

    # 9. PAYE / Social Security (Section G7)
    # The PAYE reconciliation runs on every job with payroll, not only when the books hold a PAYE account (a payroll
    # file with no 5320 in the TB still gets the tab)
    has_payroll_file = db.query(PayrollP32Record.id).filter(PayrollP32Record.engagement_id == engagement.id).first() is not None
    has_paye = any(c in tb_codes_present for c in {"5320", "2210"}) or has_payroll_file
    if not has_paye:
        for s in ["G7-PAYE liabilities", "G7.1 - NL Analysis"]:
            remove_sheet(s)
        if "G1 (LEAD)" in wb.sheetnames:
            wb["G1 (LEAD)"]["D19"] = 0.0
    else:
        rebuild_control_subledger("G7.1 - NL Analysis", {"5320", "5720"}, "paye", "PAYE Liabilities")

    # 10. Pension Payable (Section G8)
    has_pension = bool(pension_names)
    if not has_pension:
        for s in ["G8-Pension Payable", "G8.1 - NL Analysis"]:
            remove_sheet(s)
        if "G1 (LEAD)" in wb.sheetnames:
            wb["G1 (LEAD)"]["D21"] = 0.0
    else:
        rebuild_control_subledger("G8.1 - NL Analysis", set(), "", "Pension Payable", line_filter=is_pension_line)

    build_payroll()
