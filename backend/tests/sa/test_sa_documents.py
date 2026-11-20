"""Self Assessment document intake and the P60 checks, with made-up documents (no client data)."""

import io
import zipfile

from backend.app.sa.extract.classify import classify, tax_year_of
from backend.app.sa.extract.p60 import checks, clean, from_text
from backend.app.sa.intake import intake

P60_TEXT = """P60 End of Year Certificate 2025/26 EMPLOYER DETAILS Name Example Trading Limited PAYE reference 120/AB12345
EMPLOYEE DETAILS National Insurance number QQ123456C PAY AND INCOME TAX DETAILS Pay Tax deducted
In previous employment(s) £1,000.00 £100.00 In this employment £30,000.00 £3,486.00 Total for year £31,000.00 £3,586.00
Final tax code 1257L Student Loan deductions £0.00 Postgraduate Loan deductions £12.00"""


def test_p60_from_text():
    f = from_text(P60_TEXT)
    assert (f["pay_this"], f["tax_this"], f["pay_total"], f["tax_total"]) == (30000.0, 3486.0, 31000.0, 3586.0)
    assert (f["tax_year"], f["paye_ref"], f["tax_code"], f["employer"]) == ("2025-26", "120/AB12345", "1257L",
                                                                              "Example Trading Limited")
    assert checks(f, "2025-26", "QQ123456C") == ("READ", [])


def test_p60_checks():
    f = from_text(P60_TEXT)
    assert checks(f, "2024-25", None)[0] == "OTHER_YEAR"
    status, notes = checks(f, "2025-26", "AB654321D")
    assert status == "CHECK" and "NI number" in notes[0]
    status, notes = checks(f, "2025-26", None, {"pay_this": 30000.0, "tax_this": 3468.0})
    assert status == "CHECK" and "disagree on the tax" in notes[0]
    assert clean({"paye_ref": "190G364"})["paye_ref"] == "190/G364"
    # 'Gross Pay' before the pension printed beside 'Pay' for tax (made-up figures): the taxable pay is used
    f = clean({"pay_this": 38000, "tax_this": 4700, "pay_previous": 0, "tax_previous": 0, "pay_total": 36000,
               "tax_total": 4700})
    assert f["pay_this"] == 36000 and f["gross_before_pension"] == 38000
    f = clean({"pay_this": 38000, "tax_this": 4700, "pay_previous": 0, "pay_total": 36000, "tax_total": 4000})
    assert f["pay_this"] == 38000                                             # the tax disagrees too: left to check


def test_classify():
    assert classify("Your annual Mortgage\nInterest statement", "x.pdf") == "MORTGAGE_INTEREST"
    assert classify("", "Sam P60.PNG") == "P60"
    assert tax_year_of("for the tax year to 5 April 2026") == "2025-26"


def test_intake_zip_junk_duplicates_and_locks():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("docs/note.txt", "hello")
        z.writestr("__MACOSX/docs/._note.txt", "junk")
        z.writestr(".DS_Store", "junk")
    items = intake([("bundle.zip", buf.getvalue()), ("Thumbs.db", b"x"), ("scan.png", b"\x89PNG\r\n\x1a\n")])
    assert [i.name for i in items] == ["bundle.zip/docs/note.txt", "scan.png"]
    assert items[1].image and items[0].text == "hello"
    assert intake([("photo.heic", b"x")])[0].unreadable


def test_working_paper_sheet_is_not_the_p45_it_mentions():
    from backend.app.sa.extract.classify import classify
    assert classify("[PAYE] Employer 2 P45 Left 28/05/2024", "Working Papers Property & PAYE 2025-26.xls") == "WORKING_PAPER"
    assert classify("Clients Name: A [Queries] P60", "Client A.xlsx") == "WORKING_PAPER"
    assert classify("P45 details of employee leaving work", "scan.pdf") == "P45"


