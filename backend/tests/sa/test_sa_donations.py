"""Charity donations as Gift Aid (made-up charities): the tax year's donations, totals left out, 'not Gift Aid' out."""

from backend.app.sa.extract import donations as D
from backend.app.sa.extract.classify import classify


def test_the_years_donations():
    f = D.clean({"donor": "Pat Giver", "donations": [
        {"date": "2025-04-01", "charity": "A Trust", "amount": 20, "gift_aid": None},          # before 6 April: last year
        {"date": "2025-05-01", "charity": "B Church", "amount": "300", "gift_aid": True},
        {"date": "2025-06-01", "charity": "C Fund", "amount": 50, "gift_aid": False},          # not Gift Aided: out
        {"date": "2026-03-01", "charity": "TOTAL", "amount": 370}]})                             # a total row: out
    status, notes = D.checks(f, "2025-26", "Pat Giver")
    assert status == "CHECK" and f["total"] == 300.0 and "£300.00" in notes[0]


def test_donation_papers_by_name():
    assert classify("", "Charity donations.pdf") == "DONATIONS"
    assert classify("", "Nationwide_charity_donations_2025-26.csv") == "DONATIONS"


def test_sipp_top_ups_and_no_wrapper_questions():
    from types import SimpleNamespace as N
    from backend.app.sa.extract import sipp_csv
    from backend.app.sa.lastyear import question
    data = (b"Title,Type,Timestamp,Account Currency,Total Amount in Account Currency\n"
            b"Top up,TOP_UP,2025-06-01T10:00:00Z,GBP,2000.00\nTop up,TOP_UP,2026-05-01T10:00:00Z,GBP,500.00\n"
            b"Some Co,DIVIDEND,2025-07-01T10:00:00Z,GBP,40.00\nSome Co,ORDER,2025-07-02T10:00:00Z,GBP,1500.00\n")
    assert sipp_csv.looks_like("platform_SIPP_export.csv", data)
    f = sipp_csv.as_pension("platform_SIPP_export.csv", data, "2025-04-06", "2026-04-05")
    assert f["items"][0]["amount"] == 2000.0 and f["items"][0]["basis"] == "RELIEF_AT_SOURCE"
    assert question(N(source="SAVINGS", kind="INTEREST", name="Platform SIPP", ref=None, last_amount=5), 2026) is None
    assert question(N(source="SAVINGS", kind="INTEREST", name="A Bank Saver", ref=None, last_amount=5), 2026)


def test_gifts_by_two_people_need_the_declaration_in_this_persons_name():
    from backend.app.sa.extract import donations as D
    f = D.clean({"donor": "Mr A and Mrs B Person", "donations": [{"date": "2024-06-01", "charity": "Charity A", "amount": 100, "gift_aid": True}]})
    status, notes = D.checks(f, "2024-25", "A Person")
    assert status == "CHECK" and "R-SAV-08" in notes[0]
