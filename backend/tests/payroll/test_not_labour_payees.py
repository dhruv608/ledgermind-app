"""Payees in a subcontractor account whose names say they supply something that is not labour."""
from backend.app.services.review.subcontractors import not_labour


def test_non_labour_services():
    assert not_labour("JAD WINDOW CLEANERS") == "cleaning"
    assert not_labour("K J COFFEE SOLUTIONS") == "coffee / vending supplies"
    assert not_labour("4 SEASONS ENVIRONMENTAL SERVICES") == "pest control / environmental services"
    assert not_labour("A & G PLUMBING AND HEATING") == ""
    assert not_labour("JRB ELECTRICAL SERVICES") == ""
