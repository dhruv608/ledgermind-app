"""The payroll report and the directors' pay per the payroll file, written on G6.2 against the books."""

import json
import re
from typing import Any, Dict, List

from openpyxl.utils import get_column_letter
from sqlalchemy import select

from backend.app.services.mapping.chart_lookup import NET_WAGES
from backend.app.services.papers.payroll_months import month_end

PAYROLL_FIELDS = ["gross_pay", "tax_deducted", "employee_nic", "employer_nic", "student_loan",
                  "pension_employee", "pension_employer", "net_pay"]
WAGE_PAYMENT_CODES = {str(NET_WAGES), "3000", "3004", "3010", "3014", "3015"}
DIRECTORS_GROSS, STAFF_GROSS = "Directors' gross", "Staff gross"


def payroll_report_lines(p) -> List[Any]:
    """Lines of an uploaded payroll report (one per employee per month) inside this year's months."""
    db, engagement, payroll_months = p.db, p.engagement, p.payroll_months
    if db is None:
        return []
    # (none from a report for another period: the review and the Data check leave it out too, payroll_period.py)
    from backend.app.services.review.payroll_period import usable
    lines = [rec for rec in usable(engagement, db)[0] if rec.employee_name is not None]
    return [rec for rec in lines if rec.period_end and (rec.period_end.year, rec.period_end.month) in payroll_months]


