"""The payroll tabs: G6.2 summary, G6.3 employees, G6 net wages, G7 PAYE / NI and G8 pension."""

from typing import Any, Dict, Tuple

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from backend.app.services.workbook.payroll.controls import lead_link
from backend.app.services.mapping.chart_lookup import NET_WAGES, PAYE_NIC
from backend.app.services.papers.payroll_months import (COST_COLS, EMPLOYMENT_ALLOWANCE, by_codes, dated_payments, month_end,
                                                 month_status, next_year_rows)
from backend.app.services.papers.payroll_months import series as payroll_series


LEDGER_TAB = "G6.2.1 - Payroll per ledger"
DIFF_TAB = "G6.2.2 - Payroll differences"


def _new_tab(wb, title: str, at: int, ref: str):
    """A payroll tab of its own, placed after G6.2, with the client heading the other tabs carry."""
    if title in wb.sheetnames:
        del wb[title]
    ws = wb.create_sheet(title, at)
    ws["A1"] = "=A!B2"
    ws["A2"] = "='Notes & Queries'!A2"
    ws["E1"] = ref
    return ws


def _accounts_of(tx_rows, pick, month_of) -> str:
    """The ledger accounts (code and the client's name) whose lines this year make up a column."""
    found = sorted({f"{tx[1]} {tx[3]}".strip() for tx in tx_rows if month_of(tx) is not None and pick(tx)})
    return "; ".join(found)


