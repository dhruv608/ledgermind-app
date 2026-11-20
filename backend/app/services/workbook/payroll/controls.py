"""The payroll control tabs' parts: the lead (b/fwd, movement, journals, c/fwd), its link to G1, the month-by-month
control table, and small helpers."""

from typing import Any, Dict, List, Tuple

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from backend.app.services.papers.payroll_months import month_end, month_rows, opening_owed
from backend.app.services.papers.payroll_months import other_entries as _other_entries
from backend.app.services.workbook.balance_tabs.common import on_tab
from backend.app.services.workbook.balance_tabs.t_shape import t_account


def write_control_lead(p, ws, codes: List[str], rows: Dict[str, str], col: str, total_cell: str,
                       nl: str = "") -> Dict[str, Any]:
    """b/fwd, TTB movement, journals and c/fwd of a payroll control account, as amounts owed (credit +). With the
    ETB reading the ledger: the lead lines (balance_tabs.lead_lines), the NL tab's lines as the movement;
    returns {"bf", "cf": cell, "end": row} (empty otherwise)."""
    accounting_total_border, bold_font, ctx = p.accounting_total_border, p.bold_font, p.ctx
    if ctx.tb_kind:
        for r in range(7, 21):
            for c in range(1, 7):
                if type(ws.cell(row=r, column=c)).__name__ != "MergedCell":
                    ws.cell(row=r, column=c).value = None
        # The account as one T with its lines named, as the screen shows it: what is
        # still owed is the c/d on the debit side; links read it as owed + (negative = overpaid)
        for c in range(1, 8):                 # the template's '£' headings above its lead column
            if ws.cell(row=6, column=c).value == "£":
                ws.cell(row=6, column=c).value = None
        t = t_account(ctx, ws, [int(c) for c in codes], top=7, owed=True)
        return {"bf": t["bf_s"], "cf": t["cf_s"], "end": t["end"], "tab": ws.title}

    def etb(c: str) -> str:
        return "+".join(f"SUMIF('B1-ETB'!$A:$A,{code},'B1-ETB'!${c}:${c})" for code in codes) or "0"

    def ttb(c: str) -> str:
        return "+".join(f"SUMIF(TTB!$A:$A,{code},TTB!${c}:${c})" for code in codes) or "0"

    ws[f"B{rows['bf']}"] = "Balance b/fwd"
    ws[f"{col}{rows['bf']}"] = f"=({etb('G')})-({etb('F')})"
    ws[f"B{rows['ttb']}"] = "Movement per TTB"
    ws[f"{col}{rows['ttb']}"] = f"=({ttb('G')})-({ttb('F')})"
    ws[f"B{rows['jnl']}"] = "Adjusting journals (B2)"
    ws[f"{col}{rows['jnl']}"] = f"=({etb('K')})-({etb('J')})"
    ws[f"B{rows['cf']}"] = "Balance c/fwd - still owed (negative = overpaid)"
    ws[total_cell] = f"=SUM({col}{rows['bf']}:{col}{rows['jnl']})"
    ws[total_cell].font = bold_font
    ws[total_cell].border = accounting_total_border
    return {}


def lead_to_g1(p, row: int, lead: Dict[str, Any], tab: str) -> None:
    """G1 reads the lead's c/fwd and b/fwd (last year) where the lead lines put them."""
    wb = p.wb
    if lead and "G1 (LEAD)" in wb.sheetnames:
        wb["G1 (LEAD)"][f"D{row}"] = f"={lead_link(lead, 'cf', tab)}"
        wb["G1 (LEAD)"][f"E{row}"] = f"={lead_link(lead, 'bf', tab)}"


def lead_link(lead: Dict[str, Any], key: str, tab: str) -> str:
    """The lead's b/f or c/d read from another tab (owed +)."""
    return on_tab(tab, lead[key])