def write_payroll_report(p, ws, start: int, lines, costs, net_pay, paye, pension, director_months=None,
                         diff_ws=None) -> int:
    """The payroll report month by month; totals per employee; and the SOP check: payments into wage accounts to
    people who are not on the payroll. The report against the books goes on its own tab (diff_ws, G6.2.2), each
    report figure taken from this tab by formula (report, ledger and differences on three tabs). director_months:
    the directors' gross by month per the payroll file, shown apart from the staff's. Returns the last row used."""
    PAYROLL_FIELDS, WAGE_PAYMENT_CODES = p.PAYROLL_FIELDS, p.WAGE_PAYMENT_CODES
    accounting_total_border, bold_font, month_of = p.accounting_total_border, p.bold_font, p.month_of
    payroll_months, report_notes, tx_rows = p.payroll_months, p.report_notes, p.tx_rows
    by_month = {mo: {f: 0.0 for f in PAYROLL_FIELDS} for mo in payroll_months}
    paid = {mo: set() for mo in payroll_months}
    for rec in lines:
        mo = (rec.period_end.year, rec.period_end.month)
        for f in PAYROLL_FIELDS:
            by_month[mo][f] += float(getattr(rec, f) or 0)
        if float(rec.gross_pay or 0) > 0:
            paid[mo].add(rec.employee_name)
    L = get_column_letter
    money = "#,##0.00;(#,##0.00)"

    ws.cell(row=start, column=1, value="Per payroll report (checked against the books on G6.2.2)").font = bold_font
    split = bool(director_months)
    report_heads = ["Gross pay"] + ([DIRECTORS_GROSS, STAFF_GROSS] if split else []) + [
        "Tax", "Employee NI", "Employer NI", "Student loan", "Employee pension", "Employer pension", "Net pay"]
    heads = ["Month", "Employees paid"] + report_heads
    col = {h: L(i) for i, h in enumerate(heads, 1)}
    last = len(heads)
    head = start + 1
    for c, text in enumerate(heads, 1):
        ws.cell(row=head, column=c, value=text).font = bold_font
    missing = []
    for i, mo in enumerate(payroll_months):
        r = head + 1 + i
        v = by_month[mo]
        ws.cell(row=r, column=1, value=month_end(mo)).number_format = "mmm-yy"
        ws.cell(row=r, column=2, value=len(paid[mo])).number_format = "0"
        values = [v["gross_pay"]] + ([director_months.get(mo, 0.0), None] if split else []) + [
            v[f] for f in ("tax_deducted", "employee_nic", "employer_nic", "student_loan", "pension_employee",
                           "pension_employer", "net_pay")]
        for j, value in enumerate(values):
            if value is not None:
                ws.cell(row=r, column=3 + j, value=round(value, 2))
        if split:
            ws[f"{col[STAFF_GROSS]}{r}"] = f"=ROUND({col['Gross pay']}{r}-{col[DIRECTORS_GROSS]}{r},2)"
        if not any(abs(v[f]) >= 0.005 for f in PAYROLL_FIELDS) and abs(costs[0][mo][0] + costs[1][mo][0]) >= 0.005:
            missing.append(month_end(mo).strftime("%b-%y"))
    tot = head + 1 + len(payroll_months)
    ws.cell(row=tot, column=1, value="Total").font = bold_font
    for c in range(3, last + 1):
        cell = ws.cell(row=tot, column=c, value=f"=SUM({L(c)}{head + 1}:{L(c)}{tot - 1})")
        cell.font = bold_font
        cell.border = accounting_total_border
    for row in ws.iter_rows(min_row=head + 1, max_row=tot, min_col=3, max_col=last):
        for cell in row:
            cell.number_format = money
    if missing:
        report_notes.append(f"Payroll report missing for {', '.join(missing)} (G6.2)")
        ws.cell(row=tot + 1, column=1, value=f"No payroll report lines for: {', '.join(missing)} (the books show wages these months).")
    if diff_ws is not None:
        write_report_differences(p, diff_ws, ws.title, head, col, by_month, costs, net_pay, paye, pension)

    # Totals per employee
    r0 = tot + 3
    ws.cell(row=r0, column=1, value="Per employee (year)").font = bold_font
    emp_heads = ["Employee", "Months paid", "Gross pay", "Tax", "Employee NI", "Employer NI", "Student loan",
                 "Employee pension", "Employer pension", "Net pay"]
    for c, text in enumerate(emp_heads, 1):
        ws.cell(row=r0 + 1, column=c, value=text).font = bold_font
    employees: Dict[str, Dict[str, float]] = {}
    months_paid: Dict[str, int] = {}
    for rec in lines:
        e = employees.setdefault(rec.employee_name, {f: 0.0 for f in PAYROLL_FIELDS})
        for f in PAYROLL_FIELDS:
            e[f] += float(getattr(rec, f) or 0)
        if float(rec.gross_pay or 0) > 0:
            months_paid[rec.employee_name] = months_paid.get(rec.employee_name, 0) + 1
    for k, (name, e) in enumerate(sorted(employees.items())):
        r = r0 + 2 + k
        ws.cell(row=r, column=1, value=name)
        ws.cell(row=r, column=2, value=months_paid.get(name, 0)).number_format = "0"
        for j, f in enumerate(["gross_pay", "tax_deducted", "employee_nic", "employer_nic", "student_loan",
                               "pension_employee", "pension_employer", "net_pay"]):
            ws.cell(row=r, column=3 + j, value=round(e[f], 2)).number_format = money

    # Payroll SOP: payments into wage accounts to people who are not on the payroll
    r1 = r0 + 3 + len(employees)
    ws.cell(row=r1, column=1, value="Payments to people not on the payroll (wage accounts, bank payments only)").font = bold_font
    tokens = {t for n in employees if n != "All employees" for t in re.findall(r"[a-z]{3,}", n.lower())}
    if not tokens:
        # A report of monthly totals names nobody: nothing to check the payees against (not every payment flagged)
        ws.cell(row=r1 + 1, column=1, value="The payroll report gives monthly totals only and names nobody, so the "
                                             "payees cannot be checked against it.")
        return r1 + 1
    wage_payments = [tx for tx in tx_rows
                     if tx[1] in WAGE_PAYMENT_CODES and tx[7] > 0 and "journal" not in str(tx[4]).lower()
                     and month_of(tx) is not None]
    no_name = [tx for tx in wage_payments if not str(tx[5] or "").strip()]
    flagged = [tx for tx in wage_payments if str(tx[5] or "").strip()
               and not (set(re.findall(r"[a-z]{3,}", str(tx[5]).lower())) & tokens)]
    for c, text in enumerate(["Date", "Account", "Payee / description", "Amount"], 1):
        ws.cell(row=r1 + 1, column=c, value=text).font = bold_font
    for k, tx in enumerate(flagged):
        r = r1 + 2 + k
        ws.cell(row=r, column=1, value=tx[0])
        ws.cell(row=r, column=2, value=f"{tx[1]} {tx[3]}")
        ws.cell(row=r, column=3, value=tx[5])
        ws.cell(row=r, column=4, value=round(tx[7], 2)).number_format = money
    if no_name:
        r_note = r1 + 3 + len(flagged) + (1 if flagged else 0)
        ws.cell(row=r_note, column=1, value=(
            f"{len(no_name)} wage payment(s) totalling {sum(tx[7] for tx in no_name):,.2f} have no payee name in the "
            f"ledger, so they could not be checked against the payroll."))
    if not flagged:
        ws.cell(row=r1 + 2, column=1, value="None: every named payment into the wage accounts is to someone on the payroll.")
    else:
        report_notes.append(f"{len(flagged)} wage payment(s) to people not on the payroll (G6.2)")
        ws.cell(row=r1 + 3 + len(flagged), column=1, value=(
            "Please confirm with the client whether these relate to employees, subcontractors or other payments."))
    return r1 + 4 + len(flagged) + (1 if no_name else 0)