def build_payroll(p) -> None:
    accounting_total_border, bold_font, clear_from = p.accounting_total_border, p.bold_font, p.clear_from
    closing_owed, db, directors_per_file, engagement = p.closing_owed, p.db, p.directors_per_file, p.engagement
    is_pension_line, journal_allowance, journal_totals = p.is_pension_line, p.journal_allowance, p.journal_totals
    lead_to_g1, led, other_entries, payroll_months = p.lead_to_g1, p.led, p.other_entries, p.payroll_months
    payroll_report_lines, pension_codes, pension_names = p.payroll_report_lines, p.pension_codes, p.pension_names
    report_notes, tab_opening, tb_records, tx_rows = p.report_notes, p.tab_opening, p.tb_records, p.tx_rows
    wb, write_control_lead, write_control_table = p.wb, p.write_control_lead, p.write_control_table
    write_directors, write_payroll_report = p.write_directors, p.write_payroll_report
    month_of = p.month_of
    months_data = payroll_series(led, pension_names)
    net_pay, paye, paye_allowance = months_data["net_pay"], months_data["paye"], months_data["paye_allowance"]
    pension = months_data["pension"]
    # A director's net pay posted straight to the director's loan account: it explains a month whose cost is
    # higher than what is owed out through net wages
    dla_pay = months_data["dla_pay"]
    report_lines = payroll_report_lines()

    # A payroll file that gives no net pay while it pays gross (gross, employer NI and pension only) does not give
    # the employee's side (tax, employee NI, student loan and pension, net pay): those figures are
    # not compared with the books, rather than shown as nil against the books' whole amount
    employee_side = {"tax_deducted", "employee_nic", "student_loan", "pension_employee", "net_pay"}
    no_employee_side = bool(report_lines) and abs(sum(float(p.net_pay or 0) for p in report_lines)) < 0.005 and         abs(sum(float(p.gross_pay or 0) for p in report_lines)) >= 1

    def on_report(*fields):
        """The payroll report's total of these fields per month (None with no report: nothing to tie to)."""
        if not report_lines or (no_employee_side and employee_side & set(fields)):
            return None
        out = {mo: 0.0 for mo in payroll_months}
        for p in report_lines:
            mo = (p.period_end.year, p.period_end.month)
            if mo in out:
                out[mo] += sum(float(getattr(p, f) or 0) for f in fields)
        return out

    # The report is the base: a month's payroll journal debits are netted, or left as cleared where the report shows
    # the month without them (payroll_months.follow_report)
    from backend.app.services.papers.payroll_months import EMPLOYMENT_ALLOWANCE as _EA, follow_report, journal_debits
    paye_line = lambda tx: tx[1] == str(PAYE_NIC) and not _EA.search(str(tx[5]))
    net_pay = follow_report(net_pay, journal_debits(led, by_codes(NET_WAGES)), on_report("net_pay"))
    paye = follow_report(paye, journal_debits(led, paye_line),
                         on_report("tax_deducted", "employee_nic", "employer_nic", "student_loan"))
    pension = follow_report(pension, journal_debits(led, is_pension_line),
                            on_report("pension_employee", "pension_employer"))

    dla_months: Dict[Tuple[int, int], float] = {}

    # G6.2 payroll summary by month: the payroll report first, as it is the base for every payroll figure (the
    # liability is recognised from it; the ledger shows how it was posted and cleared), then the
    # ledger's summary, then the directors' pay
    if "G6.2 - Payroll summary" in wb.sheetnames:
        ws = wb["G6.2 - Payroll summary"]
        clear_from(ws, 5)
        ws["A1"] = "=A!B2"
        ws["A2"] = "='Notes & Queries'!A2"
        director_months = {}
        if db is not None and report_lines:
            from backend.app.models.director_pay import PayrollDirectorMonth
            for m in db.query(PayrollDirectorMonth).filter(PayrollDirectorMonth.engagement_id == engagement.id):
                key = (m.period_end.year, m.period_end.month)
                director_months[key] = director_months.get(key, 0.0) + float(m.gross_pay)
        cost_cols = COST_COLS
        costs = months_data["costs"]
        # Three tabs: G6.2 the payroll report, G6.2.1 the ledger, G6.2.2 the report v the ledger
        at = wb.sheetnames.index("G6.2 - Payroll summary") + 1
        ledger_ws = _new_tab(wb, LEDGER_TAB, at, "G6.2.1")
        diff_ws = _new_tab(wb, DIFF_TAB, at + 1, "G6.2.2") if report_lines else None
        report_end = 4
        if report_lines:
            ws["A4"] = "Payroll - Summary (from the payroll report)"
            report_end = write_payroll_report(ws, 6, report_lines, costs, net_pay, paye, pension, director_months,
                                              diff_ws=diff_ws)
        else:
            ws["A4"] = "No payroll report uploaded: the payroll from the ledger is on G6.2.1."
        report_ws, ws = ws, ledger_ws
        top = 4
        ws.cell(row=top, column=1, value="Payroll - Summary (from the ledger)").font = bold_font
        heads_row, first = top + 2, top + 4
        heads = ["Month"] + [n for n, _ in cost_cols] + ["Total cost", "Net pay", "PAYE / NI", "Pension", "Total owed out",
                                                         "Difference", "Paid through director's DLA", "Still unexplained"]
        for c, text in enumerate(heads, 1):
            ws.cell(row=heads_row, column=c, value=text).font = bold_font
        # The ledger accounts each column is taken from, so every figure can be traced to the GL
        sources = [by_codes(*codes) for _, codes in cost_cols] + [None, by_codes(NET_WAGES), lambda tx: tx[1] == str(PAYE_NIC),
                                                                  is_pension_line]
        ws.cell(row=heads_row + 1, column=1, value="Taken from").font = Font(name="Calibri", size=9, italic=True)
        for c, pick in enumerate(sources, 2):
            text = "B to E" if pick is None else _accounts_of(tx_rows, pick, month_of) or "nothing in the ledger"
            cell = ws.cell(row=heads_row + 1, column=c, value=text)
            cell.font = Font(name="Calibri", size=9, italic=True)
        for c, text in ((10, "G to I"), (11, "F - J"), (12, "director's loan account lines naming the payroll"),
                        (13, "K - L")):
            ws.cell(row=heads_row + 1, column=c, value=text).font = Font(name="Calibri", size=9, italic=True)
        # Some clients pay wages straight from the bank, with no net wages account: then cost vs owed-out
        # cannot be checked month by month (the payroll report comparison above is the check)
        has_net_wages = any(abs(net_pay[mo][0]) >= 0.01 for mo in payroll_months)
        for i, mo in enumerate(payroll_months):
            r = first + i
            ws.cell(row=r, column=1, value=month_end(mo)).number_format = "mmm-yy"
            for j, series in enumerate(costs):
                ws.cell(row=r, column=2 + j, value=round(series[mo][0], 2))
            ws.cell(row=r, column=6, value=f"=SUM(B{r}:E{r})")
            ws.cell(row=r, column=7, value=round(net_pay[mo][0], 2))
            ws.cell(row=r, column=8, value=round(paye[mo][0] - paye_allowance[mo], 2))
            ws.cell(row=r, column=9, value=round(pension[mo][0], 2))
            ws.cell(row=r, column=10, value=f"=SUM(G{r}:I{r})")
            ws.cell(row=r, column=11, value=f"=ROUND(F{r}-J{r},2)")
            # Only when the month is out and the DLA payroll entry is what is missing from net wages
            gap = round(sum(sr[mo][0] for sr in costs) - net_pay[mo][0] - paye[mo][0] + paye_allowance[mo] - pension[mo][0], 2)
            via_dla = round(dla_pay[mo][0], 2)
            settled = via_dla if abs(gap) >= 1 and via_dla and abs(gap - via_dla) < 1 else 0.0
            dla_months[mo] = settled
            ws.cell(row=r, column=12, value=settled or None)
            ws.cell(row=r, column=13, value=f"=ROUND(K{r}-L{r},2)")
            if not has_net_wages:
                for c in range(7, 14):
                    ws.cell(row=r, column=c).value = None   # (cell(value=None) leaves the old value)
        tot = first + len(payroll_months)
        ws.cell(row=tot, column=1, value="Total").font = bold_font
        for c in range(2, 14 if has_net_wages else 7):
            letter = get_column_letter(c)
            cell = ws.cell(row=tot, column=c, value=f"=SUM({letter}{first}:{letter}{tot - 1})")
            cell.font = bold_font
            cell.border = accounting_total_border
        for row in ws.iter_rows(min_row=first, max_row=tot, min_col=2, max_col=13):
            for cell in row:
                cell.number_format = "#,##0.00;(#,##0.00)"
        ws.cell(row=tot + 3, column=1, value=(
            "PAYE / NI is shown after any employment allowance booked in the ledger (it lowers employer NI and the amount owed)."))
        ws.cell(row=tot + 2, column=1, value=(
            "Each month the payroll cost (gross pay + employer NI + employer pension) should equal what is owed out "
            "(net pay + PAYE/NI + pension). A difference usually means a payroll journal is missing, doubled or "
            "posted to another account. Tax, employee NI and student loan come from the payroll report (above, once uploaded). "
            "'Paid through director's DLA': the director's net pay was posted straight to the director's loan account "
            "instead of net wages (flag: salary settled through the DLA; check the DLA)."))
        if not has_net_wages:
            ws.cell(row=top + 3, column=7, value=(
                "No net wages account in this client's books (wages paid straight from the bank), so cost vs "
                "amounts owed cannot be checked month by month: see the payroll report against the books above."))
        mismatched = 0 if not has_net_wages else sum(
            1 for mo in payroll_months
            if abs(sum(s[mo][0] for s in costs) - net_pay[mo][0] - paye[mo][0] + paye_allowance[mo] - pension[mo][0]
                   - dla_months.get(mo, 0.0)) >= 1)
        via_dla_months = [mo for mo in payroll_months if dla_months.get(mo)]
        if via_dla_months:
            report_notes.append(
                f"Director's salary settled through the DLA in {len(via_dla_months)} month(s), "
                f"£{sum(dla_months[mo] for mo in via_dla_months):,.2f}: check the DLA (G6.2.1)")
        if mismatched:
            report_notes.append(f"Payroll cost and amounts owed differ in {mismatched} month(s) (G6.2.1)")
        for col, width in zip("ABCDEFGHIJKLM", (12, 16, 16, 14, 16, 14, 14, 14, 14, 14, 12, 18, 14)):
            ws.column_dimensions[col].width = width
        # The payroll report's own checks stay on G6.2, after the report
        ws, next_at = report_ws, report_end + 3
        if report_lines and not has_net_wages:
            next_at = p.write_net_pay_paid(ws, next_at, report_lines) + 3
        directors = directors_per_file()
        if directors is not None:
            books_ref = "'" + LEDGER_TAB + f"'!B{tot}"
            write_directors(ws, next_at, directors, books_ref, sum(costs[0][mo][0] for mo in payroll_months),
                            director_months, {mo: costs[0][mo][0] for mo in payroll_months})

    # G6.3 average employees: not in the ledger
    if "G6.3 - Avg. No. of Employee" in wb.sheetnames:
        ws = wb["G6.3 - Avg. No. of Employee"]
        paid_by_month = {mo: {p.employee_name for p in report_lines
                              if (p.period_end.year, p.period_end.month) == mo and float(p.gross_pay or 0) > 0}
                         for mo in payroll_months}
        # The payroll file's own number of employees (a summary of monthly totals names nobody)
        from backend.app.models.payroll_headcount import PayrollHeadcount
        from sqlalchemy import select as sql_select       # 'select' is a local name below
        heads = db.execute(sql_select(PayrollHeadcount).where(
            PayrollHeadcount.engagement_id == engagement.id)).scalars().all() if db is not None else []
        by_month = {(h.period_end.year, h.period_end.month): float(h.count) for h in heads if h.period_end}
        year_average = next((float(h.count) for h in heads if h.period_end is None), None)
        named = report_lines and any(p.employee_name != "All employees" for p in report_lines)
        for i, mo in enumerate(payroll_months):
            ws.cell(row=8 + i, column=1, value=month_end(mo)).number_format = "mmm-yy"
            count = (by_month.get(mo) if by_month else year_average if year_average and not named
                     else len(paid_by_month[mo]) if report_lines else None)
            ws.cell(row=8 + i, column=3, value=count)
        if by_month or (year_average and not named):
            ws["A22"] = ("Employees each month, from the payroll report's number of employees" if by_month else
                         f"The payroll report's average number of employees for the year ({year_average:g}).")
        elif report_lines:
            ws["A22"] = "Employees paid each month, from the payroll report (G6.2)."
        else:
            ws["A22"] = "Enter the number of employees each month from the payroll records (not in the ledger)."
            report_notes.append("Average number of employees not entered (G6.3)")


    # Next year's ledger, when uploaded: payments after the year end shown against the months owed
    after_rows = next_year_rows(str(engagement.id), db)

    # G6 net wages
    if "G6 - Net Wages" in wb.sheetnames:
        ws = wb["G6 - Net Wages"]
        clear_from(ws, 8, 16)
        ws["E7"] = "£"
        ws["F7"] = "£"
        lead = write_control_lead(ws, [str(NET_WAGES)], {"bf": "9", "ttb": "11", "jnl": "13", "cf": "15"}, "F", "F15",
                                  nl="G6.1 - NL Analysis")
        lead_to_g1(17, lead, "G6 - Net Wages")
        p.ctx.schedule_cf[NET_WAGES] = (lead_link(lead, "cf", "G6 - Net Wages") if lead else "'G6 - Net Wages'!F15", -1)    # owed +
        if not report_lines:
            # Never an unexplained tab: no payroll report, so net pay per employee is not reconciled
            ws["A5"] = ("No payroll report uploaded: the net wages are checked from the ledger only (G6.2.1). Upload the payroll summary to reconcile net pay per employee to the bank.")
            ws["A5"].font = Font(name="Calibri", size=10, italic=True, color="FFC00000")
        select = lambda t: t.std_code == NET_WAGES
        opening = tab_opening(select, [NET_WAGES])
        flags = write_control_table(ws, max(19, lead.get("end", 0) + 3), "Net pay by month (G6.1)", net_pay, opening, "Net pay posted",
                                    journal=journal_totals({str(NET_WAGES)}),
                                    other=other_entries(net_pay, select, opening),
                                    per_report=on_report("net_pay"), report_label="Net pay",
                                    status=month_status(payroll_months, net_pay, opening,
                                                        dated_payments(tx_rows, by_codes(NET_WAGES)), "net",
                                                        engagement.period_end_date,
                                                        later=dated_payments(after_rows, by_codes(NET_WAGES))))
        if flags:
            report_notes.append(f"Net wages: {flags} month(s) to look at (G6)")

    # G7 PAYE / NI
    if "G7-PAYE liabilities" in wb.sheetnames:
        ws = wb["G7-PAYE liabilities"]
        clear_from(ws, 7, 16)
        ws["D6"] = "£"
        ws["E6"] = "£"
        lead = write_control_lead(ws, [str(PAYE_NIC)], {"bf": "8", "ttb": "10", "jnl": "12", "cf": "14"}, "E", "D14",
                                  nl="G7.1 - NL Analysis")
        lead_to_g1(19, lead, "G7-PAYE liabilities")
        p.ctx.schedule_cf[PAYE_NIC] = (lead_link(lead, "cf", "G7-PAYE liabilities") if lead else "'G7-PAYE liabilities'!D14", -1)
        from backend.app.services.mapping.chart_lookup import foreign_tax_on_paye_code
        foreign = foreign_tax_on_paye_code(tb_records)
        if foreign:
            # Tax owed abroad on the PAYE code ('Foreign tax'): named as the client names it, not PAYE
            ws["A5"] = (f"{PAYE_NIC} holds '{foreign}': tax owed abroad, not PAYE and NI. It is agreed to the "
                        f"overseas tax assessments, not the HMRC PAYE statement (review point U-PAY-024).")
            ws["A5"].font = Font(name="Calibri", size=10, italic=True, color="FFC00000")
            if "G1 (LEAD)" in wb.sheetnames:
                wb["G1 (LEAD)"]["B19"] = foreign[:60]
        select = lambda t: t.std_code == PAYE_NIC
        ea_journal = journal_allowance()
        jnl_cr, jnl_dr = journal_totals({str(PAYE_NIC)})
        opening = tab_opening(select, [PAYE_NIC])
        flags = write_control_table(ws, max(18, lead.get("end", 0) + 3), "PAYE / NI by month (G7.1)", paye, opening,
                                    "PAYE / NI owed", journal=(jnl_cr, jnl_dr - ea_journal),
                                    allowance=paye_allowance, allowance_journal=ea_journal,
                                    other=other_entries(paye, select, opening, paye_allowance),
                                    per_report=on_report("tax_deducted", "employee_nic", "employer_nic", "student_loan"),
                                    report_label="PAYE / NI",
                                    status=month_status(payroll_months, paye, opening, dated_payments(
                                        tx_rows, lambda tx: tx[1] == str(PAYE_NIC)
                                        and not EMPLOYMENT_ALLOWANCE.search(str(tx[5]))), "paye",
                                        engagement.period_end_date, allowance=paye_allowance,
                                        later=dated_payments(after_rows, lambda tx: tx[1] == str(PAYE_NIC)
                                                             and not EMPLOYMENT_ALLOWANCE.search(str(tx[5])))))
        if flags:
            report_notes.append(f"PAYE: {flags} month(s) to look at (G7)")

    # G8 pension
    if "G8-Pension Payable" in wb.sheetnames:
        ws = wb["G8-Pension Payable"]
        clear_from(ws, 7, 16)
        ws["D6"] = "£"
        ws["E6"] = "£"
        select = lambda t: t.raw_account_name in pension_names
        # A pension account on a code other accounts use too (5350 other creditors): the code's total in the ETB
        # would bring every other creditor in, so the lead is the pension accounts' own figures
        shared = any(str(t.std_code) in pension_codes and t.raw_account_name not in pension_names for t in tb_records)
        lead: Dict[str, Any] = {}
        if shared:
            chosen = [t for t in tb_records if select(t)]
            opening = -sum(float(t.opening_amount or 0) for t in chosen)
            closing = closing_owed(select)
            ws["B8"] = "Balance b/fwd"
            ws["E8"] = round(opening, 2)
            ws["B10"] = "Movement in the year"
            ws["E10"] = round(closing - opening, 2)
            ws["B11"] = "Adjusting journals (B2)"
            ws["E11"] = 0
            ws["B12"] = "Balance c/fwd - still owed (negative = overpaid)"
            ws["D12"] = "=SUM(E8:E11)"
            ws["D12"].font = bold_font
            ws["D12"].border = accounting_total_border
            for a in ("E8", "E10", "E11", "D12"):
                ws[a].number_format = "#,##0.00;(#,##0.00)"
            jnl = (0.0, 0.0)
        else:
            lead = write_control_lead(ws, pension_codes, {"bf": "8", "ttb": "10", "jnl": "11", "cf": "12"}, "E", "D12")
            opening = tab_opening(select, pension_codes)
            jnl = journal_totals(set(pension_codes))
            # G1 reads the lead's own c/fwd, as net wages and PAYE do (D12 is empty in the ledger layout)
            lead_to_g1(21, lead, "G8-Pension Payable")
        flags = write_control_table(ws, max(16, (lead.get("end", 0) + 3) if not shared else 16), "Pension by month (G8.1)", pension, opening, "Pension owed",
                                    journal=jnl, other=other_entries(pension, select, opening),
                                    per_report=on_report("pension_employee", "pension_employer"), report_label="Pension",
                                    status=month_status(payroll_months, pension, opening,
                                                        dated_payments(tx_rows, is_pension_line), "pension",
                                                        engagement.period_end_date,
                                                        later=dated_payments(after_rows, is_pension_line)))
        if shared:
            ws["A36"] = ("Note: the pension account shares its code with other accounts in the ETB (other creditors); "
                         "the figures above are the pension account(s) alone: " + ", ".join(sorted(pension_names)) + ".")
        if flags:
            report_notes.append(f"Pension: {flags} month(s) to look at (G8)")