def write_control_table(p, ws, start_row: int, title: str, per_month, opening: float, owed_label: str,
                        journal: Tuple[float, float] = (0.0, 0.0), allowance=None, allowance_journal: float = 0.0,
                        other: float = 0.0, per_report=None, report_label: str = "", status=None) -> int:
    """Month by month: owed (credits), employment allowance (PAYE only), paid or cleared (debits), balance at
    month end and a note; then the adjusting journals (B2), so the last balance is the lead's c/fwd. With a payroll
    report, each month's owed is tied to it: per the report, and books less the report."""
    accounting_total_border, bold_font, payroll_months = p.accounting_total_border, p.bold_font, p.payroll_months
    report_notes = p.report_notes
    ws.cell(row=start_row, column=1, value=title).font = bold_font
    head = start_row + 1
    names = ["Month", owed_label] + (["Employment allowance"] if allowance is not None else []) + \
            ["Paid / cleared", "Balance at month end", "Note"] + \
            ([f"{report_label} per payroll report", "Difference (books less report)"] if per_report else []) + \
            (["Due by", "Status"] if status is not None else [])
    col = {n: i for i, n in enumerate(names, 1)}
    c_rep = col.get(f"{report_label} per payroll report")
    c_owed, c_paid, c_bal, c_note = col[owed_label], col["Paid / cleared"], col["Balance at month end"], col["Note"]
    c_ea = col.get("Employment allowance")
    L = get_column_letter
    for n, c in col.items():
        ws.cell(row=head, column=c, value=n).font = bold_font
    ws.cell(row=head + 1, column=1, value="Balance b/fwd")
    ws.cell(row=head + 1, column=c_bal, value=round(opening, 2))

    def balance_formula(r: int) -> str:
        ea_part = f"-{L(c_ea)}{r}" if c_ea else ""
        return f"={L(c_bal)}{r - 1}+{L(c_owed)}{r}{ea_part}-{L(c_paid)}{r}"

    # Each month's figures and note (services/papers/payroll_months.py, shared with the Payroll by month card)
    rows, flags = month_rows(payroll_months, per_month, opening, allowance, allowance_journal)
    differ_months: List[str] = []
    for i, row in enumerate(rows):
        r = head + 2 + i
        ws.cell(row=r, column=1, value=month_end(row["month"])).number_format = "mmm-yy"
        ws.cell(row=r, column=c_owed, value=round(row["owed"], 2))
        if c_ea:
            ws.cell(row=r, column=c_ea, value=round(row["allowance"], 2))
        ws.cell(row=r, column=c_paid, value=round(row["paid"], 2))
        ws.cell(row=r, column=c_bal, value=balance_formula(r))
        if row["note"]:
            ws.cell(row=r, column=c_note, value=row["note"])
        # Due date and status: payments matched by date, oldest owed first
        if status is not None and row["month"] in status:
            due, said = status[row["month"]]
            ws.cell(row=r, column=col["Due by"], value=due).number_format = "dd/mm/yyyy"
            ws.cell(row=r, column=col["Status"], value=said)
        if c_rep:
            on_report = per_report.get(row["month"], 0.0)
            ws.cell(row=r, column=c_rep, value=round(on_report, 2)).number_format = "#,##0.00;(#,##0.00)"
            ws.cell(row=r, column=c_rep + 1, value=f"=ROUND({L(c_owed)}{r}-{L(c_rep)}{r},2)").number_format =                     "#,##0.00;(#,##0.00)"
            if abs(row["owed"] - on_report) >= 1:
                differ_months.append(month_end(row["month"]).strftime("%b-%y"))
    r = head + 2 + len(payroll_months)
    # What the months do not explain, on its own line: the table then ends at the lead's c/fwd from the lead's b/fwd
    if abs(other) >= 0.005:
        ws.cell(row=r, column=1, value="Other entries not in the months above (other dates, opening lines)")
        ws.cell(row=r, column=c_owed, value=round(other, 2) if other > 0 else None)
        ws.cell(row=r, column=c_paid, value=round(-other, 2) if other < 0 else None)
        ws.cell(row=r, column=c_bal, value=balance_formula(r))
        ws.cell(row=r, column=c_note, value="Check these entries in the nominal ledger tab")
        flags += 1
        r += 1
    ws.cell(row=r, column=1, value="Adjusting journals (B2)")
    ws.cell(row=r, column=c_owed, value=round(journal[0], 2))
    if c_ea:
        ws.cell(row=r, column=c_ea, value=round(allowance_journal, 2))
    ws.cell(row=r, column=c_paid, value=round(journal[1], 2))
    ws.cell(row=r, column=c_bal, value=balance_formula(r))
    tot = r + 1
    ws.cell(row=tot, column=1, value="Total").font = bold_font
    for c in [c_owed, c_paid] + ([c_ea] if c_ea else []) + ([c_rep, c_rep + 1] if c_rep else []):
        cell = ws.cell(row=tot, column=c, value=f"=SUM({L(c)}{head + 2}:{L(c)}{tot - 1})")
        cell.font = bold_font
        cell.border = accounting_total_border
    if c_rep:
        cell = ws.cell(row=tot + 1, column=1, value=(
            f"{report_label} per the books and the payroll report differ in {', '.join(differ_months)}: check the "
            f"payroll journals for those months." if differ_months else
            f"{report_label} per the books agrees with the payroll report every month."))
        cell.font = Font(name="Calibri", size=10, italic=True, color="FFC00000" if differ_months else None)
        if differ_months:
            report_notes.append(f"{report_label}: books and payroll report differ in {len(differ_months)} month(s) "
                                f"({ws.title})")
            # On A0 as an amber check, so the tab's header does not say every check agrees
            ws.cell(row=tot + 2, column=1, value=("Check: months where the books and the payroll report differ, "
                                                  "unexplained (must be nil)")).font = bold_font
            diffs = f"{L(c_rep + 1)}{head + 2}:{L(c_rep + 1)}{head + 1 + len(payroll_months)}"
            ws.cell(row=tot + 2, column=c_rep + 1, value=f"=SUMPRODUCT(--(ABS({diffs})>=1))").number_format = "0"
        ws.cell(row=tot, column=c_rep).number_format = ws.cell(row=tot, column=c_rep + 1).number_format =                 "#,##0.00;(#,##0.00)"
    for row in ws.iter_rows(min_row=head + 1, max_row=tot, min_col=2, max_col=c_bal):
        for cell in row:
            cell.number_format = "#,##0.00;(#,##0.00)"
    if c_ea:
        # Where the employment allowance comes from, so it can be traced
        from backend.app.services.papers.payroll_months import allowance_journal_numbers
        in_ledger = round(sum((allowance or {}).values()), 2)
        numbers = allowance_journal_numbers(getattr(p, "journals", None) or [])
        if in_ledger >= 0.005 or allowance_journal >= 0.005:
            parts = []
            if in_ledger >= 0.005:
                parts.append(f"£{in_ledger:,.2f} from the ledger lines on this account described 'employment "
                             f"allowance' (the months above; the lines are on G7.1 NL Analysis)")
            if allowance_journal >= 0.005:
                parts.append(f"£{allowance_journal:,.2f} from adjusting journal(s) "
                             + (", ".join(str(n) for n in numbers) if numbers else "")
                             + " on the Journals tab (B2): Dr PAYE / NI, Cr employer's NI")
            ws.cell(row=tot + 4, column=1, value="Employment allowance: " + "; ".join(parts) + ".").font = Font(
                name="Calibri", size=10, italic=True)
        else:
            ws.cell(row=tot + 4, column=1, value=(
                "Employment allowance: none in the ledger (no line described 'employment allowance') and no "
                "adjusting journal.")).font = Font(name="Calibri", size=10, italic=True)
    return flags


def clear_from(p, ws, first_row: int, last_col: int = 40) -> None:
    for row in ws.iter_rows(min_row=first_row, max_row=max(ws.max_row, 40), max_col=last_col):
        for cell in row:
            cell.value = None
            cell.hyperlink = None


def tab_opening(p, select_record, codes) -> float:
    ctx, tb_records = p.ctx, p.tb_records
    return opening_owed(tb_records, select_record, codes, getattr(ctx, "opening_by_code", None) or {})


def other_entries(p, per_month, select_record, opening: float, allowance=None) -> float:
    tb_records = p.tb_records
    return _other_entries(tb_records, per_month, select_record, opening, allowance)