DIFF_PAIRS = [
    # (name, the report's fields, the books' figure)
    ("Gross pay", ("gross_pay",), "gross"),
    ("Net pay", ("net_pay",), "net_pay"),
    ("PAYE / NI", ("tax_deducted", "employee_nic", "employer_nic", "student_loan"), "paye"),
    ("Pension", ("pension_employee", "pension_employer"), "pension"),
    ("Employer NI", ("employer_nic",), "employer_nic"),
    ("Employer pension", ("pension_employer",), "employer_pension"),
]
REPORT_HEAD = {"gross_pay": "Gross pay", "net_pay": "Net pay", "tax_deducted": "Tax", "employee_nic": "Employee NI",
               "employer_nic": "Employer NI", "student_loan": "Student loan", "pension_employee": "Employee pension",
               "pension_employer": "Employer pension"}


def write_report_differences(p, ws, report_title: str, report_head: int, report_col, by_month, costs, net_pay, paye,
                             pension) -> None:
    """G6.2.2: each month, the payroll report (by formula from G6.2) against the books (the ledger, G6.2.1) and the
    difference, for gross pay, net pay, PAYE / NI, pension, employer NI and employer pension. A month the report does not cover is not counted as differing (G6.2 lists it as missing)."""
    accounting_total_border, bold_font, report_notes = p.accounting_total_border, p.bold_font, p.report_notes
    L = get_column_letter
    money = "#,##0.00;(#,##0.00)"
    ref = "'" + report_title.replace("'", "''") + "'!"
    ws["A4"] = "Payroll report v books, month by month"
    ws["A4"].font = bold_font
    ws["A5"] = ("Per report: the payroll report (G6.2). Per books: the ledger (G6.2.1). A difference usually means a "
                "payroll journal is missing, doubled or posted to another account. PAYE / NI per books is before "
                "any employment allowance, as the report gives employer NI before it (G6.2.1 shows it after).")
    heads = ["Month"]
    for name, _, _ in DIFF_PAIRS:
        heads += [f"{name} per report", f"{name} per books", f"{name} difference"]
    head = 7
    for c, text in enumerate(heads, 1):
        ws.cell(row=head, column=c, value=text).font = bold_font
    differ = 0
    for i, mo in enumerate(p.payroll_months):
        r, rr = head + 1 + i, report_head + 1 + i
        v = by_month[mo]
        # Books: gross (directors + staff), net pay, PAYE / NI and pension owed, and the employer's NI and pension
        # costs (ER NI and ER pension per summary against the GL too)
        books = {"gross": costs[0][mo][0] + costs[1][mo][0], "net_pay": net_pay[mo][0], "paye": paye[mo][0],
                 "pension": pension[mo][0], "employer_nic": costs[2][mo][0], "employer_pension": costs[3][mo][0]}
        ws.cell(row=r, column=1, value=month_end(mo)).number_format = "mmm-yy"
        diffs = []
        for k, (_, fields, key) in enumerate(DIFF_PAIRS):
            c = 2 + 3 * k
            ws.cell(row=r, column=c, value="=" + "+".join(f"{ref}{report_col[REPORT_HEAD[f]]}{rr}" for f in fields))
            ws.cell(row=r, column=c + 1, value=round(books[key], 2))
            ws.cell(row=r, column=c + 2, value=f"=ROUND({L(c)}{r}-{L(c + 1)}{r},2)")
            diffs.append(sum(v[f] for f in fields) - books[key])
        if any(abs(v[f]) >= 0.005 for f in p.PAYROLL_FIELDS) and any(abs(d) >= 1 for d in diffs):
            differ += 1
    tot = head + 1 + len(p.payroll_months)
    ws.cell(row=tot, column=1, value="Total").font = bold_font
    for c in range(2, len(heads) + 1):
        cell = ws.cell(row=tot, column=c, value=f"=SUM({L(c)}{head + 1}:{L(c)}{tot - 1})")
        cell.font, cell.border = bold_font, accounting_total_border
    for row in ws.iter_rows(min_row=head + 1, max_row=tot, min_col=2, max_col=len(heads)):
        for cell in row:
            cell.number_format = money
    ws.column_dimensions["A"].width = 12
    for c in range(2, len(heads) + 1):
        ws.column_dimensions[L(c)].width = 14
    if differ:
        report_notes.append(f"Payroll report and books differ in {differ} month(s) (G6.2.2)")


