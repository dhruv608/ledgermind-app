"""Last year's TB code the firm chart lacks takes its parent code in the same ten (a loan on 5501 is
not lost); the opening goes to the account of the same name."""
from types import SimpleNamespace as NS

from backend.app.services.review.last_year_common import LastYearLine, pick_account
from backend.app.services.review.last_year_read import in_chart

NAMES = {5500: "Bank loans", 5510: "Other loans", 5100: "Bank loans"}


def test_unknown_code_to_parent():
    assert in_chart(LastYearLine("Funding Circle Loan", 5501, -5357.19), NAMES) == \
        LastYearLine("Funding Circle Loan", 5500, -5357.19)
    assert in_chart(LastYearLine("Bank loans", 5500, -1.0), NAMES).code == 5500        # known: as it is
    assert in_chart(LastYearLine("Odd", 5599, -1.0), NAMES).code == 5599                # no parent: as it is


def test_opening_to_the_same_name():
    same = [NS(raw_account_name="Bounce Back Loan", net_amount=5447.43, opening_amount=0.0),
            NS(raw_account_name="Funding Circle loan", net_amount=6222.60, opening_amount=0.0),
            NS(raw_account_name="Funding Circle Loan 3", net_amount=13704.33, opening_amount=0.0)]
    assert pick_account(LastYearLine("Funding Circle Loan", 5500, -5357.19), same).raw_account_name == "Funding Circle loan"
    assert pick_account(LastYearLine("Bounce Back Loan", 5500, -941.61), same).raw_account_name == "Bounce Back Loan"


def test_codes_not_in_chart_are_listed_to_confirm(monkeypatch):
    import pandas as pd
    from types import SimpleNamespace as NS
    from backend.app.services.review import last_year_read as lyr
    from backend.app.services.review.last_year_common import LastYearLine
    monkeypatch.setattr(lyr, "_prior_frame", lambda eng: ("Last TB.xlsx", pd.DataFrame()))
    monkeypatch.setattr(lyr, "chart_names", lambda db: {5500: "Bank loans", 5350: "Other creditors"})
    monkeypatch.setattr(lyr, "firm_coded_lines", lambda df, names: [LastYearLine("PNB Loan-904", 5500, -600000.0),
                                                                    LastYearLine("PNB Loan-710", 5501, -3545500.0)])
    import backend.app.services.bank_only.books as books
    monkeypatch.setattr(books, "is_books_client", lambda eng: False)
    assert lyr.codes_not_in_chart(NS(), None) == [("PNB Loan-710", 5501, 5500, -3545500.0)]