def test_owner_check_on_a_p60():
    from backend.app.sa.extract import p60
    assert p60.owner("Andrew Scammell", "Toni Scammell") == "OTHER"          # a spouse's P60 in the same folder
    assert p60.owner("Maria Smith", "Maria Laka") == "NAME"                  # a maiden name: counted, to check
    assert p60.owner("Maria Laka", "Maria Milena Laka") is None and p60.owner(None, "Maria Laka") is None
    # A letter doubled and a Gujarati honorific are the same forename; a different one is not (made-up names)
    assert p60.owner("Miss Karen Example", "Karren Example") is None and p60.owner("Amit Example", "Amitbhai Example") is None
    assert p60.owner("Sian Example", "Sean Example") == "OTHER" and p60.owner("Gurdeep Example", "Billy Example") == "OTHER"
    # Surname first with no comma, the French way: the person's own name turned round
    assert p60.owner("MR EXAMPLE NEIL", "Neil Example") is None and p60.owner("EXAMPLE TONI", "Neil Example") == "OTHER"
    # 'Dee' is short for Delicia: her own P60, and under her maiden name a name to check
    assert p60.owner("DELICIA EXAMPLE", "Dee Example") is None and p60.owner("Ms Delicia Other", "Dee Example") == "NAME"
    f = {"pay_this": 30000.0, "tax_this": 3000.0, "tax_year": "2025-26", "employee": "Andrew Example"}
    status, notes = p60.checks(f, "2025-26", None, person="Toni Example")
    assert status == "CHECK" and f["other_person"] and "not used" in notes[0]


def test_owner_by_ni_number_first():
    # R-IN-07: 'match on NINO, not name': a maiden name with the person's NI number is theirs; a matching name with
    # another NI number is not
    from backend.app.sa.extract import p60
    f = {"pay_this": 30000.0, "tax_this": 3000.0, "tax_year": "2025-26", "employee": "Maria Smith", "ni_number": "QQ 12 34 56 C"}
    assert p60.checks(f, "2025-26", "QQ123456C", person="Maria Laka") == ("READ", [])
    g = {"pay_this": 30000.0, "tax_this": 3000.0, "tax_year": "2025-26", "employee": "Maria Laka", "ni_number": "QQ654321A"}
    status, notes = p60.checks(g, "2025-26", "QQ123456C", person="Maria Laka")
    assert status == "CHECK" and g["other_person"] and "NI number" in notes[0]


def test_employee_name_from_a_text_p60():
    from backend.app.sa.extract.p60 import from_text
    t = ("P60 End of Year Certificate Tax year to 5 April 2026 EMPLOYEE DETAILS Surname Example Forename(s) Alex "
         "Works/payroll number 12 National Insurance number QQ 12 34 56 C PAY AND INCOME TAX DETAILS Pay Tax deducted "
         "In previous employment(s) £0.00 £0.00 In this employment £9,900.00 £0.00 Total for year £9,900.00 £0.00")
    assert from_text(t)["employee"] == "Alex Example"


def test_pension_p60_payer():
    from backend.app.sa.extract.p60 import is_pension
    assert is_pension("The MetLife Personal Pension Scheme") and is_pension("Trustees of the ABC Scheme")
    assert not is_pension("Crown Paints Limited") and not is_pension("Pensionable Pay Ltd")
    # An employee benefits scheme and the pension-only firms; an insurer that also employs people stays a job
    assert is_pension("Practical Action Employee Benefits Scheme Ltd") and is_pension("Standard Life")
    assert not is_pension("Aviva Employment Services") and not is_pension("Standard Chartered Bank")


def test_working_paper_year():
    from backend.app.sa.extract.classify import classify, working_paper_year
    assert working_paper_year("Year ending: 31st March 2026 Sales", "Working papers March 26.xlsx") == "2025-26"
    assert working_paper_year("Year ended 5th April 2025", "workings Client 2026.xlsx") == "2025-26"   # a stale header
    assert working_paper_year("Year ending: 5th April 2026", "Working Papers 2025-26...xls") == "2025-26"
    assert working_paper_year("", "Client FY2024-2025.xlsx") == "2024-25"
    rows = " ".join(f"2025-{m:02d}-01 00:00:00" for m in range(4, 13))
    assert working_paper_year(rows, "Working papers.xlsx") == "2025-26"                              # the rows' dates
    assert classify("Year ended 5th April 2026 Employment", "workings Client 2026.xlsx") == "WORKING_PAPER"