def directors_per_file(p):
    """Directors' pay as the uploaded payroll file gives it (a 'Director Salary' line, a block per director)."""
    db, engagement = p.db, p.engagement
    if db is None:
        return None
    from backend.app.models.director_pay import PayrollDirectorPay
    return db.execute(select(PayrollDirectorPay).where(
        PayrollDirectorPay.engagement_id == engagement.id)).scalars().first()


DIRECTOR_PAY_CODES = {"3010", "3014", "3015", "1450"}      # directors' salaries (and in cost of sales)


def write_directors(p, ws, start: int, directors, books_ref: str, in_books: float, director_months=None,
                    books_by_month=None) -> int:
    """Directors' pay per the payroll file against the directors' accounts in the ledger (column B); with the file's
    months, month by month, and the ledger lines on the directors' accounts in a month holding more than the file
    gives, to reanalyse (directors' pay is split only by the payroll, never by guess).
    Returns the last row used."""
    accounting_total_border, bold_font, report_notes = p.accounting_total_border, p.bold_font, p.report_notes
    money = "#,##0.00;(#,##0.00)"
    people = json.loads(directors.people or "{}")
    ws.cell(row=start, column=1, value="Directors' pay: payroll file v books").font = bold_font
    ws.cell(row=start + 1, column=1, value="Directors' pay per payroll file"
            + (f" ({', '.join(people)})" if people else ""))
    ws.cell(row=start + 1, column=6, value=round(float(directors.gross_pay), 2)).number_format = money
    ws.cell(row=start + 2, column=1, value="Directors' pay per books (G6.2.1)")
    ws.cell(row=start + 2, column=6, value=f"={books_ref}").number_format = money
    gap = float(directors.gross_pay) - in_books
    ws.cell(row=start + 3, column=1, value=(
        "Difference: still in staff wages" if gap >= 1 else
        "Difference: more in the directors' accounts than the payroll gives (reanalyse)" if gap <= -1 else
        "Difference")).font = bold_font
    cell = ws.cell(row=start + 3, column=6, value=f"=ROUND(F{start + 1}-F{start + 2},2)")
    cell.number_format = money
    cell.font = bold_font
    cell.border = accounting_total_border
    ws.cell(row=start + 4, column=1, value=(
        "Directors' pay is shown on its own in the accounts and the directors' remuneration note (CA 2006 s412). A "
        "shortfall is moved from staff wages by the journal on the Journals tab (U-PAY-007); an excess is not moved "
        "by guess: the lines below are reanalysed with the client (salary through the loan account, a missing payroll)."))
    if abs(gap) >= 1:
        report_notes.append(f"Directors' pay per payroll £{float(directors.gross_pay):,.2f} v books "
                            f"£{in_books:,.2f} (G6.2)")
    end = start + 4
    if not director_months or books_by_month is None:
        return end
    # Month by month: per the payroll file v the directors' accounts
    r = start + 6
    ws.cell(row=r, column=1, value="Directors' pay by month: payroll file v books").font = bold_font
    for c, text in enumerate(["Month", "Per payroll file", "Per books", "Books more than the payroll (reanalyse)"], 1):
        ws.cell(row=r + 1, column=c, value=text).font = bold_font
    over_months = []
    for i, mo in enumerate(p.payroll_months):
        row = r + 2 + i
        per_file = round(director_months.get(mo, 0.0), 2)
        per_books = round(books_by_month.get(mo, 0.0), 2)
        ws.cell(row=row, column=1, value=month_end(mo)).number_format = "mmm-yy"
        ws.cell(row=row, column=2, value=per_file).number_format = money
        ws.cell(row=row, column=3, value=per_books).number_format = money
        ws.cell(row=row, column=4, value=f"=ROUND(MAX(0,C{row}-B{row}),2)").number_format = money
        if per_books - per_file >= 1:
            over_months.append(mo)
    total = r + 2 + len(p.payroll_months)
    ws.cell(row=total, column=1, value="Total").font = bold_font
    for c in (2, 3, 4):
        letter = get_column_letter(c)
        cell = ws.cell(row=total, column=c, value=f"=SUM({letter}{r + 2}:{letter}{total - 1})")
        cell.number_format, cell.font, cell.border = money, bold_font, accounting_total_border
    end = total
    if over_months:
        lines = [tx for tx in p.tx_rows if str(tx[1]) in DIRECTOR_PAY_CODES and p.month_of(tx) in over_months]
        r2 = total + 2
        ws.cell(row=r2, column=1, value=(
            "Ledger lines on the directors' accounts in those months, to reanalyse against the payroll")).font = bold_font
        for c, text in enumerate(["Date", "Account", "Description", "Debit", "Credit"], 1):
            ws.cell(row=r2 + 1, column=c, value=text).font = bold_font
        for k, tx in enumerate(lines):
            row = r2 + 2 + k
            ws.cell(row=row, column=1, value=tx[0])
            ws.cell(row=row, column=2, value=f"{tx[1]} {tx[3]}")
            ws.cell(row=row, column=3, value=tx[5])
            ws.cell(row=row, column=4, value=round(tx[7], 2) if tx[7] else None).number_format = money
            ws.cell(row=row, column=5, value=round(tx[8], 2) if tx[8] else None).number_format = money
        end = r2 + 1 + len(lines)
        report_notes.append(f"Directors' accounts hold more than the payroll in {len(over_months)} month(s): "
                            f"reanalyse (G6.2)")
    return end


