"""A review point's query carries only the words for the client (its question and what to send): the accountant's
working and steps stay on the point's card, and so out of the client email."""
from backend.app.services.queries.query_list import client_words


def test_question_after_the_working():
    details = ("No expense recorded in the final month for a regular cost. Cost recorded in 10 of 12 months; average "
               "monthly cost £518.16 (for review only). Client question: This expense usually occurs every month but is "
               "missing in February 2026. Please confirm whether an accrual should be recorded.")
    words = client_words(details)
    assert words.startswith("This expense usually occurs every month")
    assert "for review only" not in words and "Cost recorded" not in words


def test_question_and_evidence_lines_without_references():
    details = ("What the app found: 5300 - VAT Suspense: £169.28\n\nQuery to the client: Please provide an analysis of "
               "the items making up this balance.\nEvidence: Transaction listing for the account. Ref: -; -")
    assert client_words(details) == ("Please provide an analysis of the items making up this balance. "
                                     "Please send: Transaction listing for the account.")


def test_point_with_no_question_has_no_words():
    assert client_words("20% reducing balance on £1,115.12 gives £223.02; the books show £0.00.") == ""