def test_a_files_own_saved_date():
    # R-IN-08: the newest working paper by its own date: an .xlsx's saved date, else the date in the zip
    import io, zipfile
    from backend.app.sa.intake import intake
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:                     # the part of an .xlsx that holds its saved date
        zf.writestr("docProps/core.xml", '<cp:coreProperties><dcterms:modified xsi:type="dcterms:W3CDTF">'
                                         '2026-05-01T09:30:00Z</dcterms:modified></cp:coreProperties>')
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("WP 2025.pdf", date_time=(2026, 3, 2, 10, 0, 0))
        zf.writestr(info, b"%PDF-1.4 not really")
    items = {i.name: i for i in intake([("WP.xlsx", buf.getvalue()), ("papers.zip", z.getvalue())])}
    assert items["WP.xlsx"].saved.startswith("2026-05-01") and items["papers.zip/WP 2025.pdf"].saved == "2026-03-02T10:00"


def test_tax_code_suffix_and_the_ni_table():
    # R-FAM-04 and R-NIC-02
    from backend.app.sa.extract.p60 import code_parts, code_points
    assert code_parts("1131N")["suffix"] == "N" and code_parts("K475")["k"] and code_parts("1257L M1")["emergency"]
    assert code_parts("S1257L")["suffix"] == "L" and code_parts("1257L X")["emergency"] and code_parts("BR")["flat"]
    pts = code_points([{"employer": "A Ltd", "tax_code": "1131N", "earnings_at_lel": 5200.0}], None, 6500)
    assert [p["key"] for p in pts] == ["code_n:A Ltd", "lel:A Ltd"]
    assert code_points([{"employer": "A Ltd", "tax_code": "1131N"}], "TRANSFERRED", 6500) == []   # already set
    assert [p["key"] for p in code_points([{"employer": "B", "tax_code": "1391L M1"}], None, 6500)] == ["code_x:B"]


def test_owner_with_initials():
    from backend.app.sa.extract import p60
    assert p60.owner("Mr P N Fairbourne", "Paul Fairbourne") is None and p60.owner("Mr R Pennyworth", "Robert Pennyworth") is None
    assert p60.owner("A Other", "Paul Fairbourne") == "OTHER" and p60.owner("Fairbourne", "Paul Fairbourne") is None


def test_old_word_files_and_protected_workbooks():
    from backend.app.sa import intake
    doc = intake.OLE + b"\x00\x01binary\x00Dear Sam, the total Foster Care Allowances paid are: Amount \xa353289.73\x00\x02"
    item = intake.intake([("letter.doc", doc)])[0]
    assert "Foster Care Allowances" in item.text and "53289.73" in item.text and "\x00" not in item.text
    locked = intake.intake([("accounts.xlsx", intake.OLE + b"encrypted")])[0]
    assert "unprotected copy" in locked.unreadable


def test_a_spreadsheet_that_reads_like_a_p60_is_never_the_form():
    from backend.app.sa.extract.classify import classify
    text = "P60 End of year certificate summary\nEmployer A pay 20,000 tax 2,000\nPension B pay 5,000"
    assert classify(text, "Master Tax Summary Sheet 2024 to 2025.xlsx") == "WORKING_PAPER"
    assert classify(text, "Client A/Our working/2024-25.xlsx") == "WORKING_PAPER"
    assert classify(text, "pensions list.xlsx") == "OTHER"          # filed for the accountant to look at
    assert classify(text, "P60 2025.pdf") == "P60"                  # the form itself


def test_a_blank_tax_box_under_the_tax_code_allowance_is_nil_tax():
    base = {"tax_year": "2024-25", "employee": "A Person", "employer": "Employer A", "pay_this": 9096.0, "pay_total": 9096.0,
            "tax_this": None, "tax_code": "1257L"}
    status, notes = checks(dict(base), "2024-25", None, dict(base), "A Person")
    assert status == "READ" and notes == []
    # Over the allowance, or a code that taxes from the first pound: a blank box is still a point to look at
    assert checks(dict(base, pay_this=20000.0, pay_total=20000.0), "2024-25", None, None, "A Person")[0] == "CHECK"
    assert checks(dict(base, tax_code="BR"), "2024-25", None, None, "A Person")[0] == "CHECK"
    assert checks(dict(base, tax_code="1257L M1"), "2024-25", None, None, "A Person")[0] == "CHECK"


