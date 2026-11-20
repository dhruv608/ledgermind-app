"""Loan repayments in a cost account (e.g. a BBLS and a bank business loan in 'Formation Costs')."""
from types import SimpleNamespace as NS

from backend.app.services.review.loan_repayments import _lender, loan_account


def test_lender_words():
    assert _lender("No Name - Bbls Loan BBLS LOAN///") == "BBLS loan"
    assert _lender("No Name - Nwb Business Loan 01063453490851") == "Business loan"
    assert _lender("Funding Circle repayment") == "Funding Circle"
    assert _lender("Sir Thomas White Charity Loan - SIR THOMAS WHITE 7889") is None     # a charity scheme: asked
    assert _lender("BBLS loan interest") is None                                           # interest is a cost
    assert _lender("Formation of company") is None


def test_loan_account_after_one_year_first():
    tb = [NS(std_code=5100, net_amount=-15436.23), NS(std_code=5500, net_amount=-29795.73)]
    assert loan_account(tb) == 5500
    assert loan_account([NS(std_code=5100, net_amount=-100.0)]) == 5100
    assert loan_account([NS(std_code=3380, net_amount=500.0)]) is None
