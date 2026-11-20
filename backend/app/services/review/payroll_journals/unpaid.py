"""U-PAY-025 A payroll liability unpaid for more than two months: a query.

Net pay, PAYE / NI and pension owed for a month are normally paid in the next month (PAYE by the 22nd: PAYE manual
PAYE20020; net pay on pay day; pension by the 22nd). A month still owed at the year end whose due date was more than two
months before it is not the usual last-month balance: the client is asked whether it was paid (and how) or is still
owed. The months, amounts and due dates come from the same month tables as the G6 / G7 / G8 tabs (payroll_months), so
the point and the tabs agree. A question only: no journal."""

from datetime import timedelta
from typing import List

from sqlalchemy.orm import Session

from backend.app.models.database import AuditFinding, ClientEngagement
from backend.app.services.review.point_figures import row, table
from backend.app.services.mapping.chart_lookup import NET_WAGES, PAYE_NIC
from backend.app.services.papers.payroll_months import (
    EMPLOYMENT_ALLOWANCE, NOT_PAID, LedgerMonths, _inputs, by_codes, dated_payments, month_end, month_status,
    next_year_rows, opening_owed, pension_accounts, pension_line, series, year_months)

OVERDUE_DAYS = 61            # due more than two months before the year end
MIN_OWED = 50.0              # a month's amount below this is rounding


def unpaid_over_two_months(engagement: ClientEngagement, db: Session) -> List[AuditFinding]:
    if engagement.period_end_date is None:
        return []
    tb_records, tx_rows, _journals, opening_by_code = _inputs(engagement, db)
    months = year_months(engagement.period_end_date)
    pension_names, pension_codes = pension_accounts(tb_records)
    s = series(LedgerMonths(tx_rows, months), pension_names)
    end = engagement.period_end_date
    controls = [
        ("Net wages", "net", s["net_pay"], [NET_WAGES], lambda t: t.std_code == NET_WAGES, by_codes(NET_WAGES), None),
        ("PAYE / NI", "paye", s["paye"], [PAYE_NIC], lambda t: t.std_code == PAYE_NIC,
         lambda tx: tx[1] == str(PAYE_NIC) and not EMPLOYMENT_ALLOWANCE.search(str(tx[5])), s["paye_allowance"]),
    ]
    if pension_names:
        controls.append(("Pension", "pension", s["pension"], [int(c) for c in pension_codes],
                         lambda t: t.raw_account_name in pension_names, pension_line(pension_names), None))
    after_rows = next_year_rows(str(engagement.id), db)       # paid after the year end: no question to ask
    out: List[AuditFinding] = []
    for title, kind, per_month, codes, select, line, allowance in controls:
        if not any(abs(per_month[mo][0]) >= 0.01 for mo in months):
            continue
        opening = opening_owed(tb_records, select, codes, opening_by_code)
        status = month_status(months, per_month, opening, dated_payments(tx_rows, line), kind, end, allowance=allowance,
                              later=dated_payments(after_rows, line))
        late = [(mo, due) for mo, (due, st) in status.items()
                if st == NOT_PAID and due <= end - timedelta(days=OVERDUE_DAYS)
                and per_month[mo][0] - (allowance or {}).get(mo, 0.0) >= MIN_OWED]
        if not late:
            continue
        owed = [(mo, due, round(per_month[mo][0] - (allowance or {}).get(mo, 0.0), 2)) for mo, due in late]
        total = round(sum(a for _, _, a in owed), 2)
        listed = "; ".join(f"{month_end(mo):%B %Y} £{a:,.2f} (due {due:%d/%m/%Y})" for mo, due, a in owed)
        out.append(AuditFinding(
            engagement_id=engagement.id, stage="STAGE_1_ACCOUNTING", procedure_ref="U-PAY-025",
            procedure_name=f"Payroll: {title.lower()}", severity="MEDIUM", source_row_ref=title,
            quantified_amount=total, status="OPEN",
            figures=table(["Month", "Due", "Owed"], [row(f"{month_end(mo):%B %Y}", f"{due:%d/%m/%Y}", a) for mo, due, a in owed]
                          + [row("Unpaid for more than two months", None, total, strong=True)]),
            finding_title=f"{title}: {len(owed)} month(s) unpaid for more than two months, £{total:,.2f}",
            finding_details=(f"{title} owed for these months shows no payment in the books, though each was due more "
                             f"than two months before the year end ({end:%d/%m/%Y}): {listed}. Owed at the year end "
                             f"is normally the last month only. Either it was paid and posted elsewhere (another "
                             f"account, the director's loan, a later payment covering several months), or it is still "
                             f"owed (for PAYE: interest and penalties may follow). Query to the client: Were the "
                             f"{title.lower()} amounts for {', '.join(f'{month_end(mo):%B %Y}' for mo, _, _ in owed)} "
                             f"paid, and if so when and from which account?")))
    return out