def test_a_double_barrelled_surname_with_the_persons_surname_is_theirs():
    from backend.app.sa.extract.p60 import owner
    assert owner("Mr Person Alpha-Beta", "Person Alpha") is None
    assert owner("Person Beta", "Person Alpha") == "NAME"               # a different surname: still a point to check
    assert owner("Other Alpha-Beta", "Person Alpha") == "OTHER"         # a different forename: someone else's


def test_a_banks_surname_first_with_initials_is_the_persons():
    from backend.app.sa.extract.p60 import owner
    assert owner("ALPHA PE", "Person E Alpha") is None
    assert owner("ALPHA Q", "Person Alpha") == "OTHER"             # another initial: someone else


def test_a_list_of_cis_payments_is_not_a_p60():
    f = {"tax_year": "2024-25", "employee": "A Person", "employer": None, "paye_ref": None, "pay_this": 44140.0,
         "tax_this": 8828.0, "tax_code": None}
    status, notes = checks(f, "2024-25", None, None, "A Person")
    assert status == "CHECK" and f.get("looks_cis") and "CIS" in notes[0]
    real = {"tax_year": "2024-25", "employee": "A Person", "employer": "Employer A", "paye_ref": "123/A456", "pay_this": 30000.0,
            "tax_this": 6000.0, "tax_code": "BR"}
    assert not checks(dict(real), "2024-25", None, None, "A Person")[1] or not real.get("looks_cis")


def test_a_p60_only_one_reader_found_is_not_entered():
    f = {"tax_year": "2024-25", "employee": "A Person", "employer": "Employer A", "paye_ref": "123/A456", "pay_this": 35000.0,
         "tax_this": 4500.0, "tax_code": "1257L"}
    status, notes = checks(f, "2024-25", None, {"pay_this": None, "tax_this": None}, "A Person")
    assert status == "CHECK" and f.get("one_reader") and any("Only one of the two readers" in n for n in notes)


def test_a_p60s_printed_year_wins():
    from backend.app.sa.extract import p60
    assert p60.printed_year("P60 End of Year Certificate\nTax year to 5 April\n2025\nTo the employee") == "2024-25"
    assert p60.printed_year("P60 End of Year Certificate 2025-26") == "2025-26"
    assert p60.printed_year("Tax year to 5 April 2025 ... tax year 2025-26") is None        # two years: the readers'
    assert p60.printed_year("") is None and p60.printed_year(None) is None


def test_a_p60s_year_is_worked_out_from_the_year_printed():
    assert clean({"year_to": 2025, "tax_year": "2025-26", "pay_this": 100})["tax_year"] == "2024-25"
    assert clean({"year_to": "2026"})["tax_year"] == "2025-26"
    assert clean({"tax_year": "2024-25"})["tax_year"] == "2024-25" and clean({"year_to": "x"})["tax_year"] is None


def test_a_br_or_d0_code_and_a_different_surname_are_points():
    """BR / D0 on a job is a signal; a P60 in another surname is off the return until confirmed."""
    from backend.app.sa.extract import p60
    from backend.app.sa.extract.p60 import code_points
    assert [p["key"] for p in code_points([{"employer": "B Ltd", "tax_code": "BR"}], None, 6500)] == ["code_flat:B Ltd"]
    assert [p["key"] for p in code_points([{"employer": "B Ltd", "tax_code": "D0"}], None, 6500)] == ["code_flat:B Ltd"]
    f = p60.clean({"kind": "P60", "year_to": 2026, "employee": "Person Beta", "employer": "C Ltd", "pay_this": 20000,
                   "tax_this": 1500})
    status, notes = p60.checks(f, "2025-26", None, person="Person Alpha")
    # Kept on the return (most are the person's own), marked so the return cannot be finished until it is confirmed
    assert status == "CHECK" and f.get("name_check") and not f.get("other_person") and "confirm it before" in notes[0]