def write_net_pay_paid(p, ws, start: int, lines) -> int:
    """No net wages account (wages paid straight from the bank into the wage costs): each month's net pay per the
    payroll report against the bank payments into the wage accounts naming the employee (the ledger's description:
    paid lines matched by payee name). What is not paid by the year end is owed as net wages.
    Returns the last row used."""
    from backend.app.services.review.payroll_journals.common import _names_person
    bold_font, accounting_total_border, report_notes = p.bold_font, p.accounting_total_border, p.report_notes
    money = "#,##0.00;(#,##0.00)"
    names = sorted({rec.employee_name for rec in lines if rec.employee_name and rec.employee_name != "All employees"})
    per_report = {mo: 0.0 for mo in p.payroll_months}
    for rec in lines:
        mo = (rec.period_end.year, rec.period_end.month)
        if mo in per_report:
            per_report[mo] += float(rec.net_pay or 0)
    paid = {mo: 0.0 for mo in p.payroll_months}
    for tx in p.tx_rows:
        if (str(tx[1]) in p.WAGE_PAYMENT_CODES and str(tx[1]) != str(NET_WAGES) and tx[7] > 0
                and "journal" not in str(tx[4]).lower() and p.month_of(tx) in paid
                and (not names or any(_names_person(str(tx[5] or ""), n) for n in names))):
            paid[p.month_of(tx)] += tx[7]
    if not any(abs(v) >= 0.005 for v in paid.values()):
        return start - 1
    ws.cell(row=start, column=1, value="Net pay per payroll report v paid from the bank (no net wages account)").font = bold_font
    for c, text in enumerate(["Month", "Net pay per report", "Paid (bank, naming the employee)", "Not paid", "Status"], 1):
        ws.cell(row=start + 1, column=c, value=text).font = bold_font
    for i, mo in enumerate(p.payroll_months):
        r = start + 2 + i
        ws.cell(row=r, column=1, value=month_end(mo)).number_format = "mmm-yy"
        ws.cell(row=r, column=2, value=round(per_report[mo], 2)).number_format = money
        ws.cell(row=r, column=3, value=round(paid[mo], 2)).number_format = money
        ws.cell(row=r, column=4, value=f"=ROUND(B{r}-C{r},2)").number_format = money
        due = per_report[mo] - paid[mo]
        ws.cell(row=r, column=5, value=("Paid" if abs(due) < 1 and per_report[mo] >= 0.005 else
                                        "Not paid" if due >= 1 and paid[mo] < 0.005 else
                                        "Part paid" if due >= 1 else "Paid more than the report" if due <= -1 else None))
    tot = start + 2 + len(p.payroll_months)
    ws.cell(row=tot, column=1, value="Total").font = bold_font
    for c in (2, 3, 4):
        letter = get_column_letter(c)
        cell = ws.cell(row=tot, column=c, value=f"=SUM({letter}{start + 2}:{letter}{tot - 1})")
        cell.number_format, cell.font, cell.border = money, bold_font, accounting_total_border
    unpaid = round(sum(per_report.values()) - sum(paid.values()), 2)
    ws.cell(row=tot + 1, column=1, value=(
        f"Net pay per the report not paid by the year end: £{unpaid:,.2f}. It is owed as net wages: the payroll "
        f"journal for the month(s) the books miss posts it (Journals tab)." if unpaid >= 1 else
        "Every month's net pay per the report was paid from the bank."))
    if unpaid >= 1:
        report_notes.append(f"Net pay per payroll £{unpaid:,.2f} not paid by the year end (G6.2)")
    return tot + 1
