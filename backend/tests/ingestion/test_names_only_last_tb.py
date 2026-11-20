"""Last year's TB with names only and no working paper (the ETB opening columns are otherwise empty): each line
takes this year's code for the same account name; nothing unless every line is found and they balance."""
from types import SimpleNamespace as NS

from backend.app.services.review.last_year_read import LastYearLine, code_names_only

RECORDS = [NS(raw_account_name="Natwest Business Account", std_code=4800),
           NS(raw_account_name="VAT (Current liabilities - creditors < 1 year)", std_code=5300),
           NS(raw_account_name="Balance b/fwd (Profit and loss account)", std_code=8000)]


def test_each_line_takes_this_years_code():
    lines = [LastYearLine("Natwest Business Account", None, 10106.90),
             LastYearLine("VAT (Current liabilities - creditors < 1 year)", None, -31643.52),
             LastYearLine("Balance b/fwd (Profit and loss account)", None, 21536.62)]
    assert code_names_only(lines, RECORDS) == {4800: 10106.90, 5300: -31643.52, 8000: 21536.62}


def test_nothing_when_a_line_is_not_found_or_it_does_not_balance():
    lines = [LastYearLine("Natwest Business Account", None, 100.0), LastYearLine("Unknown", None, -100.0)]
    assert code_names_only(lines, RECORDS) == {}
    assert code_names_only([LastYearLine("Natwest Business Account", None, 100.0)], RECORDS) == {}
