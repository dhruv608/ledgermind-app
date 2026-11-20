"""The firm's payroll summary: the company's total block, then a block per person. The year's pay is counted once:
column markers ('a', 'b') above the total block are not a person, a block that is the sum of the others is the total,
weekly lines ('Week 9 - Ending 1 June, 2024') are dated by the month the week ends in, and 'Weekly' beside a name is
not the name."""
from backend.app.services.ingestion.supplementary.payroll import PayrollParsing

HEAD = ["Months", "Gross Wages", "Employee NI", "TAX", "Net Wages", "Employer NI"]


class _Db:
    def __init__(self):
        self.added = []

    def add(self, x):
        self.added.append(x)

    def query(self, *_):
        return self

    def filter(self, *_):
        return self

    def delete(self, **_):
        return 0

    def commit(self):
        pass


def _read(rows, monkeypatch):
    for name in ("_store_allowance", "_store_headcount"):
        monkeypatch.setattr(PayrollParsing, name, classmethod(lambda cls, *a, **k: None))
    db = _Db()
    rows = [[str(c) if c is not None else "" for c in r] for r in rows]
    PayrollParsing._parse_payroll_summary("e1", rows, db)
    return db.added


def test_markers_above_total_block_not_a_person(monkeypatch):
    recs = _read([["", "", "", "a", "", "b"], HEAD,
                  ["2025-01-01 00:00:00", "1464.32", "0", "0", "1464.32", "0"],
                  ["2025-02-01 00:00:00", "732.16", "0", "0", "732.16", "0"], ["Total", "2196.48"], [],
                  ["Ann Smith"], HEAD, ["2025-01-01 00:00:00", "732.16", "0", "0", "732.16", "0"],
                  ["2025-02-01 00:00:00", "732.16", "0", "0", "732.16", "0"], ["Total"], [],
                  ["Raj Kumar"], HEAD, ["2025-01-01 00:00:00", "732.16", "0", "0", "732.16", "0"], ["Total"]],
                 monkeypatch)
    assert round(sum(r.gross_pay for r in recs), 2) == 2196.48
    assert {r.employee_name for r in recs} == {"Ann Smith", "Raj Kumar"}


def test_weekly_lines_and_frequency_word(monkeypatch):
    head = ["Period", "Gross Pay", "Tax", "Employee NICs", "Net pay", "Employer NICs"]
    recs = _read([["Total Summary"], head,
                  ["Week 9 - Ending 1 June, 2024", "700", "65", "25", "610", "54"],
                  ["Week 10 - Ending 8 June, 2024", "300", "0", "0", "300", "0"], [],
                  ["Employer", "Lee Parker", "Weekly"], head,
                  ["Week 9 - Ending 1 June, 2024", "700", "65", "25", "610", "54"], ["Total"], [],
                  ["Jo Bloggs"], head, ["Week 10 - Ending 8 June, 2024", "300", "0", "0", "300", "0"], ["Total"]],
                 monkeypatch)
    assert round(sum(r.gross_pay for r in recs), 2) == 1000.0
    assert {r.employee_name for r in recs} == {"Lee Parker", "Jo Bloggs"}
    assert {str(r.period_end) for r in recs} == {"2024-06-30"}


def test_total_line_above_a_block_is_not_a_person(monkeypatch):
    # the company's months end with a Total line; the next block's headings sit right under it
    head2 = ["Posted date", "Payment date", "Gross Earnings", "PAYE", "EE NIC", "Net Pay", "ER NIC - Class 1"]
    recs = _read([["Payroll Summary"], HEAD,
                  ["2024-07-31 00:00:00", "7478.26", "0", "1943.66", "5534.60", "66"],
                  ["2024-08-31 00:00:00", "7597.90", "432.49", "1991.26", "5174.15", "1048.51"],
                  ["Total", "15076.16", "432.49", "3934.92", "10708.75", "1114.51"], head2,
                  ["A Person"], ["2026-05-09 08:15:25", "2024-07-31", "7478.26", "1943.66", "0", "5534.60", "66"],
                  ["2024-08-28 06:37:34", "2024-08-31", "7597.90", "1991.26", "432.49", "5174.15", "1048.51"]],
                 monkeypatch)
    assert "Total" not in {r.employee_name for r in recs}
    assert round(sum(r.gross_pay for r in recs), 2) == 15076.16
    assert {str(r.period_end) for r in recs} == {"2024-07-31", "2024-08-31"}


def test_statutory_maternity_pay_read_sick_pay_not(monkeypatch):
    head = ["Month", "Gross", "Ee's Tax", "Ee's NI", "Net pay", "Er's ni", "SMP", "SSP"]
    recs = _read([["PAYROLL SUMMARY"], head, ["2024-12-01 00:00:00", "7776.97", "150.4", "60.16", "7465.44", "236.38",
                                               "947.76", "120"], ["Total"]], monkeypatch)
    assert recs[0].statutory_pay_recovered == 947.76 and recs[0].gross_pay == 7776.97
