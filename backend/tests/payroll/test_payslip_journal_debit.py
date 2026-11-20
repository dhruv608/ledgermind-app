"""A journal's debit on a payroll control account lowers what is owed; it is not a payment
(the payroll journal posts the cost and liabilities, the bank the payments)."""
from backend.app.services.papers.payroll_months import LedgerMonths, dated_payments


def test_payslip_debit_lowers_owed_not_paid():
    rows = [("31/12/2024", "5320", "", "PAYE/NI", "Manual Journal", "(1) - Dec 24 Payslip for A", "", 0.0, 300.0),
            ("31/12/2024", "5320", "", "PAYE/NI", "Manual Journal", "(1) - Dec 24 Payslip for B", "", 41.8, 0.0),
            ("22/12/2024", "5320", "", "PAYE/NI", "Spend Money", "HMRC PAYE", "", 200.0, 0.0),
            ("23/12/2024", "5320", "", "PAYE/NI", "Manual Journal", "PAYE paid by the director", "", 50.0, 0.0)]
    got = LedgerMonths(rows, [(2024, 12)]).monthly(lambda tx: tx[1] == "5320", credit_side=True, journals_net=True)
    assert got[(2024, 12)] == [258.2, 250.0]       # owed 300 - 41.80; paid 200 by bank + 50 settled by the director


def test_any_journal_debit_is_part_of_the_payroll_not_a_payment():
    # A per-employee journal line (no 'payslip' word), a reclass and a Sage journal debit: owed goes down, nothing paid
    rows = [("31/01/2025", "5330", "", "Net wages", "Journal Entry", "Payroll January", "", 0.0, 2000.0),
            ("31/01/2025", "5330", "", "Net wages", "Journal Entry", "Sophia Example", "", 100.0, 0.0),
            ("31/01/2025", "5330", "", "Net wages", "JD", "PAYE DUE", "", 50.0, 0.0),
            ("25/01/2025", "5330", "", "Net wages", "Spend Money", "Sophia Example", "", 1850.0, 0.0)]
    pick = lambda tx: tx[1] == "5330"
    got = LedgerMonths(rows, [(2025, 1)]).monthly(pick, credit_side=True, journals_net=True)
    assert got[(2025, 1)] == [1850.0, 1850.0]
    assert [a for _, a in dated_payments(rows, pick)] == [1850.0]
    # Without the switch (another account) the journal debits stay as they are
    assert LedgerMonths(rows, [(2025, 1)]).monthly(pick, credit_side=True)[(2025, 1)] == [2000.0, 2000.0]


def test_overpaid_note_only_when_it_lasts():
    """'Paid more than was owed' only when the overpayment is still there two month ends later or at the year end
    (wages paid before the payroll journal each month are timing, not a point)."""
    from backend.app.services.papers.payroll_months import month_rows
    months = [(2025, m) for m in range(1, 6)]
    per_month = {(2025, 1): (50.0, 150.0), (2025, 2): (100.0, 0.0), (2025, 3): (100.0, 100.0),
                 (2025, 4): (100.0, 150.0), (2025, 5): (0.0, 0.0)}
    rows, flags = month_rows(months, per_month, 0.0)
    notes = [r["note"] for r in rows]
    assert notes[0] is None                       # -100 in January, cleared in February: timing
    assert notes[3] == "Paid more than was owed"   # -50 from April, still there at the year end
    assert notes[4] == "Nothing posted this month"


def test_allowance_journals_found_by_number():
    from backend.app.services.papers.payroll_months import allowance_journal_numbers
    journals = [{"no": 3, "code": "5320", "debit": 500.0, "credit": 0}, {"no": 3, "code": "3001", "debit": 0, "credit": 500.0},
                {"no": 4, "code": "5320", "debit": 80.0, "credit": 0}, {"no": 4, "code": "7900", "debit": 0, "credit": 80.0}]
    assert allowance_journal_numbers(journals) == [3]


def test_report_decides_whether_a_journal_debit_is_netted():
    from backend.app.services.papers.payroll_months import follow_report
    per_month = {(2024, 7): [848.46, 775.62], (2024, 8): [1000.0, 900.0]}     # journal debits already netted
    debits = {(2024, 7): 529.18, (2024, 8): 50.0}
    report = {(2024, 7): 1377.64, (2024, 8): 1000.0}
    got = follow_report(per_month, debits, report)
    assert got[(2024, 7)] == [1377.64, 1304.8]     # the report holds July without the debit: it was cleared
    assert got[(2024, 8)] == [1000.0, 900.0]       # August agrees netted: stays netted
    assert follow_report(per_month, debits, None) is per_month


def test_a_payment_moved_by_journal_stays_a_payment():
    rows = [("31/01/2025", "5320", "", "PAYE", "Journal Entry", "Move from NET Wages", "", 3279.31, 0.0),
            ("31/01/2025", "5320", "", "PAYE", "Journal Entry", "Payroll January", "", 0.0, 1065.56)]
    assert [a for _, a in dated_payments(rows, lambda tx: tx[1] == "5320")] == [3279.31]
