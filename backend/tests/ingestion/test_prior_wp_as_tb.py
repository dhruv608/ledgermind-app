"""Last year's final working paper set as last year's TB: read from its ETB final balances
('Xero NC | ... | Final balances' over Debit | Credit), not its first sheet; codes 4000-9999 as they are and the P&L
closed into 8000; a plain TB set as well is preferred."""
import io

import openpyxl

from backend.app.services.ingestion.last_year_adjustments import etb_final
from backend.app.services.review.last_year_common import prior_tb_frame


def _paper() -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = "A"
    wb.active["A1"] = "Working paper index"            # the first sheet: no balances
    ws = wb.create_sheet("B - ETB")
    ws["A1"], ws["B1"] = "Client Name - ", "Test Co"
    ws["A7"], ws["B7"], ws["I7"] = "Xero NC", "Nominal Name", "Final balances"
    ws["I8"], ws["J8"] = "Debit £", "Credit £"
    for r, (code, name, dr, cr) in enumerate([(0, "Sales", 0, 10000), (3010, "Salaries", 6000, 0),
                                               (4800, "Bank", 7000, 0), (5400, "Director's loan", 0, 4000),
                                               (7000, "Share capital", 0, 1), (8000, "P&L b/fwd", 1001, 0)], 10):
        ws.cell(row=r, column=1, value=code)
        ws.cell(row=r, column=2, value=name)
        ws.cell(row=r, column=9, value=dr)
        ws.cell(row=r, column=10, value=cr)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_etb_final_debit_credit_pair():
    _end, finals = etb_final(openpyxl.load_workbook(io.BytesIO(_paper()), data_only=True))
    assert finals == {"0": -10000.0, "3010": 6000.0, "4800": 7000.0, "5400": -4000.0, "7000": -1.0, "8000": 1001.0}


def test_paper_as_last_years_tb():
    name, df = prior_tb_frame([("Final WP.xlsx", _paper())])
    rows = {int(r[0]): (r[2], r[3]) for r in df.values.tolist()[1:]}
    # P&L net -4,000 (a profit) closed into 8000: 1,001 - 4,000 = -2,999 (credit)
    assert rows == {4800: (7000.0, 0.0), 5400: (0.0, 4000.0), 7000: (0.0, 1.0), 8000: (0.0, 2999.0)}
    plain = ("Last TB.xlsx", b"Code,Account,Debit,Credit\n4800,Bank,7000,0\n")
    assert prior_tb_frame([("Final WP.xlsx", _paper()), ("Last TB.csv", plain[1])])[0] == "Last TB.csv"


def test_names_only_tb_gives_way_to_the_paper():
    """A last-year TB with an empty Code column (names only) cannot give openings by code: the final paper set as
    well is read instead (openings belong in ETB F-G from last year's ETB final balances)."""
    names_only = b"Code,Account,Debit,Credit\n,Bank,7000,0\n,Director's loan,0,7000\n"
    name, df = prior_tb_frame([("Final WP.xlsx", _paper()), ("Last TB.csv", names_only)])
    assert name == "Final WP.xlsx (ETB final balances)"
    coded = b"Code,Account,Debit,Credit\n4800,Bank,7000,0\n5400,Director's loan,0,7000\n"
    assert prior_tb_frame([("Final WP.xlsx", _paper()), ("Last TB.csv", coded)])[0] == "Last TB.csv"
    assert prior_tb_frame([("Last TB.csv", names_only)])[0] == "Last TB.csv"      # no paper: the TB as it is
